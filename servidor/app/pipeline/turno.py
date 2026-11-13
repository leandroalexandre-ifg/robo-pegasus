"""Um turno de conversa: áudio do usuário → blocos de áudio da resposta, em fluxo."""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import numpy as np

from app.config import Config
from app.pipeline import llm, stt, tts
from app.pipeline.emocao import Emocao, limpar_para_voz
from app.pipeline.frases import cortar_frases
from app.pipeline.llm import Historico


@dataclass
class BlocoAudio:
    frase: str
    pcm: bytes  # PCM 16 bits mono
    taxa: int


@dataclass
class Turno:
    """Texto e tempos de um turno. Os tempos contam a partir da criação do turno,
    que deve coincidir com o fim da fala do usuário."""

    texto_usuario: str = ""
    frases: list[str] = field(default_factory=list)
    emocoes: list[str] = field(default_factory=list)
    tempos: dict[str, float] = field(default_factory=dict)
    tts_s: float = 0.0  # soma do tempo do Piper em todas as frases
    fim_escuta: str = ""  # o que encerrou a escuta: vad, listen_stop ou limite
    vad_s: float = 0.0  # silêncio esperado depois da fala até decidir que ela acabou
    memoria: int = 0  # turnos anteriores enviados ao LLM
    reserva: bool = False  # o LLM não respondeu e o robô disse a fala de reserva
    despedida: bool = False  # a fala encerrou a conversa e o robô se despediu
    _inicio: float = field(default_factory=time.perf_counter, repr=False)

    def marcar(self, etapa: str) -> None:
        """Registra o instante da primeira ocorrência da etapa."""
        self.tempos.setdefault(etapa, time.perf_counter() - self._inicio)

    @property
    def etapa(self) -> str:
        """A última etapa concluída (onde o turno estava ao falhar)."""
        return max(self.tempos, key=self.tempos.__getitem__, default="inicio")

    @property
    def resposta(self) -> str:
        return " ".join(self.frases)


NEUTRO = Emocao("neutro")
REPETICOES_SEM_FALA = 1
FALA_RESERVA = "Desculpe, me perdi. Pode perguntar de novo?"
log = logging.getLogger("pegasus.turno")


async def _pedacos_medidos(
    texto: str, config: Config, turno: Turno, historico: Historico
) -> AsyncIterator[str | Emocao]:
    async for pedaco in llm.gerar(texto, config, historico):
        turno.marcar("emocao_llm" if isinstance(pedaco, Emocao) else "llm_primeiro_token")
        yield pedaco
    turno.marcar("llm_fim")


async def _emocao_medida(
    texto: str, config: Config, turno: Turno, historico: Historico
) -> Emocao | None:
    try:
        emocao = await llm.escolher_emocao(texto, config, historico)
    except Exception as e:  # sem emoção o turno segue, com neutro
        log.warning("falha ao escolher a emoção: %s", e)
        return None
    turno.marcar("emocao_llm")
    return emocao


async def transcrever(audio: np.ndarray, config: Config, turno: Turno) -> str:
    turno.texto_usuario = await asyncio.wait_for(
        stt.transcrever(audio, config), config.stt_limite_s
    )
    turno.marcar("stt")
    return turno.texto_usuario


def _registrar_emocao(emocao: Emocao, turno: Turno) -> Emocao:
    turno.emocoes.append(emocao.nome)
    turno.marcar("emocao")
    return emocao


class _Fim:
    """Marca, na fila de `falar`, que a produção das frases terminou."""


@dataclass
class _Falha:
    erro: BaseException


async def _produzir(
    texto: str, config: Config, turno: Turno, historico: Historico, fila: asyncio.Queue
) -> None:
    """Gera as frases (e, no modo "antes", a emoção do fluxo) e põe cada bloco de
    áudio na fila assim que o Piper termina. Roda à frente de quem envia."""

    async def sintetizar(frase: str) -> BlocoAudio:
        t = time.perf_counter()
        pcm, taxa = await asyncio.wait_for(tts.sintetizar(frase, config), config.tts_limite_s)
        turno.tts_s += time.perf_counter() - t
        return BlocoAudio(frase, pcm, taxa)

    emocao_vista = config.emocao_modo == "paralelo"  # no paralelo, a emoção vem à parte
    falou = False

    async def por(bloco: BlocoAudio) -> None:
        nonlocal emocao_vista, falou
        if not emocao_vista:
            log.info("o LLM não chamou definir_emocao antes da fala; usando neutro")
            emocao_vista = True
            await fila.put(NEUTRO)
        falou = True
        turno.marcar("primeiro_audio")  # o primeiro áudio pronto; o envio é medido na sessão
        await fila.put(bloco)

    try:
        for tentativa in range(1 + REPETICOES_SEM_FALA):
            contexto = historico
            if tentativa:
                # O Qwen3.8 às vezes encerra o turno no primeiro token: a resposta vem
                # vazia, com finish_reason "stop". Depende do conteúdo da memória (até
                # metade das vezes com certas conversas) e nunca foi visto sem ela, então
                # a nova tentativa vai sem memória: perde o contexto, mas responde.
                log.warning("o LLM terminou sem dizer nada; repetindo o pedido sem a memória")
                turno.marcar("llm_repeticao")
                contexto = ()
            pedacos = _pedacos_medidos(texto, config, turno, contexto)
            async for item in cortar_frases(pedacos, primeira_na_virgula=True):
                if isinstance(item, Emocao):
                    emocao_vista = True
                    await fila.put(item)
                    continue
                frase = limpar_para_voz(item)  # a voz nunca lê marcações
                if not frase:
                    continue
                turno.marcar("llm_primeira_frase")
                await por(await sintetizar(frase))
            if falou:
                break
        else:
            log.warning("o LLM não disse nada depois de repetir; usando a fala de reserva")
            turno.reserva = True
            await por(await sintetizar(FALA_RESERVA))
    except Exception as e:
        await fila.put(_Falha(e))
    else:
        await fila.put(_Fim())


async def falar(
    texto: str, config: Config, turno: Turno, historico: Historico = ()
) -> AsyncIterator[BlocoAudio | Emocao]:
    """Gera a resposta ao texto do usuário: um bloco de áudio por frase e, no meio
    deles, uma emoção para o rosto, assim que ela chega. O primeiro áudio não espera
    a emoção: no modo "paralelo" ela costuma chegar durante a primeira frase.

    Se a emoção não chegar em `emocao_espera_s` depois do primeiro áudio, vai neutro.
    Se o LLM terminar sem dizer nada, o pedido é repetido uma vez; se ainda vier
    vazio, o robô diz FALA_RESERVA em vez de ficar mudo."""
    fila: asyncio.Queue = asyncio.Queue()
    pedido = None
    if config.emocao_modo == "paralelo":
        # Requisição própria, em paralelo com a fala; o resultado entra na fila.
        pedido = asyncio.create_task(_emocao_medida(texto, config, turno, historico))
        pedido.add_done_callback(lambda t: t.cancelled() or fila.put_nowait(t.result() or NEUTRO))
    produtor = asyncio.create_task(_produzir(texto, config, turno, historico, fila))
    prazo = None  # até quando o rosto espera a emoção, contado do primeiro áudio
    terminou = False
    try:
        while not (terminou and (turno.emocoes or prazo is None)):
            espera = None
            if prazo is not None and not turno.emocoes:
                espera = max(0.0, prazo - time.perf_counter())
            try:
                item = await asyncio.wait_for(fila.get(), espera)
            except TimeoutError:
                log.warning(
                    "emoção não chegou em %.0f ms; usando neutro", config.emocao_espera_s * 1000
                )
                item = NEUTRO
            if isinstance(item, _Falha):
                raise item.erro
            if isinstance(item, _Fim):
                terminou = True
            elif isinstance(item, Emocao):
                if turno.emocoes:
                    log.info("emoção %s chegou depois do prazo; descartada", item.nome)
                else:
                    yield _registrar_emocao(item, turno)
            else:
                turno.frases.append(item.frase)  # só o que saiu daqui entra na memória
                if prazo is None:
                    prazo = time.perf_counter() + config.emocao_espera_s
                yield item
    finally:
        # Turno interrompido ou emoção atrasada: não espera mais nada.
        for tarefa in (produtor, pedido):
            if tarefa is not None:
                tarefa.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await produtor
    turno.marcar("fim")


async def conversar(
    audio: np.ndarray, config: Config, turno: Turno
) -> AsyncIterator[BlocoAudio | Emocao]:
    """Transcreve o áudio e devolve a emoção e a resposta falada, um bloco por frase."""
    if await transcrever(audio, config, turno):
        async for bloco in falar(turno.texto_usuario, config, turno):
            yield bloco
