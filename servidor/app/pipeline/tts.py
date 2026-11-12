"""Texto → fala com Piper, na CPU."""

import asyncio
import threading

from piper import PiperVoice

from app.config import Config

_voz: PiperVoice | None = None
_trava = asyncio.Lock()


async def carregar(config: Config) -> PiperVoice:
    """Carrega a voz uma única vez por processo."""
    global _voz
    async with _trava:
        if _voz is None:
            _voz = await asyncio.to_thread(PiperVoice.load, config.piper_voz, use_cuda=False)
    return _voz


def _sintetizar(voz: PiperVoice, texto: str, parar: threading.Event) -> bytes:
    blocos = []
    for bloco in voz.synthesize(texto):  # o Piper gera um bloco por frase do texto
        if parar.is_set():
            break
        blocos.append(bloco.audio_int16_bytes)
    return b"".join(blocos)


async def sintetizar(texto: str, config: Config) -> tuple[bytes, int]:
    """Devolve PCM 16 bits mono e a taxa de amostragem da voz (22,05 kHz na faber)."""
    voz = await carregar(config)
    parar = threading.Event()
    try:
        pcm = await asyncio.to_thread(_sintetizar, voz, texto, parar)
    except asyncio.CancelledError:
        # A thread não pode ser interrompida no meio de um bloco: o turno segue sem
        # esperar por ela, e o aviso a faz parar antes do próximo bloco.
        parar.set()
        raise
    return pcm, voz.config.sample_rate
