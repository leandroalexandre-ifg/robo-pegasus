"""Estado de um tablet conectado e execução dos seus turnos de conversa."""

import asyncio
import collections
import contextlib
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import numpy as np
import openai
from fastapi import WebSocket

from app import registro
from app.config import Config
from app.pipeline import ativacao, stt, tts
from app.pipeline.emocao import Emocao
from app.pipeline.turno import BlocoAudio, Turno, falar, transcrever
from app.pipeline.vad import DetectorFala
from app.saude import MonitorLLM
from app.wav import TAXA_ENTRADA

log = logging.getLogger("pegasus.sessao")

MAX_AUDIO_S = 30
_MAX_BYTES = MAX_AUDIO_S * TAXA_ENTRADA * 2
BLOCO_SAIDA_S = 0.1
# Quanto o abort espera a limpeza do turno cancelado (fechar o fluxo do LLM etc.)
# antes de seguir sem ela.
ESPERA_CANCELAMENTO_S = 0.5
# Um tablet que não lê o que o servidor envia (rede travada) não segura o turno.
ENVIO_LIMITE_S = 10
# Margens mantidas em volta da fala detectada, para o Whisper não perder sílabas.
PRE_FALA_S = 0.3
POS_FALA_S = 0.2
# Escuta contínua (ativação por palavra): áudio guardado enquanto ninguém fala,
# para ter a margem antes da fala quando ela começar.
VIGIA_GUARDA_S = 1.0
_VIGIA_LIMITE_BYTES = round(2 * VIGIA_GUARDA_S * TAXA_ENTRADA) * 2
SAUDACAO = "Oi?"  # resposta a uma fala que é só a palavra de ativação
DESPEDIDA = "Tchau! Até a próxima."  # resposta a "tchau, Pegasus" no modo palavra
# Uma fala da escuta contínua mais longa que isso não é um chamado (ruído ou conversa
# da sala) e é descartada sem transcrever: o Whisper fica lento e inventa texto com
# ruído longo.
MAX_FALA_PALAVRA_S = 10


def _amostras(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


class _Portao:
    """Segura o envio de um turno começado antes da hora (prévia) até a decisão.

    `abrir` espera o fim da fala e diz se o turno ainda vale; roda uma vez só."""

    def __init__(self, abrir: Callable[[], Awaitable[bool]]):
        self._abrir = abrir
        self.aberto: bool | None = None

    async def passar(self) -> bool:
        if self.aberto is None:
            self.aberto = await self._abrir()
        return self.aberto


def _esperar(liberar: asyncio.Event) -> Callable[[], Awaitable[bool]]:
    async def abrir() -> bool:
        await liberar.wait()
        return True

    return abrir


async def _passou(portao: _Portao | None) -> bool:
    return portao is None or await portao.passar()


@dataclass
class _Previa:
    """Turno começado com PEGASUS_VAD_PREVIA_MS de silêncio: transcreve e gera, mas
    só envia quando o VAD confirmar o fim da fala. Vale para a fala cujo silêncio
    começou na amostra `fim`; se a pessoa voltar a falar, é cancelado."""

    fim: int
    turno: Turno
    liberar: asyncio.Event
    tarefa: asyncio.Task


class Sessao:
    def __init__(
        self, ws: WebSocket, config: Config, device_id: str, monitor: MonitorLLM | None = None
    ):
        self.monitor = monitor
        self.ws = ws
        self.config = config
        self.device_id = device_id
        self.id = secrets.token_hex(4)
        self.estado = "ocioso"
        self._audio = bytearray()
        self._descartadas = 0  # amostras do início do áudio já jogadas fora (escuta contínua)
        self._vad: DetectorFala | None = None
        # Muda a cada ativação, listen_start ou abort: uma fala da escuta contínua
        # que ainda estava sendo transcrita nesse momento é descartada.
        self._epoca = 0
        self._turno: asyncio.Task | None = None
        self._previa: _Previa | None = None
        # Verificações da escuta contínua ainda vivas: uma espera a outra, e todas
        # são canceladas juntas (abort, listen_start, queda do LLM).
        self._verificacoes: set[asyncio.Task] = set()
        self._frase_aberta = False
        # Modo palavra: escuta aberta sem precisar do nome (depois do "Oi?" ou de uma
        # resposta). O prazo sem fala da escuta atual fica em `_sem_fala_s`.
        self._conversando = False
        self._sem_fala_s = config.vad_sem_fala_s
        # Memória curta: (fala do usuário, resposta) dos últimos turnos desta conexão.
        self.historico: collections.deque[tuple[str, str]] = collections.deque(
            maxlen=config.memoria_turnos
        )
        # O receptor de mensagens e a tarefa do turno enviam pela mesma conexão.
        self._envio = asyncio.Lock()

    async def _enviar(self, envio) -> None:
        async with self._envio:
            try:
                await asyncio.wait_for(envio, ENVIO_LIMITE_S)
            except TimeoutError:
                log.warning("sessão %s: envio travado por %d s; fechando", self.id, ENVIO_LIMITE_S)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self.ws.close(4008, "envio travado"), 1)
                raise

    async def enviar_json(self, mensagem: dict) -> None:
        await self._enviar(self.ws.send_text(json.dumps(mensagem, ensure_ascii=False)))

    async def enviar_audio(self, pcm: bytes) -> None:
        await self._enviar(self.ws.send_bytes(pcm))

    def estado_livre(self) -> str:
        """Estado fora de um turno: ocioso, ou desconectado com o LLM fora do ar."""
        if self.monitor is not None and not self.monitor.disponivel:
            return "desconectado"
        return "ocioso"

    async def ao_llm(self, disponivel: bool) -> None:
        """O monitor viu o LLM cair ou voltar."""
        if not disponivel:
            if self.estado == "desconectado":
                return  # o turno que falhou já avisou
            self._epoca += 1
            await self.cancelar_turno()
            self._limpar_audio()
            await self.mudar_estado("desconectado")
        elif self.estado == "desconectado":
            await self.mudar_estado("ocioso")

    async def mudar_estado(self, estado: str) -> None:
        if estado in ("ocioso", "desconectado") and self._conversando:
            self._conversando = False
            await self.enviar_json({"type": "conversation", "state": "esperando_nome"})
        self.estado = estado
        await self.enviar_json({"type": "state", "state": estado})

    def _limpar_audio(self) -> None:
        if self._previa is not None:
            self._previa.tarefa.cancel()  # a fala da prévia não vale mais
            self._previa = None
        self._audio.clear()
        self._descartadas = 0
        self._vad = None

    async def _abrir_escuta(self, sem_fala_s: float | None = None) -> None:
        self._limpar_audio()
        self._vad = DetectorFala(self.config)
        self._sem_fala_s = sem_fala_s or self.config.vad_sem_fala_s
        await self.mudar_estado("ouvindo")

    async def _conversar(self, prazo_s: float) -> None:
        """Modo palavra: abre a escuta sem exigir o nome. A próxima fala é pergunta;
        sem fala em `prazo_s` (contado no áudio recebido, isto é, depois de a voz do
        robô tocar), volta a esperar o nome."""
        self._conversando = True
        await self.enviar_json(
            {"type": "conversation", "state": "conversando", "timeout_ms": round(prazo_s * 1000)}
        )
        await self._abrir_escuta(prazo_s)

    async def ao_listen_start(self) -> None:
        if self.estado_livre() == "desconectado":
            await self.mudar_estado("desconectado")  # sem LLM, o robô não escuta
            return
        self._epoca += 1
        await self.cancelar_turno()  # falar por cima interrompe o robô
        await self._abrir_escuta()

    async def ao_audio(self, dados: bytes) -> None:
        if self.estado == "ocioso" and self.config.ativacao == "palavra":
            await self._vigiar(dados)
            return
        if self.estado != "ouvindo" or self._vad is None:
            self._limpar_audio()  # meio-duplex: áudio fora da escuta é descartado
            return
        self._audio += dados[: _MAX_BYTES - len(self._audio)]
        if self._vad.processar(dados) == "fim":
            await self._encerrar_escuta("vad")
        elif len(self._audio) >= _MAX_BYTES:
            await self._encerrar_escuta("limite")
        elif not self._vad.falou and len(self._audio) >= self._sem_fala_s * 2 * TAXA_ENTRADA:
            log.info("sessão %s: escuta sem fala; voltando a ocioso", self.id)
            self._limpar_audio()
            await self.mudar_estado(self.estado_livre())
        else:
            self._acompanhar_previa(
                lambda pcm, turno, liberar: asyncio.create_task(
                    self._responder(pcm, turno, portao=_Portao(_esperar(liberar)))
                )
            )

    def _acompanhar_previa(
        self, iniciar: Callable[[bytes, Turno, asyncio.Event], asyncio.Task]
    ) -> None:
        """Começa o turno com PEGASUS_VAD_PREVIA_MS de silêncio e o cancela se a pessoa
        voltar a falar antes de o VAD decidir que a fala acabou."""
        vad = self._vad
        if self._previa is not None and self._previa.fim != vad.fim:
            self._previa.tarefa.cancel()
            self._previa = None
        previa_s = self.config.vad_previa_s
        if self._previa is None and previa_s and vad.fim is not None and vad.silencio_s >= previa_s:
            turno = Turno()
            turno.vad_s = vad.silencio_s
            liberar = asyncio.Event()
            tarefa = iniciar(self._recortar(), turno, liberar)
            self._previa = _Previa(vad.fim, turno, liberar, tarefa)

    def _tomar_previa(self) -> _Previa | None:
        """A prévia, se ela for da fala que acabou de terminar; senão, a cancela."""
        previa, self._previa = self._previa, None
        if previa is None:
            return None
        if self._vad is None or previa.fim != self._vad.fim:
            previa.tarefa.cancel()
            return None
        previa.turno.marcar("liberado")
        return previa

    async def ao_listen_stop(self) -> None:
        if self.estado == "ouvindo":
            await self._encerrar_escuta("listen_stop")

    def _recortar(self) -> bytes:
        """O áudio da escuta, recortado em volta da fala que o VAD detectou."""
        pcm = bytes(self._audio[: len(self._audio) // 2 * 2])
        vad = self._vad
        if vad is None or not vad.falou:
            return pcm  # listen_stop sem fala detectada: o Whisper decide
        # Os instantes do VAD contam desde o início da escuta; o áudio guardado
        # pode ter perdido o começo (escuta contínua).
        total = len(pcm) // 2
        inicio = max(0, vad.inicio - self._descartadas - round(PRE_FALA_S * TAXA_ENTRADA))
        fim = total
        if vad.fim is not None:
            fim = min(total, vad.fim - self._descartadas + round(POS_FALA_S * TAXA_ENTRADA))
        return pcm[2 * inicio : 2 * fim]

    def _fechar_fala(self, motivo: str) -> tuple[bytes, Turno]:
        """Recorta a fala detectada e zera a escuta; o Turno marca o fim da fala."""
        turno = Turno()
        turno.fim_escuta = motivo
        turno.vad_s = self._vad.silencio_s if self._vad is not None else 0.0
        pcm = self._recortar()
        self._limpar_audio()
        return pcm, turno

    async def _encerrar_escuta(self, motivo: str) -> None:
        if previa := self._tomar_previa():
            previa.turno.fim_escuta = motivo
            self._limpar_audio()
            await self.mudar_estado("pensando")
            self._turno = previa.tarefa
            previa.liberar.set()
            return
        pcm, turno = self._fechar_fala(motivo)
        if not pcm:
            await self.mudar_estado(self.estado_livre())
            return
        await self.mudar_estado("pensando")
        self._turno = asyncio.create_task(self._responder(pcm, turno))

    async def ao_abort(self) -> None:
        self._epoca += 1
        await self.cancelar_turno()
        self._limpar_audio()
        await self.mudar_estado(self.estado_livre())

    async def _vigiar(self, dados: bytes) -> None:
        """Escuta contínua em `ocioso`: separa as falas com o VAD e manda cada uma
        verificar a palavra de ativação. Nada do que não for ativação é guardado."""
        if self._vad is None:
            self._limpar_audio()
            self._vad = DetectorFala(self.config)
        self._audio += dados
        evento = self._vad.processar(dados)
        if self._vad.fala_s > MAX_FALA_PALAVRA_S:
            self._limpar_audio()  # o próximo áudio começa um detector novo
            return
        if evento == "fim":
            if previa := self._tomar_previa():
                previa.turno.fim_escuta = "ativacao"
                self._limpar_audio()
                self._turno = previa.tarefa
                previa.liberar.set()
                return
            pcm, turno = self._fechar_fala("ativacao")
            self._turno = self._nova_verificacao(pcm, turno)
        elif not self._vad.falou and len(self._audio) > _VIGIA_LIMITE_BYTES:
            corte = len(self._audio) - round(VIGIA_GUARDA_S * TAXA_ENTRADA) * 2
            del self._audio[:corte]
            self._descartadas += corte // 2
        else:
            self._acompanhar_previa(self._nova_verificacao)

    def _nova_verificacao(
        self, pcm: bytes, turno: Turno, liberar: asyncio.Event | None = None
    ) -> asyncio.Task:
        # Uma verificação de cada vez, na ordem das falas: a nova espera a anterior.
        anterior = self._turno if self._turno is not None and not self._turno.done() else None
        tarefa = asyncio.create_task(self._verificar(pcm, turno, self._epoca, anterior, liberar))
        self._verificacoes.add(tarefa)
        tarefa.add_done_callback(self._verificacoes.discard)
        return tarefa

    async def _verificar(
        self,
        pcm: bytes,
        turno: Turno,
        epoca: int,
        anterior: asyncio.Task | None,
        liberar: asyncio.Event | None = None,
    ) -> None:
        """Transcreve uma fala da escuta contínua e só a atende se ela começar com a
        palavra de ativação. As outras são descartadas sem registro do áudio nem do texto.
        Com `liberar` (prévia), nada é enviado antes de o VAD confirmar o fim da fala."""
        if anterior is not None:
            # Sem propagar o cancelamento: uma prévia cancelada não leva a anterior junto.
            await asyncio.wait({anterior})
        if epoca != self._epoca:
            return
        try:
            texto = await asyncio.wait_for(
                stt.transcrever(_amostras(pcm), self.config), self.config.stt_limite_s
            )
        except Exception as e:
            log.error(
                "sessão %s: falha ao transcrever na escuta contínua (%s)", self.id, type(e).__name__
            )
            return
        pedido = ativacao.pergunta(texto)
        del texto
        if pedido is None:
            return
        turno.marcar("stt")

        async def abrir() -> bool:
            if liberar is not None:
                await liberar.wait()
            if epoca != self._epoca or self.estado != "ocioso":
                return False
            self._epoca += 1  # falas seguintes, ainda na fila, são descartadas
            self._limpar_audio()
            if pedido:
                log.info("sessão %s: ativada pela palavra, com pergunta", self.id)
                await self.mudar_estado("pensando")
            return True

        portao = _Portao(abrir)
        if pedido:
            turno.texto_usuario = pedido
            await self._responder(pcm, turno, pedido, portao)
        elif await portao.passar():
            await self._saudar(turno, len(pcm) / 2 / TAXA_ENTRADA)

    async def _saudar(self, turno: Turno, duracao_s: float) -> None:
        """Só a palavra de ativação: responde "Oi?" e abre a escuta da pergunta."""
        try:
            pcm, taxa = await asyncio.wait_for(
                tts.sintetizar(SAUDACAO, self.config), self.config.tts_limite_s
            )
            await self.mudar_estado("falando")
            await self._enviar_frase(SAUDACAO, pcm, taxa)
            turno.marcar("primeiro_envio")
            await self._conversar(self.config.vad_sem_fala_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("sessão %s: falha na saudação", self.id)
            await self._falhar("Ocorreu um erro no servidor.")
            return
        registro.registrar("ativacao", **self._medidas(turno, duracao_s))

    async def cancelar_turno(self) -> None:
        """Interrompe na hora o turno em andamento: STT, LLM (o fluxo é fechado e o
        vLLM aborta a geração), pedido de emoção, Piper e envio de áudio."""
        tarefa, self._turno = self._turno, None
        vivas = {t for t in (tarefa, *self._verificacoes) if t is not None and not t.done()}
        if vivas:
            inicio = time.perf_counter()
            for t in vivas:
                t.cancel()
            _, pendentes = await asyncio.wait(vivas, timeout=ESPERA_CANCELAMENTO_S)
            ms = (time.perf_counter() - inicio) * 1000
            if pendentes:
                log.warning("sessão %s: limpeza do turno passou de %.0f ms", self.id, ms)
            log.info("sessão %s: turno interrompido em %.0f ms", self.id, ms)
        if self._frase_aberta:
            self._frase_aberta = False
            await self.enviar_json({"type": "tts_end"})

    async def encerrar(self) -> None:
        """Fim da conexão: interrompe o turno e descarta a memória da conversa."""
        try:
            await self.cancelar_turno()
        finally:
            self.historico.clear()

    def _lembrar(self, turno: Turno) -> None:
        # Guarda o que o robô chegou a dizer, mesmo se o turno foi interrompido.
        if turno.texto_usuario and turno.frases and not (turno.reserva or turno.despedida):
            self.historico.append((turno.texto_usuario, turno.resposta))

    async def _responder(
        self,
        pcm: bytes,
        turno: Turno,
        texto: str | None = None,
        portao: _Portao | None = None,
    ) -> None:
        """Responde à fala. Com `texto`, ela já foi transcrita (palavra de ativação).
        Com `portao`, o turno começou antes do fim da fala: transcreve e gera, mas só
        envia algo (inclusive erros) depois de passar por ele."""
        memoria = tuple(self.historico)
        turno.memoria = len(memoria)
        duracao_s = len(pcm) / 2 / TAXA_ENTRADA
        try:
            async with asyncio.timeout(self.config.turno_limite_s):
                if texto is None:
                    texto = await transcrever(_amostras(pcm), self.config, turno)
                    # Na conversa, "Pegasus, e amanhã?" vale como "e amanhã?".
                    if self.config.ativacao == "palavra" and (resto := ativacao.pergunta(texto)):
                        texto = turno.texto_usuario = resto
                await self._falar(texto, turno, memoria, portao)
            if not await _passou(portao):
                return
            await self._depois_da_resposta(turno)
        except asyncio.CancelledError:
            if portao is not None and not portao.aberto:
                raise  # prévia cancelada: a pessoa voltou a falar; não houve turno
            self._lembrar(turno)
            registro.registrar("interrompido", **self._medidas(turno, duracao_s))
            raise
        except Exception as e:
            if await _passou(portao):
                await self._tratar_falha(turno, duracao_s, e)
        else:
            self._lembrar(turno)
            tipo = "despedida" if turno.despedida else "turno" if turno.frases else "sem_fala"
            registro.registrar(tipo, **self._medidas(turno, duracao_s))

    async def _depois_da_resposta(self, turno: Turno) -> None:
        """No modo palavra, cada resposta abre (ou renova) a conversa; uma despedida
        ou uma fala sem resposta volta a esperar o nome."""
        if (
            self.config.ativacao == "palavra"
            and self.config.conversa_s > 0
            and turno.frases
            and not turno.despedida
            and self.estado_livre() == "ocioso"
        ):
            await self._conversar(self.config.conversa_s)
        else:
            await self.mudar_estado(self.estado_livre())

    async def _despedir(self, turno: Turno) -> AsyncIterator[BlocoAudio]:
        """Resposta fixa a uma despedida, sem o LLM e sem emoção."""
        turno.despedida = True
        pcm, taxa = await asyncio.wait_for(
            tts.sintetizar(DESPEDIDA, self.config), self.config.tts_limite_s
        )
        turno.marcar("primeiro_audio")
        turno.frases.append(DESPEDIDA)
        yield BlocoAudio(DESPEDIDA, pcm, taxa)

    async def _tratar_falha(self, turno: Turno, duracao_s: float, e: Exception) -> None:
        if isinstance(e, openai.APIError):
            log.error("sessão %s: falha no LLM (%s)", self.id, type(e).__name__)
            self._registrar_falha(turno, duracao_s, e)
            if self.monitor is not None and isinstance(e, openai.APIConnectionError):
                if not await self.monitor.suspeitar():
                    # Marca já (sem await no meio), para o aviso do monitor, que vem
                    # logo depois, não cancelar este turno no meio do envio do erro.
                    self.estado = "desconectado"
            await self._falhar("O servidor de linguagem não está disponível.")
        elif isinstance(e, TimeoutError):
            log.error("sessão %s: tempo esgotado depois da etapa %s", self.id, turno.etapa)
            self._registrar_falha(turno, duracao_s, e)
            await self._falhar("O servidor demorou demais para responder.")
        else:
            log.error("sessão %s: falha no turno", self.id, exc_info=e)
            self._registrar_falha(turno, duracao_s, e)
            await self._falhar("Ocorreu um erro no servidor.")

    async def _falar(
        self,
        texto: str,
        turno: Turno,
        memoria: tuple[tuple[str, str], ...],
        portao: _Portao | None,
    ) -> None:
        """Envia o `stt` e a resposta. A geração começa já, antes do portão: o primeiro
        bloco (áudio ou emoção) fica pronto enquanto o VAD ainda confirma o fim da fala."""
        resposta = None
        if texto and self.config.ativacao == "palavra" and ativacao.encerra(texto):
            log.info("sessão %s: despedida; volta a esperar o nome", self.id)
            resposta = self._despedir(turno)
        elif texto:
            resposta = falar(texto, self.config, turno, memoria)
        primeiro = asyncio.ensure_future(anext(resposta, None)) if resposta else None
        try:
            if not await _passou(portao):
                return
            await self.enviar_json({"type": "stt", "text": texto})
            if primeiro is None:
                return
            bloco = await primeiro
            while bloco is not None:
                if isinstance(bloco, Emocao):
                    await self.enviar_json({"type": "emotion", "emotion": bloco.nome})
                else:
                    if self.estado != "falando":
                        await self.mudar_estado("falando")
                    await self._enviar_frase(bloco.frase, bloco.pcm, bloco.taxa, turno)
                bloco = await anext(resposta, None)
        finally:
            if primeiro is not None:
                if not primeiro.done():
                    primeiro.cancel()
                with contextlib.suppress(BaseException):
                    await primeiro  # recolhe o erro de uma prévia que não chegou a enviar
                await resposta.aclose()  # fecha o fluxo do LLM e o pedido de emoção

    async def _enviar_frase(self, frase: str, pcm: bytes, taxa: int, turno: Turno | None = None):
        passo = int(taxa * BLOCO_SAIDA_S) * 2
        self._frase_aberta = True
        await self.enviar_json({"type": "tts_start", "text": frase, "sample_rate": taxa})
        for i in range(0, len(pcm), passo):
            await self.enviar_audio(pcm[i : i + passo])
            if turno is not None:
                turno.marcar("primeiro_envio")
        await self.enviar_json({"type": "tts_end"})
        self._frase_aberta = False

    async def _falhar(self, mensagem: str) -> None:
        # A conexão pode já ter caído; nesse caso não há a quem avisar.
        with contextlib.suppress(Exception):
            if self._frase_aberta:
                self._frase_aberta = False
                await self.enviar_json({"type": "tts_end"})
            await self.enviar_json({"type": "error", "message": mensagem})
            await self.mudar_estado(self.estado_livre())

    def _medidas(self, turno: Turno, duracao_s: float) -> dict:
        """Campos do registro do turno: tempos e contagens, nunca o texto."""
        ms = {k: round(v * 1000) for k, v in turno.tempos.items()}
        ms["tts_soma"] = round(turno.tts_s * 1000)
        ms["vad"] = round(turno.vad_s * 1000)
        if "primeiro_envio" in ms:
            # Meta do projeto: do fim da fala ao primeiro som, incluindo a espera do VAD.
            ms["fala_ate_primeiro_audio"] = ms["vad"] + ms["primeiro_envio"]
        return {
            "sessao": self.id,
            "tablet": self.device_id,
            "audio_s": round(duracao_s, 2),
            "fim_escuta": turno.fim_escuta,
            "frases": len(turno.frases),
            "memoria": turno.memoria,
            "emocoes": turno.emocoes,
            "ms": ms,
        }

    def _registrar_falha(self, turno: Turno, duracao_s: float, erro: BaseException) -> None:
        dados = self._medidas(turno, duracao_s)
        registro.registrar("falha", etapa=turno.etapa, erro=type(erro).__name__, **dados)
