"""Teste do pipeline: WAV (16 kHz, mono) → texto → resposta falada em fluxo → WAV.

Uso, a partir de servidor/ e com o vLLM ligado (pegasus-ligar):

    set -a; . ~/.config/robo-pegasus/pegasus.env; set +a
    ../.venv/bin/python -m scripts.teste_pipeline entrada.wav -o resposta.wav
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import openai

from app.config import Config, carregar_config
from app.pipeline import stt, tts
from app.pipeline.emocao import Emocao
from app.pipeline.turno import Turno, conversar
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
    return "      —" if segundos is None else f"{segundos * 1000:7.0f} ms"


async def principal(
    entrada: Path, saida: Path, aquecer: bool, json_saida: bool, config: Config
) -> int:
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

    turno = Turno()  # marco zero: o áudio do usuário está pronto
    blocos = []
    try:
        async for bloco in conversar(audio, config, turno):
            if not isinstance(bloco, Emocao):
                blocos.append(bloco)
    except openai.APIConnectionError:
        print(f"O LLM não respondeu em {config.llm_url}. Ele está ligado (pegasus-ligar)?")
        return 2

    print(f"Reconhecido: {turno.texto_usuario or '(nada)'}")
    if not blocos:
        print("Nenhuma fala reconhecida; nada a responder.")
        return 1
    print(f"Resposta:    {turno.resposta}")
    print(f"Emoção:      {', '.join(turno.emocoes) or '(nenhuma)'}")

    taxa = blocos[0].taxa
    pcm = b"".join(b.pcm for b in blocos)
    escrever_wav(saida, pcm, taxa)
    duracao_saida = len(pcm) / 2 / taxa
    tempos = turno.tempos

    print()
    print(f"Áudio de entrada: {duracao_entrada:.2f} s   áudio de saída: {duracao_saida:.2f} s")
    print(f"Frases: {len(blocos)}   (tempos contados do fim da fala)")
    print(f"STT  (Whisper):          {ms(tempos['stt'])}")
    print(f"LLM  primeiro token:     {ms(tempos.get('llm_primeiro_token'))}")
    print(f"LLM  primeira frase:     {ms(tempos.get('llm_primeira_frase'))}")
    print(f"Emoção:                  {ms(tempos.get('emocao'))}")
    print(f"Primeiro áudio:          {ms(tempos.get('primeiro_audio'))}   ← meta: 1500 ms")
    print(f"LLM  fim do fluxo:       {ms(tempos.get('llm_fim'))}")
    print(f"Fim (todo o áudio):      {ms(tempos.get('fim'))}")
    print(f"TTS  soma das frases:    {ms(turno.tts_s)}")
    print(f"Carga dos modelos (fora da medição): {carga:.1f} s")
    if vram_antes is not None and vram_depois is not None:
        print(
            f"VRAM GPU{config.whisper_gpu}: {vram_antes} → {vram_depois} MiB "
            f"(Whisper: +{vram_depois - vram_antes} MiB)"
        )
    print(f"Resposta salva em {saida}")
    if json_saida:
        medidas = {k: round(v * 1000) for k, v in tempos.items()}
        medidas["tts_soma"] = round(turno.tts_s * 1000)
        resumo = {"frases": len(blocos), "emocoes": turno.emocoes, "ms": medidas}
        print("JSON " + json.dumps(resumo, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa o pipeline fala → resposta falada.")
    parser.add_argument("entrada", type=Path, help="WAV 16 kHz, mono, 16 bits")
    parser.add_argument("-o", "--saida", type=Path, default=Path("resposta.wav"))
    parser.add_argument(
        "--sem-aquecimento", action="store_true", help="mede também a primeira execução"
    )
    parser.add_argument("--json", action="store_true", help="imprime os tempos também em JSON")
    args = parser.parse_args()
    config = carregar_config()
    codigo = asyncio.run(
        principal(args.entrada, args.saida, not args.sem_aquecimento, args.json, config)
    )
    sys.exit(codigo)


if __name__ == "__main__":
    main()
