"""Leitura e escrita de WAV PCM 16 bits mono."""

import wave
from pathlib import Path

import numpy as np

TAXA_ENTRADA = 16_000


def ler_wav(caminho: Path) -> np.ndarray:
    """Lê WAV 16 kHz, mono, 16 bits e devolve float32 em [-1, 1]."""
    with wave.open(str(caminho), "rb") as f:
        if f.getframerate() != TAXA_ENTRADA or f.getnchannels() != 1 or f.getsampwidth() != 2:
            raise ValueError(
                f"{caminho}: esperado 16 kHz, mono, 16 bits; recebido "
                f"{f.getframerate()} Hz, {f.getnchannels()} canal(is), "
                f"{8 * f.getsampwidth()} bits."
            )
        dados = f.readframes(f.getnframes())
    return np.frombuffer(dados, dtype=np.int16).astype(np.float32) / 32768.0


def escrever_wav(caminho: Path, pcm: bytes, taxa: int) -> None:
    with wave.open(str(caminho), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(taxa)
        f.writeframes(pcm)
