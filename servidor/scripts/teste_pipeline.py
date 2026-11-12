"""Teste do pipeline: WAV (16 kHz, mono) → texto → resposta → WAV.

Uso, a partir de servidor/ e com o vLLM ligado (pegasus-ligar):

    set -a; . ~/.config/robo-pegasus/pegasus.env; set +a
    ../.venv/bin/python -m scripts.teste_pipeline entrada.wav -o resposta.wav
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

import openai

from app.config import Config, carregar_config
from app.pipeline import llm, stt, tts
from app.wav import TAXA_ENTRADA, escrever_wav, ler_wav


def vram_mib(gpu: int) -> int | None:
    """Memória usada na GPU (índice físico), via NVML."""
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            uso = pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(gpu))
            return uso.used // 2**20
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return None


def ms(segundos: float | None) -> str:
    return "—" if segundos is None else f"{segundos * 1000:7.0f} ms"


async def principal(entrada: Path, saida: Path, aquecer: bool, config: Config) -> int:
    audio = ler_wav(entrada)
    duracao_entrada = len(audio) / TAXA_ENTRADA
    usa_gpu = config.whisper_dispositivo == "cuda"

    vram_antes = vram_mib(int(config.whisper_gpu)) if usa_gpu else None
    t = time.perf_counter()
    await stt.carregar(config)
    await tts.carregar(config)
    carga = time.perf_counter() - t

    if aquecer:
        # A primeira execução compila os kernels do CTranslate2 para a 5090; fica fora da medição.
        await stt.transcrever(audio, config)
        await tts.sintetizar("Olá.", config)
    vram_depois = vram_mib(int(config.whisper_gpu)) if usa_gpu else None

    inicio = time.perf_counter()
    texto = await stt.transcrever(audio, config)
    t_stt = time.perf_counter() - inicio
    print(f"Reconhecido: {texto or '(nada)'}")
    if not texto:
        print("Nenhuma fala reconhecida; nada a responder.")
        return 1

    t = time.perf_counter()
    try:
        resposta = await llm.responder(texto, config)
    except openai.APIConnectionError:
        print(f"O LLM não respondeu em {config.llm_url}. Ele está ligado (pegasus-ligar)?")
        return 2
    t_llm = time.perf_counter() - t
    print(f"Resposta:    {resposta.texto}")

    t = time.perf_counter()
    pcm, taxa = await tts.sintetizar(resposta.texto, config)
    t_tts = time.perf_counter() - t
    total = time.perf_counter() - inicio

    escrever_wav(saida, pcm, taxa)
    duracao_saida = len(pcm) / 2 / taxa

    print()
    print(f"Áudio de entrada: {duracao_entrada:.2f} s   áudio de saída: {duracao_saida:.2f} s")
    print(f"STT  (Whisper):          {ms(t_stt)}   tempo real ×{t_stt / duracao_entrada:.3f}")
    print(f"LLM  primeiro token:     {ms(resposta.primeiro_token_s)}")
    print(f"LLM  resposta completa:  {ms(t_llm)}")
    print(f"TTS  (Piper):            {ms(t_tts)}   tempo real ×{t_tts / duracao_saida:.3f}")
    print(f"Total:                   {ms(total)}")
    print(f"Carga dos modelos (fora do total): {carga:.1f} s")
    if vram_antes is not None and vram_depois is not None:
        print(
            f"VRAM GPU{config.whisper_gpu}: {vram_antes} → {vram_depois} MiB "
            f"(Whisper: +{vram_depois - vram_antes} MiB)"
        )
    print(f"Resposta salva em {saida}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa o pipeline fala → resposta falada.")
    parser.add_argument("entrada", type=Path, help="WAV 16 kHz, mono, 16 bits")
    parser.add_argument("-o", "--saida", type=Path, default=Path("resposta.wav"))
    parser.add_argument(
        "--sem-aquecimento", action="store_true", help="mede também a primeira execução"
    )
    args = parser.parse_args()
    config = carregar_config()
    sys.exit(asyncio.run(principal(args.entrada, args.saida, not args.sem_aquecimento, config)))


if __name__ == "__main__":
    main()
