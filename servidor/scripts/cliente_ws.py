"""Cliente de teste do WebSocket: envia um WAV como se fosse o tablet e salva a resposta.

Uso, a partir de servidor/, com o servidor (python -m app.main) e o vLLM ligados:

    set -a; . ~/.config/robo-pegasus/pegasus.env; set +a
    ../.venv/bin/python -m scripts.cliente_ws entrada.wav -o resposta.wav

O token vem de PEGASUS_TOKEN ou, na falta dele, do primeiro de PEGASUS_TOKENS.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.wav import escrever_wav, ler_wav

BLOCO_ENTRADA = 640  # 20 ms de PCM 16 kHz, 16 bits


def ms(segundos: float | None) -> str:
    return "      —" if segundos is None else f"{segundos * 1000:7.0f} ms"


def ler_token() -> str:
    token = os.environ.get("PEGASUS_TOKEN") or os.environ.get("PEGASUS_TOKENS", "").split(",")[0]
    if not token.strip():
        sys.exit("Defina PEGASUS_TOKEN ou PEGASUS_TOKENS (carregue o pegasus.env).")
    return token.strip()


async def esperar_estado(ws, estado: str) -> None:
    while True:
        mensagem = json.loads(await ws.recv())
        if mensagem.get("type") == "state" and mensagem["state"] == estado:
            return


async def principal(url: str, entrada: Path, saida: Path, tempo_real: bool) -> int:
    pcm_entrada = (ler_wav(entrada) * 32768).clip(-32768, 32767).astype("<i2").tobytes()

    async with connect(url, max_size=2**22) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "version": 1,
                    "token": ler_token(),
                    "device_id": "cliente-ws",
                    "audio": {"format": "pcm_s16le", "sample_rate": 16000, "channels": 1},
                }
            )
        )
        hello = json.loads(await ws.recv())
        taxa = hello["audio"]["sample_rate"]
        print(f"Conectado: sessão {hello['session_id']}, áudio de saída a {taxa} Hz")
        await esperar_estado(ws, "ocioso")

        await ws.send(json.dumps({"type": "listen_start"}))
        await esperar_estado(ws, "ouvindo")
        for i in range(0, len(pcm_entrada), BLOCO_ENTRADA):
            await ws.send(pcm_entrada[i : i + BLOCO_ENTRADA])
            if tempo_real:
                await asyncio.sleep(0.02)

        inicio = time.perf_counter()  # marco zero: fim da fala
        await ws.send(json.dumps({"type": "listen_stop"}))

        def agora() -> float:
            return time.perf_counter() - inicio

        tempos: dict[str, float] = {}
        frases: list[str] = []
        audio = bytearray()
        reconhecido = None
        while True:
            quadro = await asyncio.wait_for(ws.recv(), 60)
            if isinstance(quadro, bytes):
                tempos.setdefault("primeiro_audio", agora())
                audio += quadro
                continue
            mensagem = json.loads(quadro)
            tipo = mensagem.get("type")
            if tipo == "stt":
                tempos["stt"] = agora()
                reconhecido = mensagem["text"]
            elif tipo == "tts_start":
                tempos.setdefault("primeira_frase", agora())
                frases.append(mensagem["text"])
            elif tipo == "error":
                print(f"Erro do servidor: {mensagem['message']}")
            elif tipo == "state" and mensagem["state"] == "ocioso":
                tempos["fim"] = agora()
                break

    print(f"Reconhecido: {reconhecido or '(nada)'}")
    if not audio:
        print("Nenhum áudio de resposta.")
        return 1
    print(f"Resposta:    {' '.join(frases)}")
    escrever_wav(saida, bytes(audio), taxa)

    print()
    print(
        f"Áudio de entrada: {len(pcm_entrada) / 32000:.2f} s"
        f"{' (enviado em tempo real)' if tempo_real else ''}"
        f"   áudio de saída: {len(audio) / 2 / taxa:.2f} s   frases: {len(frases)}"
    )
    print("Tempos contados do envio do listen_stop, vistos pelo cliente:")
    print(f"stt recebido:            {ms(tempos.get('stt'))}")
    print(f"primeiro tts_start:      {ms(tempos.get('primeira_frase'))}")
    print(f"Primeiro áudio:          {ms(tempos.get('primeiro_audio'))}   ← meta: 1500 ms")
    print(f"Fim (estado ocioso):     {ms(tempos.get('fim'))}")
    print(f"Resposta salva em {saida}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Envia um WAV ao servidor como se fosse o tablet.")
    parser.add_argument("entrada", type=Path, help="WAV 16 kHz, mono, 16 bits")
    parser.add_argument("-o", "--saida", type=Path, default=Path("resposta_ws.wav"))
    parser.add_argument("--url", default=None, help="padrão: ws://127.0.0.1:PEGASUS_PORTA_API/ws")
    parser.add_argument(
        "--tempo-real", action="store_true", help="envia o áudio no ritmo da fala (20 ms por bloco)"
    )
    args = parser.parse_args()
    url = args.url or f"ws://127.0.0.1:{os.environ.get('PEGASUS_PORTA_API', '8100')}/ws"
    try:
        codigo = asyncio.run(principal(url, args.entrada, args.saida, args.tempo_real))
    except ConnectionClosed as e:
        sys.exit(f"Conexão fechada pelo servidor: {e.code} {e.reason}")
    except OSError as e:
        sys.exit(f"Não foi possível conectar em {url}: {e}")
    sys.exit(codigo)


if __name__ == "__main__":
    main()
