"""Um turno de conversa: áudio do usuário → blocos de áudio da resposta, em fluxo."""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import numpy as np

from app.config import Config
from app.pipeline import llm, stt, tts
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
    tempos: dict[str, float] = field(default_factory=dict)
    tts_s: float = 0.0  # soma do tempo do Piper em todas as frases
    _inicio: float = field(default_factory=time.perf_counter, repr=False)

    def marcar(self, etapa: str) -> None:
        """Registra o instante da primeira ocorrência da etapa."""
        self.tempos.setdefault(etapa, time.perf_counter() - self._inicio)

    @property
    def resposta(self) -> str:
        return " ".join(self.frases)


async def _pedacos_medidos(texto: str, config: Config, turno: Turno) -> AsyncIterator[str]:
    async for pedaco in llm.gerar(texto, config):
        turno.marcar("llm_primeiro_token")
        yield pedaco
    turno.marcar("llm_fim")


async def conversar(audio: np.ndarray, config: Config, turno: Turno) -> AsyncIterator[BlocoAudio]:
    """Transcreve o áudio e devolve a resposta falada, um bloco por frase."""
    turno.texto_usuario = await stt.transcrever(audio, config)
    turno.marcar("stt")
    if not turno.texto_usuario:
        return

    # Enquanto o Piper sintetiza uma frase, o vLLM continua gerando: os tokens
    # ficam no buffer da conexão até o laço voltar a ler.
    async for frase in cortar_frases(_pedacos_medidos(turno.texto_usuario, config, turno)):
        turno.marcar("llm_primeira_frase")
        t = time.perf_counter()
        pcm, taxa = await tts.sintetizar(frase, config)
        turno.tts_s += time.perf_counter() - t
        turno.frases.append(frase)
        turno.marcar("primeiro_audio")
        yield BlocoAudio(frase, pcm, taxa)
    turno.marcar("fim")
