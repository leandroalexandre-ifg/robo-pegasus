"""Texto → fala com Piper, na CPU."""

import asyncio

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


def _sintetizar(voz: PiperVoice, texto: str) -> bytes:
    return b"".join(bloco.audio_int16_bytes for bloco in voz.synthesize(texto))


async def sintetizar(texto: str, config: Config) -> tuple[bytes, int]:
    """Devolve PCM 16 bits mono e a taxa de amostragem da voz (22,05 kHz na faber)."""
    voz = await carregar(config)
    pcm = await asyncio.to_thread(_sintetizar, voz, texto)
    return pcm, voz.config.sample_rate
