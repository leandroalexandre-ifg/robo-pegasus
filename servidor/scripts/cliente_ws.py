"""Cliente de teste do WebSocket: envia WAVs como se fosse o tablet e salva as respostas.

Uso, a partir de servidor/, com o servidor (python -m app.main) e o vLLM ligados:

    set -a; . ~/.config/robo-pegasus/pegasus.env; set +a
    ../.venv/bin/python -m scripts.cliente_ws entrada.wav -o resposta.wav
    ../.venv/bin/python -m scripts.cliente_ws --vad um.wav dois.wav  # conversa sem listen_stop
    ../.venv/bin/python -m scripts.cliente_ws --abortar entrada.wav   # abort no primeiro áudio
    ../.venv/bin/python -m scripts.cliente_ws --continuo pegasus.wav pergunta.wav

--continuo exige o servidor com PEGASUS_ATIVACAO=palavra: não envia listen_start,
só o áudio, como um microfone sempre aberto. Cada WAV é uma fala; uma fala sem
"Pegasus" não recebe resposta nenhuma ("descartada").

Vários WAVs são turnos da mesma conexão (a memória da sessão vale entre eles).
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
SILENCIO_APOS_FALA_S = 3.0  # modo --vad: silêncio enviado depois da fala, até o servidor decidir


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


async def _enviar_fala(ws, pcm: bytes, tempo_real: bool, vad: bool, parar: asyncio.Event) -> float:
    """Envia a fala em blocos de 20 ms; devolve o instante em que ela terminou.

    No modo --vad, segue enviando silêncio (como um microfone aberto) até o servidor
    encerrar a escuta, sem listen_stop."""
    for i in range(0, len(pcm), BLOCO_ENTRADA):
        await ws.send(pcm[i : i + BLOCO_ENTRADA])
        if tempo_real or vad:
            await asyncio.sleep(0.02)
    fim_da_fala = time.perf_counter()
    if not vad:
        await ws.send(json.dumps({"type": "listen_stop"}))
        return fim_da_fala
    silencio = b"\x00" * BLOCO_ENTRADA
    for _ in range(int(SILENCIO_APOS_FALA_S / 0.02)):
        if parar.is_set():
            break
        await ws.send(silencio)
        await asyncio.sleep(0.02)
    return fim_da_fala


async def turno(ws, entrada: Path, saida: Path, args, taxa: int) -> int:
    pcm_entrada = (ler_wav(entrada) * 32768).clip(-32768, 32767).astype("<i2").tobytes()
    vad = args.vad or args.continuo
    if not args.continuo:
        await ws.send(json.dumps({"type": "listen_start"}))
        await esperar_estado(ws, "ouvindo")

    parar = asyncio.Event()
    envio = asyncio.create_task(_enviar_fala(ws, pcm_entrada, args.tempo_real, vad, parar))
    # Escuta contínua: sem nenhuma mensagem até o fim do silêncio, a fala foi descartada.
    espera_descarte = len(pcm_entrada) / 32_000 + SILENCIO_APOS_FALA_S + 1
    recebido: dict[str, float] = {}
    frases: list[str] = []
    emocoes: list[str] = []
    audio = bytearray()
    reconhecido = None
    abortou = None

    while True:
        try:
            espera = espera_descarte if args.continuo and not recebido else 60
            quadro = await asyncio.wait_for(ws.recv(), espera)
        except TimeoutError:
            if not args.continuo or recebido:
                raise
            await envio
            print("Descartada: a fala não começava com a palavra de ativação.")
            return 0
        instante = time.perf_counter()
        if isinstance(quadro, bytes):
            recebido.setdefault("primeiro_audio", instante)
            audio += quadro
            if args.abortar and abortou is None:
                abortou = time.perf_counter()
                await ws.send(json.dumps({"type": "abort"}))
            continue
        mensagem = json.loads(quadro)
        tipo = mensagem.get("type")
        if tipo == "tts_start" or (
            tipo == "state" and mensagem["state"] in ("pensando", "ocioso", "falando")
        ):
            parar.set()  # o servidor encerrou a escuta ou vai falar: o microfone fecha
        if tipo == "state" and mensagem["state"] == "pensando":
            recebido.setdefault("pensando", instante)
        elif tipo == "stt":
            recebido["stt"] = instante
            reconhecido = mensagem["text"]
        elif tipo == "tts_start":
            recebido.setdefault("primeira_frase", instante)
            frases.append(mensagem["text"])
        elif tipo == "emotion":
            recebido.setdefault("emocao", instante)
            emocoes.append(mensagem["emotion"])
        elif tipo == "error":
            print(f"Erro do servidor: {mensagem['message']}")
        elif tipo == "state" and mensagem["state"] in ("ocioso", "ouvindo"):
            recebido["fim"] = instante  # ouvindo: o "Oi?" da palavra de ativação
            break
    fim_da_fala = await envio

    print(f"Reconhecido: {reconhecido or '(nada)'}")
    print(f"Resposta:    {' '.join(frases) or '(nenhuma)'}")
    print(f"Emoção:      {', '.join(emocoes) or '(nenhuma)'}")
    if audio:
        escrever_wav(saida, bytes(audio), taxa)

    def desde_fala(chave: str) -> str:
        return ms(recebido[chave] - fim_da_fala if chave in recebido else None)

    modo = "escuta contínua" if args.continuo else "VAD, sem listen_stop" if vad else "listen_stop"
    print(f"Tempos desde o fim da fala ({modo}), vistos pelo cliente:")
    if vad:
        print(f"escuta encerrada:        {desde_fala('pensando')}")
    print(f"stt recebido:            {desde_fala('stt')}")
    print(f"emotion recebida:        {desde_fala('emocao')}")
    print(f"Primeiro áudio:          {desde_fala('primeiro_audio')}   ← meta: 1500 ms")
    if abortou is not None:
        print(f"abort → ocioso:          {ms(recebido['fim'] - abortou)}")
    else:
        print(f"Fim (estado ocioso):     {desde_fala('fim')}")
    if audio:
        print(f"Resposta salva em {saida}")
    return 0 if audio else 1


async def principal(url: str, args) -> int:
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
        if args.continuo and hello.get("activation") != "palavra":
            sys.exit("--continuo exige o servidor com PEGASUS_ATIVACAO=palavra.")
        print(f"Conectado: sessão {hello['session_id']}, áudio de saída a {taxa} Hz")
        await esperar_estado(ws, "ocioso")

        codigo = 0
        for n, entrada in enumerate(args.entradas, 1):
            saida = args.saida
            if len(args.entradas) > 1:
                saida = saida.with_stem(f"{saida.stem}_{n}")
                print(f"\n===== turno {n}: {entrada.name}")
            codigo |= await turno(ws, entrada, saida, args, taxa)
        return codigo


def main() -> None:
    parser = argparse.ArgumentParser(description="Envia WAVs ao servidor como se fosse o tablet.")
    parser.add_argument("entradas", type=Path, nargs="+", help="WAV 16 kHz, mono, 16 bits")
    parser.add_argument("-o", "--saida", type=Path, default=Path("resposta_ws.wav"))
    parser.add_argument("--url", default=None, help="padrão: ws://127.0.0.1:PEGASUS_PORTA_API/ws")
    parser.add_argument(
        "--tempo-real", action="store_true", help="envia o áudio no ritmo da fala (20 ms por bloco)"
    )
    parser.add_argument(
        "--vad",
        action="store_true",
        help="fala no ritmo real e espera o VAD do servidor encerrar a escuta (sem listen_stop)",
    )
    parser.add_argument("--abortar", action="store_true", help="envia abort no primeiro áudio")
    parser.add_argument(
        "--continuo",
        action="store_true",
        help="escuta contínua (servidor no modo palavra): só áudio, sem listen_start",
    )
    args = parser.parse_args()
    url = args.url or f"ws://127.0.0.1:{os.environ.get('PEGASUS_PORTA_API', '8100')}/ws"
    try:
        codigo = asyncio.run(principal(url, args))
    except ConnectionClosed as e:
        sys.exit(f"Conexão fechada pelo servidor: {e.code} {e.reason}")
    except OSError as e:
        sys.exit(f"Não foi possível conectar em {url}: {e}")
    sys.exit(codigo)


if __name__ == "__main__":
    main()
