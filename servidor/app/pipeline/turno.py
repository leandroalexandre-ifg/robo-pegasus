"""Um turno de conversa: áudio do usuário → blocos de áudio da resposta, em fluxo."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import numpy as np

from app.config import Config
from app.pipeline import llm, stt, tts
from app.pipeline.emocao import Emocao, limpar_para_voz
from app.pipeline.frases import cortar_frases


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
    _inicio: float = field(default_factory=time.perf_counter, repr=False)

    def marcar(self, etapa: str) -> None:
        """Registra o instante da primeira ocorrência da etapa."""
        self.tempos.setdefault(etapa, time.perf_counter() - self._inicio)

    @property
    def resposta(self) -> str:
        return " ".join(self.frases)


NEUTRO = Emocao("neutro")
log = logging.getLogger("pegasus.turno")


async def _pedacos_medidos(texto: str, config: Config, turno: Turno) -> AsyncIterator[str | Emocao]:
    async for pedaco in llm.gerar(texto, config):
        turno.marcar("emocao_llm" if isinstance(pedaco, Emocao) else "llm_primeiro_token")
        yield pedaco
    turno.marcar("llm_fim")


async def _emocao_medida(texto: str, config: Config, turno: Turno) -> Emocao | None:
    try:
        emocao = await llm.escolher_emocao(texto, config)
    except Exception as e:  # sem emoção o turno segue, com neutro
        log.warning("falha ao escolher a emoção: %s", e)
        return None
    turno.marcar("emocao_llm")
    return emocao


async def _aguardar_emocao(pedido: asyncio.Task, config: Config) -> Emocao:
    """A emoção escolhida pelo LLM, ou neutro se ele não a escolher a tempo."""
    try:
        emocao = await asyncio.wait_for(asyncio.shield(pedido), config.emocao_espera_s)
    except TimeoutError:
        log.warning("emoção não chegou em %.0f ms; usando neutro", config.emocao_espera_s * 1000)
        return NEUTRO
    return emocao or NEUTRO


async def transcrever(audio: np.ndarray, config: Config, turno: Turno) -> str:
    turno.texto_usuario = await stt.transcrever(audio, config)
    turno.marcar("stt")
    return turno.texto_usuario


def _registrar_emocao(emocao: Emocao, turno: Turno) -> Emocao:
    turno.emocoes.append(emocao.nome)
    turno.marcar("emocao")
    return emocao


async def falar(texto: str, config: Config, turno: Turno) -> AsyncIterator[BlocoAudio | Emocao]:
    """Gera a resposta ao texto do usuário: a emoção do rosto e, depois dela, um
    bloco de áudio por frase. A emoção vem sempre antes do primeiro áudio."""
    # Modo "paralelo": a emoção é pedida em requisição própria e costuma chegar
    # enquanto o Piper sintetiza a primeira frase. Modo "antes": ela vem no próprio
    # fluxo da fala, se o LLM chamar a ferramenta antes de escrever.
    pedido = None
    if config.emocao_modo == "paralelo":
        pedido = asyncio.create_task(_emocao_medida(texto, config, turno))
    try:
        # Enquanto o Piper sintetiza uma frase, o vLLM continua gerando: os tokens
        # ficam no buffer da conexão até o laço voltar a ler.
        async for item in cortar_frases(_pedacos_medidos(texto, config, turno)):
            if isinstance(item, Emocao):
                if turno.emocoes:
                    log.info("emoção %s chegou depois do primeiro áudio; descartada", item.nome)
                else:
                    yield _registrar_emocao(item, turno)
                continue
            frase = limpar_para_voz(item)  # a voz nunca lê marcações
            if not frase:
                continue
            turno.marcar("llm_primeira_frase")
            t = time.perf_counter()
            pcm, taxa = await tts.sintetizar(frase, config)
            turno.tts_s += time.perf_counter() - t
            if not turno.emocoes:
                if pedido is not None:
                    emocao = await _aguardar_emocao(pedido, config)
                else:
                    log.info("o LLM não chamou definir_emocao antes da fala; usando neutro")
                    emocao = NEUTRO
                yield _registrar_emocao(emocao, turno)
            turno.frases.append(frase)
            turno.marcar("primeiro_audio")
            yield BlocoAudio(frase, pcm, taxa)
    finally:
        if pedido is not None:
            pedido.cancel()  # turno interrompido ou emoção atrasada: não espera mais
    turno.marcar("fim")


async def conversar(
    audio: np.ndarray, config: Config, turno: Turno
) -> AsyncIterator[BlocoAudio | Emocao]:
    """Transcreve o áudio e devolve a emoção e a resposta falada, um bloco por frase."""
    if await transcrever(audio, config, turno):
        async for bloco in falar(turno.texto_usuario, config, turno):
            yield bloco
