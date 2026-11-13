"""Teste de carga: vários tablets simulados no modo palavra, ao mesmo tempo.

Cada cliente mantém o microfone aberto em tempo real (blocos de 20 ms), fala
de tempos em tempos e fecha o microfone enquanto "toca" a resposta, como o app.
Mede a latência do fim da fala ao primeiro áudio e amostra a memória da GPU.

Uso, a partir de servidor/, com a API no modo palavra:

    set -a; . ~/.config/robo-pegasus/pegasus.env; set +a
    ../.venv/bin/python -m scripts.carga --clientes 3 --minutos 10 --falas PASTA -o carga.json

PASTA tem WAVs 16 kHz mono com prefixos que dizem o que se espera de cada um:
  pergunta_*.wav     "Pegasus, ..."          → resposta
  palavra_*.wav      só "Pegasus."           → "Oi?"; em seguida vai um seguinte_*.wav
  seguinte_*.wav     pergunta sem a palavra, dita depois do "Oi?" → resposta
  sem_palavra_*.wav  fala qualquer           → descartada (nenhuma mensagem)
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from websockets.asyncio.client import connect

from app.wav import ler_wav

QUADRO = 640  # 20 ms de PCM 16 kHz, 16 bits
QUADRO_S = 0.02
ESPERA_DESCARTE_S = 4.0  # sem nenhuma mensagem nesse tempo depois da fala: descartada
TAXA_SAIDA = 22_050


@dataclass
class Evento:
    cliente: int
    tipo: str  # pergunta, palavra, seguinte, sem_palavra
    resultado: str  # resposta, oi, descartada, erro, desconectado, inesperado
    latencia_ms: float | None
    instante: float


class Microfone:
    """Envia áudio sem parar no ritmo real: a fala da fila ou silêncio. Mudo enquanto
    o robô fala (meio-duplex)."""

    def __init__(self, ws):
        self.ws = ws
        self.mudo = False
        self._fala = bytearray()
        self._fim_da_fala: asyncio.Future | None = None

    def falar(self, pcm: bytes) -> asyncio.Future:
        self._fala += pcm
        self._fim_da_fala = asyncio.get_running_loop().create_future()
        return self._fim_da_fala

    async def rodar(self) -> None:
        silencio = bytes(QUADRO)
        n, t0 = 0, time.perf_counter()
        while True:
            n += 1
            if not self.mudo:
                if self._fala:
                    quadro, self._fala = bytes(self._fala[:QUADRO]), self._fala[QUADRO:]
                    await self.ws.send(quadro.ljust(QUADRO, b"\0"))
                    if not self._fala and self._fim_da_fala and not self._fim_da_fala.done():
                        self._fim_da_fala.set_result(time.perf_counter())
                else:
                    await self.ws.send(silencio)
            await asyncio.sleep(max(0.0, t0 + n * QUADRO_S - time.perf_counter()))


async def _turno(ws, mic: Microfone, pcm: bytes, tipo: str, cliente: int) -> Evento:
    fim_da_fala = await mic.falar(pcm)
    primeiro_audio = None
    audio_bytes = 0
    oi = False
    respondeu = False  # alguma mensagem do servidor: a fala não foi descartada
    resultado = None
    while resultado is None:
        espera = 60 if respondeu else ESPERA_DESCARTE_S
        try:
            quadro = await asyncio.wait_for(ws.recv(), espera)
        except TimeoutError:
            resultado = "erro" if respondeu else "descartada"
            break
        respondeu = True
        if isinstance(quadro, bytes):
            primeiro_audio = primeiro_audio or time.perf_counter()
            audio_bytes += len(quadro)
            continue
        m = json.loads(quadro)
        if m["type"] == "tts_start":
            mic.mudo = True  # o tablet fecha o microfone para tocar a voz
            oi = oi or m["text"] == "Oi?"
        elif m["type"] == "error":
            resultado = "erro"
        elif m["type"] == "state" and m["state"] == "desconectado":
            resultado = "desconectado"
        elif m["type"] == "state" and m["state"] in ("ocioso", "ouvindo"):
            if primeiro_audio is not None:
                resultado = "oi" if oi else "resposta"
            elif m["state"] == "ocioso":
                resultado = "erro"  # turno sem áudio (stt vazio, por exemplo)
    if primeiro_audio is not None:
        # Espera a "reprodução" terminar antes de reabrir o microfone.
        fim_reproducao = primeiro_audio + audio_bytes / 2 / TAXA_SAIDA
        await asyncio.sleep(max(0.0, fim_reproducao - time.perf_counter()))
    mic.mudo = False
    latencia = None if primeiro_audio is None else (primeiro_audio - fim_da_fala) * 1000
    return Evento(cliente, tipo, resultado, latencia, time.time())


async def cliente(n: int, url: str, token: str, falas: dict, ate: float, eventos: list) -> None:
    sorteio = random.Random(n)
    async with connect(url, max_size=2**22) as ws:
        hello = {"type": "hello", "version": 1, "token": token, "device_id": f"carga-{n}"}
        await ws.send(json.dumps(hello))
        resposta = json.loads(await ws.recv())
        if resposta.get("activation") != "palavra":
            sys.exit("A API precisa estar com PEGASUS_ATIVACAO=palavra.")
        await ws.recv()  # state inicial
        mic = Microfone(ws)
        envio = asyncio.create_task(mic.rodar())
        await asyncio.sleep(sorteio.uniform(0, 3))  # os clientes não começam juntos
        try:
            while time.time() < ate:
                tipo = sorteio.choices(["pergunta", "palavra", "sem_palavra"], weights=[6, 2, 2])[0]
                ev = await _turno(ws, mic, sorteio.choice(falas[tipo]), tipo, n)
                eventos.append(ev)
                if tipo == "palavra" and ev.resultado == "oi":
                    pcm = sorteio.choice(falas["seguinte"])
                    eventos.append(await _turno(ws, mic, pcm, "seguinte", n))
                await asyncio.sleep(sorteio.uniform(1, 4))  # pausa entre falas, mic aberto
        finally:
            envio.cancel()


async def amostrar_gpu(gpu: int, ate: float, amostras: list) -> None:
    while time.time() < ate:
        saida = await asyncio.to_thread(
            subprocess.run,
            [
                "nvidia-smi",
                "-i",
                str(gpu),
                "--query-gpu=memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
        )
        usada, uso = (int(x) for x in saida.stdout.strip().split(", "))
        amostras.append({"t": time.time(), "memoria_mib": usada, "uso_pct": uso})
        await asyncio.sleep(5)


def _percentil(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def resumir(eventos: list[Evento], gpu: list[dict], segundos: float) -> dict:
    esperado = {
        "pergunta": "resposta",
        "seguinte": "resposta",
        "palavra": "oi",
        "sem_palavra": "descartada",
    }
    por_tipo = {}
    for tipo in esperado:
        evs = [e for e in eventos if e.tipo == tipo]
        lat = [e.latencia_ms for e in evs if e.latencia_ms is not None]
        resultados: dict[str, int] = {}
        for e in evs:
            resultados[e.resultado] = resultados.get(e.resultado, 0) + 1
        por_tipo[tipo] = {
            "total": len(evs),
            "certos": sum(e.resultado == esperado[tipo] for e in evs),
            "resultados": resultados,
        }
        if lat:
            por_tipo[tipo]["latencia_ms"] = {
                "mediana": round(statistics.median(lat)),
                "p90": round(_percentil(lat, 0.9)),
                "max": round(max(lat)),
                "acima_de_1500": sum(x > 1500 for x in lat),
            }
    memoria = [a["memoria_mib"] for a in gpu]
    return {
        "duracao_s": round(segundos),
        "eventos": len(eventos),
        "por_tipo": por_tipo,
        "gpu": {
            "amostras": len(gpu),
            "memoria_mib": {"min": min(memoria), "max": max(memoria)} if memoria else None,
            "uso_pct_mediana": round(statistics.median(a["uso_pct"] for a in gpu)) if gpu else None,
        },
    }


def carregar_falas(pasta: Path) -> dict[str, list[bytes]]:
    falas: dict[str, list[bytes]] = {
        k: [] for k in ("pergunta", "palavra", "seguinte", "sem_palavra")
    }
    for wav in sorted(pasta.glob("*.wav")):
        tipo = next(
            (k for k in sorted(falas, key=len, reverse=True) if wav.stem.startswith(k)), None
        )
        if tipo:
            pcm = (ler_wav(wav) * 32768).clip(-32768, 32767).astype("<i2").tobytes()
            falas[tipo].append(pcm)
    if vazios := [k for k, v in falas.items() if not v]:
        sys.exit(f"Faltam WAVs para: {', '.join(vazios)}")
    return falas


async def principal(args) -> dict:
    token = os.environ.get("PEGASUS_TOKEN") or os.environ.get("PEGASUS_TOKENS", "").split(",")[0]
    falas = carregar_falas(args.falas)
    inicio = time.time()
    ate = inicio + args.minutos * 60
    eventos: list[Evento] = []
    gpu: list[dict] = []
    await asyncio.gather(
        amostrar_gpu(args.gpu, ate, gpu),
        *(cliente(n, args.url, token.strip(), falas, ate, eventos) for n in range(args.clientes)),
    )
    resumo = resumir(eventos, gpu, time.time() - inicio)
    args.saida.write_text(
        json.dumps(
            {"resumo": resumo, "eventos": [asdict(e) for e in eventos], "gpu": gpu},
            ensure_ascii=False,
            indent=1,
        )
    )
    return resumo


def main() -> None:
    parser = argparse.ArgumentParser(description="Teste de carga no modo palavra.")
    parser.add_argument("--clientes", type=int, default=3)
    parser.add_argument("--minutos", type=float, default=10)
    parser.add_argument("--falas", type=Path, required=True)
    parser.add_argument("--gpu", type=int, default=1)
    parser.add_argument("--url", default=None)
    parser.add_argument("-o", "--saida", type=Path, default=Path("carga.json"))
    args = parser.parse_args()
    args.url = args.url or f"ws://127.0.0.1:{os.environ.get('PEGASUS_PORTA_API', '8100')}/ws"
    print(json.dumps(asyncio.run(principal(args)), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
