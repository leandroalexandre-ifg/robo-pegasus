"""Fala → texto com faster-whisper."""

import asyncio
import ctypes
import importlib.util
import os
from pathlib import Path

import numpy as np

from app.config import Config

_modelo = None
_trava = asyncio.Lock()


def _preparar_gpu(gpu: str) -> None:
    """Restringe o processo à GPU escolhida e carrega o cuBLAS 12 do venv."""
    if gpu == "0":
        raise ValueError("A GPU0 é reservada ao SciTech Ear; escolha outra GPU para o Whisper.")
    visiveis = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visiveis and visiveis != gpu:
        raise RuntimeError(f"CUDA_VISIBLE_DEVICES={visiveis} diverge de PEGASUS_WHISPER_GPU={gpu}.")
    # Precisa estar definido antes de o CTranslate2 inicializar o CUDA.
    os.environ["CUDA_VISIBLE_DEVICES"] = gpu

    # O ctranslate2 4.9 abre libcublas.so.12 pelo nome, mas o pacote
    # nvidia-cublas-cu12 não fica no caminho do carregador dinâmico.
    spec = importlib.util.find_spec("nvidia.cublas")
    pastas = [Path(p) / "lib" for p in (spec.submodule_search_locations or [])] if spec else []
    for pasta in pastas:
        if (pasta / "libcublas.so.12").exists():
            for nome in ("libcublasLt.so.12", "libcublas.so.12"):
                ctypes.CDLL(str(pasta / nome), mode=ctypes.RTLD_GLOBAL)
            return
    raise RuntimeError("libcublas.so.12 não encontrada; instale nvidia-cublas-cu12 no venv.")


def _carregar(config: Config):
    if config.whisper_dispositivo == "cuda":
        _preparar_gpu(config.whisper_gpu)
    from faster_whisper import WhisperModel

    return WhisperModel(
        config.whisper_modelo,
        device=config.whisper_dispositivo,
        # Com CUDA_VISIBLE_DEVICES restrito, a GPU escolhida é a de índice 0.
        device_index=0,
        compute_type=config.whisper_precisao,
        download_root=str(config.whisper_cache),
    )


async def carregar(config: Config):
    """Carrega o modelo uma única vez por processo."""
    global _modelo
    async with _trava:
        if _modelo is None:
            _modelo = await asyncio.to_thread(_carregar, config)
    return _modelo


def _transcrever(modelo, audio: np.ndarray, config: Config) -> str:
    segmentos, _ = modelo.transcribe(
        audio,
        language=config.whisper_idioma,
        beam_size=config.whisper_beam,
        vad_filter=False,  # o recorte da fala é feito antes, pelo Silero VAD
        condition_on_previous_text=False,
        initial_prompt=config.whisper_prompt,
    )
    # transcribe() devolve um gerador: a decodificação acontece aqui, na thread.
    return " ".join(s.text.strip() for s in segmentos).strip()


async def transcrever(audio: np.ndarray, config: Config) -> str:
    """Transcreve áudio float32 mono a 16 kHz."""
    modelo = await carregar(config)
    return await asyncio.to_thread(_transcrever, modelo, audio, config)
