"""Estado de um tablet conectado e execução dos seus turnos de conversa."""

import asyncio
import collections
import contextlib
import json
import logging
import secrets
import time

import numpy as np
import openai
from fastapi import WebSocket

from app.config import Config
from app.pipeline import ativacao, stt, tts
from app.pipeline.emocao import Emocao
from app.pipeline.turno import Turno, falar, transcrever
from app.pipeline.vad import DetectorFala
from app.wav import TAXA_ENTRADA

log = logging.getLogger("pegasus.sessao")

MAX_AUDIO_S = 30
_MAX_BYTES = MAX_AUDIO_S * TAXA_ENTRADA * 2
BLOCO_SAIDA_S = 0.1
# Quanto o abort espera a limpeza do turno cancelado (fechar o fluxo do LLM etc.)
# antes de seguir sem ela.
ESPERA_CANCELAMENTO_S = 0.5
# Margens mantidas em volta da fala detectada, para o Whisper não perder sílabas.
PRE_FALA_S = 0.3
POS_FALA_S = 0.2
# Escuta contínua (ativação por palavra): áudio guardado enquanto ninguém fala,
# para ter a margem antes da fala quando ela começar.
VIGIA_GUARDA_S = 1.0
_VIGIA_LIMITE_BYTES = round(2 * VIGIA_GUARDA_S * TAXA_ENTRADA) * 2
SAUDACAO = "Oi?"  # resposta a uma fala que é só a palavra de ativação


def _amostras(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


class Sessao:
    def __init__(self, ws: WebSocket, config: Config, device_id: str):
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
        self._frase_aberta = False
        # Memória curta: (fala do usuário, resposta) dos últimos turnos desta conexão.
        self.historico: collections.deque[tuple[str, str]] = collections.deque(
            maxlen=config.memoria_turnos
        )
        # O receptor de mensagens e a tarefa do turno enviam pela mesma conexão.
        self._envio = asyncio.Lock()

    async def enviar_json(self, mensagem: dict) -> None:
        async with self._envio:
            await self.ws.send_text(json.dumps(mensagem, ensure_ascii=False))

    async def enviar_audio(self, pcm: bytes) -> None:
        async with self._envio:
            await self.ws.send_bytes(pcm)

    async def mudar_estado(self, estado: str) -> None:
        self.estado = estado
        await self.enviar_json({"type": "state", "state": estado})

    def _limpar_audio(self) -> None:
        self._audio.clear()
        self._descartadas = 0
        self._vad = None

    async def _abrir_escuta(self) -> None:
        self._limpar_audio()
        self._vad = DetectorFala(self.config)
        await self.mudar_estado("ouvindo")

    async def ao_listen_start(self) -> None:
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
        elif (
            not self._vad.falou
            and len(self._audio) >= self.config.vad_sem_fala_s * 2 * TAXA_ENTRADA
        ):
            log.info("sessão %s: escuta sem fala; voltando a ocioso", self.id)
            self._limpar_audio()
            await self.mudar_estado("ocioso")

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
        pcm, turno = self._fechar_fala(motivo)
        if not pcm:
            await self.mudar_estado("ocioso")
            return
        await self.mudar_estado("pensando")
        self._turno = asyncio.create_task(self._responder(pcm, turno))

    async def ao_abort(self) -> None:
        self._epoca += 1
        await self.cancelar_turno()
        self._limpar_audio()
        await self.mudar_estado("ocioso")

    async def _vigiar(self, dados: bytes) -> None:
        """Escuta contínua em `ocioso`: separa as falas com o VAD e manda cada uma
        verificar a palavra de ativação. Nada do que não for ativação é guardado."""
        if self._vad is None:
            self._limpar_audio()
            self._vad = DetectorFala(self.config)
        self._audio += dados[: _MAX_BYTES - len(self._audio)]
        evento = self._vad.processar(dados)
        if evento == "fim" or len(self._audio) >= _MAX_BYTES:
            pcm, turno = self._fechar_fala("ativacao")
            # Uma verificação de cada vez, na ordem das falas: a nova espera a anterior,
            # e cancelar a nova (abort, listen_start) cancela a anterior junto.
            anterior = self._turno if self._turno is not None and not self._turno.done() else None
            self._turno = asyncio.create_task(self._verificar(pcm, turno, self._epoca, anterior))
        elif not self._vad.falou and len(self._audio) > _VIGIA_LIMITE_BYTES:
            corte = len(self._audio) - round(VIGIA_GUARDA_S * TAXA_ENTRADA) * 2
            del self._audio[:corte]
            self._descartadas += corte // 2

    async def _verificar(
        self, pcm: bytes, turno: Turno, epoca: int, anterior: asyncio.Task | None
    ) -> None:
        """Transcreve uma fala da escuta contínua e só a atende se ela começar com a
        palavra de ativação. As outras são descartadas sem registro do áudio nem do texto."""
        if anterior is not None:
            with contextlib.suppress(Exception):
                await anterior
        if epoca != self._epoca:
            return
        try:
            texto = await stt.transcrever(_amostras(pcm), self.config)
        except Exception as e:
            log.error(
                "sessão %s: falha ao transcrever na escuta contínua (%s)", self.id, type(e).__name__
            )
            return
        pedido = ativacao.pergunta(texto)
        del texto
        if pedido is None or epoca != self._epoca or self.estado != "ocioso":
            return
        turno.marcar("stt")
        self._epoca += 1  # falas seguintes, ainda na fila, são descartadas
        self._limpar_audio()
        if pedido:
            log.info("sessão %s: ativada pela palavra, com pergunta", self.id)
            turno.texto_usuario = pedido
            await self.mudar_estado("pensando")
            await self._responder(pcm, turno, pedido)
        else:
            await self._saudar(turno)

    async def _saudar(self, turno: Turno) -> None:
        """Só a palavra de ativação: responde "Oi?" e abre a escuta da pergunta."""
        try:
            pcm, taxa = await tts.sintetizar(SAUDACAO, self.config)
            await self.mudar_estado("falando")
            await self._enviar_frase(SAUDACAO, pcm, taxa)
            turno.marcar("primeiro_envio")
            await self._abrir_escuta()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("sessão %s: falha na saudação", self.id)
            await self._falhar("Ocorreu um erro no servidor.")
            return
        ms = {k: round(v * 1000) for k, v in turno.tempos.items()}
        log.info(
            "sessão %s: ativada pela palavra; %s em %d ms do fim da fala (vad %d ms, stt %d ms)",
            self.id,
            SAUDACAO,
            round(turno.vad_s * 1000) + ms["primeiro_envio"],
            round(turno.vad_s * 1000),
            ms["stt"],
        )

    async def cancelar_turno(self) -> None:
        """Interrompe na hora o turno em andamento: STT, LLM (o fluxo é fechado e o
        vLLM aborta a geração), pedido de emoção, Piper e envio de áudio."""
        tarefa, self._turno = self._turno, None
        if tarefa is not None and not tarefa.done():
            inicio = time.perf_counter()
            tarefa.cancel()
            _, pendentes = await asyncio.wait({tarefa}, timeout=ESPERA_CANCELAMENTO_S)
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
        if turno.texto_usuario and turno.frases:
            self.historico.append((turno.texto_usuario, turno.resposta))

    async def _responder(self, pcm: bytes, turno: Turno, texto: str | None = None) -> None:
        """Responde à fala. Com `texto`, ela já foi transcrita (palavra de ativação)."""
        memoria = tuple(self.historico)
        turno.memoria = len(memoria)
        try:
            if texto is None:
                texto = await transcrever(_amostras(pcm), self.config, turno)
            await self.enviar_json({"type": "stt", "text": texto})
            if texto:
                await self._falar(texto, turno, memoria)
            await self.mudar_estado("ocioso")
        except asyncio.CancelledError:
            self._lembrar(turno)
            raise
        except openai.APIError as e:
            log.error("sessão %s: falha no LLM: %s", self.id, e)
            await self._falhar("O servidor de linguagem não está disponível.")
        except Exception:
            log.exception("sessão %s: falha no turno", self.id)
            await self._falhar("Ocorreu um erro no servidor.")
        else:
            self._lembrar(turno)
            self._registrar(turno, len(pcm) / 2 / TAXA_ENTRADA)

    async def _falar(self, texto: str, turno: Turno, memoria: tuple[tuple[str, str], ...]) -> None:
        async for bloco in falar(texto, self.config, turno, memoria):
            if isinstance(bloco, Emocao):
                await self.enviar_json({"type": "emotion", "emotion": bloco.nome})
                continue
            if self.estado != "falando":
                await self.mudar_estado("falando")
            await self._enviar_frase(bloco.frase, bloco.pcm, bloco.taxa, turno)

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
            await self.mudar_estado("ocioso")

    def _registrar(self, turno: Turno, duracao_s: float) -> None:
        medidas = {k: round(v * 1000) for k, v in turno.tempos.items()}
        medidas["tts_soma"] = round(turno.tts_s * 1000)
        medidas["vad"] = round(turno.vad_s * 1000)
        if "primeiro_envio" in medidas:
            # Meta do projeto: do fim da fala ao primeiro som, incluindo a espera do VAD.
            medidas["fala_ate_primeiro_audio"] = medidas["vad"] + medidas["primeiro_envio"]
        log.info(
            "turno %s",
            json.dumps(
                {
                    "sessao": self.id,
                    "tablet": self.device_id,
                    "audio_s": round(duracao_s, 2),
                    "fim_escuta": turno.fim_escuta,
                    "frases": len(turno.frases),
                    "memoria": turno.memoria,
                    "emocoes": turno.emocoes,
                    "ms": medidas,
                },
                ensure_ascii=False,
            ),
        )
        log.debug("sessão %s: %r → %r", self.id, turno.texto_usuario, turno.resposta)
