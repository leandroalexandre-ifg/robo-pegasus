"""Mede, de ponta a ponta, os turnos com e sem ferramentas de internet.

Sintetiza cada pergunta com o Piper ("Pegasus, <pergunta>"), reamostra para 16 kHz e
a envia em tempo real pela escuta contínua (modo palavra), uma conexão por pergunta
(sem memória entre elas). Mede, do fim da fala:
  - primeiro áudio: o primeiro som (pode ser o "Deixa eu ver…");
  - resposta: o primeiro áudio da resposta de fato (depois da frase de espera).

Uso, a partir de servidor/, com a API no modo palavra:

    set -a; . ~/.config/robo-pegasus/pegasus.env; set +a
    ../.venv/bin/python -m scripts.medir_ferramentas -o medida.json
    ../.venv/bin/python -m scripts.medir_ferramentas --so-conversa -o antes.json

O texto das respostas só vai para o arquivo de saída, para conferência local.
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np
from websockets.asyncio.client import connect

from app.config import carregar_config
from app.pipeline import tts
from app.pipeline.turno import FRASES_ESPERA
from scripts import tokens

QUADRO = 640  # 20 ms de PCM 16 kHz, 16 bits
SILENCIO_DEPOIS_S = 3.0

PERGUNTAS = {
    "conversa": [
        "tudo bem com você?",
        "qual é o seu nome?",
        "me conta uma piada.",
        "quanto é sete vezes oito?",
        "qual é a sua cor favorita?",
        "você gosta de música?",
    ],
    "data_hora": [
        "que horas são?",
        "que dia é hoje?",
        "em que mês nós estamos?",
    ],
    "clima": [
        "vai chover amanhã?",
        "como está o tempo agora?",
        "qual é a temperatura em São Paulo?",
        "vai fazer frio em Curitiba amanhã?",
        "como está o tempo em Lisboa?",
    ],
    "wikipedia": [
        "quem foi Santos Dumont?",
        "o que é a fotossíntese?",
        "quem foi Cora Coralina?",
        "o que é um buraco negro?",
        "quem foi Tiradentes?",
    ],
    "busca_web": [
        "qual foi o resultado do último jogo do Flamengo?",
        "quais são as notícias de hoje no Brasil?",
        "quem ganhou a última Copa do Mundo de futebol?",
        "qual é a cotação do dólar hoje?",
        "quem é o atual presidente da França?",
    ],
}


async def sintetizar(texto: str, config) -> bytes:
    pcm, taxa = await tts.sintetizar(texto, config)
    voz = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    n = int(len(voz) * 16_000 / taxa)
    reamostrada = np.interp(np.linspace(0, len(voz) - 1, n), np.arange(len(voz)), voz)
    # O Piper deixa silêncio no fim: sem cortar, o "fim da fala" do cliente viria
    # depois do fim real, e a latência medida ficaria menor que a de verdade.
    voz_alta = np.flatnonzero(np.abs(reamostrada) > 300)
    if len(voz_alta):
        reamostrada = reamostrada[: voz_alta[-1] + 1]
    silencio = np.zeros(int(0.3 * 16_000), dtype=np.float32)
    return np.concatenate([silencio, reamostrada]).clip(-32768, 32767).astype("<i2").tobytes()


async def um_turno(url: str, token: str, pcm: bytes) -> dict:
    async with connect(url, max_size=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "version": 1,
                    "token": token,
                    "device_id": "medida",
                    "audio": {"format": "pcm_s16le", "sample_rate": 16000, "channels": 1},
                }
            )
        )
        while json.loads(await ws.recv()).get("type") != "hello":
            pass
        parar = asyncio.Event()

        async def enviar() -> float:
            for i in range(0, len(pcm), QUADRO):
                await ws.send(pcm[i : i + QUADRO])
                await asyncio.sleep(0.02)
            fim = time.perf_counter()
            for _ in range(int(SILENCIO_DEPOIS_S / 0.02)):
                if parar.is_set():
                    break
                await ws.send(b"\x00" * QUADRO)
                await asyncio.sleep(0.02)
            return fim

        envio = asyncio.create_task(enviar())
        r: dict = {"frases": [], "erro": None}
        frase_atual = None
        while True:
            # Sem nada até 4 s depois da fala: o servidor não ouviu "Pegasus" e a descartou.
            espera = (
                30 if "frases" in r and r["frases"] or "stt_texto" in r else len(pcm) / 32_000 + 4
            )
            try:
                quadro = await asyncio.wait_for(ws.recv(), espera)
            except TimeoutError:
                r["erro"] = "sem resposta" if "stt_texto" in r else "descartada (sem a palavra)"
                break
            agora = time.perf_counter()
            if isinstance(quadro, bytes):
                r.setdefault("primeiro_audio", agora)
                if frase_atual is not None and frase_atual not in FRASES_ESPERA:
                    r.setdefault("resposta", agora)
                continue
            m = json.loads(quadro)
            tipo = m.get("type")
            if tipo == "tts_start":
                parar.set()
                frase_atual = m["text"]
                r["frases"].append(frase_atual)
            elif tipo == "stt":
                r["stt_texto"] = m["text"]
            elif tipo == "error":
                r["erro"] = m["message"]
            elif tipo == "state" and m["state"] == "pensando":
                parar.set()
            elif tipo == "state" and m["state"] in ("ocioso", "ouvindo") and r["frases"]:
                r["fim"] = agora
                break
        parar.set()
        fim_fala = await envio
        for chave in ("primeiro_audio", "resposta", "fim"):
            if chave in r:
                r[chave + "_ms"] = round((r.pop(chave) - fim_fala) * 1000)
        r["espera"] = bool(r["frases"]) and r["frases"][0] in FRASES_ESPERA
        return r


def _estat(xs: list[int]) -> dict | None:
    if not xs:
        return None
    xs = sorted(xs)
    return {
        "n": len(xs),
        "mediana": round(statistics.median(xs)),
        "p90": xs[min(len(xs) - 1, int(0.9 * len(xs)))],
        "min": xs[0],
        "max": xs[-1],
    }


async def principal(args) -> dict:
    config = carregar_config()
    url = args.url or f"ws://127.0.0.1:{config.api_porta}/ws"
    token = os.environ.get("PEGASUS_TOKEN") or tokens.de_teste()[0]
    grupos = {"conversa": PERGUNTAS["conversa"]} if args.so_conversa else PERGUNTAS
    turnos = []
    for rodada in range(args.rodadas):
        for grupo, perguntas in grupos.items():
            for pergunta in perguntas:
                pcm = await sintetizar(f"Pegasus, {pergunta}", config)
                r = await um_turno(url, token, pcm)
                r |= {"grupo": grupo, "pergunta": pergunta, "rodada": rodada}
                turnos.append(r)
                print(
                    f"{grupo:10} {r.get('primeiro_audio_ms', '—'):>6} "
                    f"{r.get('resposta_ms', '—'):>6} {'espera' if r['espera'] else '':6} "
                    f"{r['erro'] or ''}",
                    flush=True,
                )
                await asyncio.sleep(args.pausa)
    resumo = {}
    for grupo in grupos:
        g = [t for t in turnos if t["grupo"] == grupo and not t["erro"]]
        resumo[grupo] = {
            "turnos": len([t for t in turnos if t["grupo"] == grupo]),
            "erros": len([t for t in turnos if t["grupo"] == grupo and t["erro"]]),
            "com_espera": sum(t["espera"] for t in g),
            "primeiro_audio_ms": _estat(
                [t["primeiro_audio_ms"] for t in g if "primeiro_audio_ms" in t]
            ),
            "resposta_ms": _estat([t["resposta_ms"] for t in g if "resposta_ms" in t]),
        }
    return {"resumo": resumo, "turnos": turnos}


def main() -> None:
    p = argparse.ArgumentParser(description="Latência com e sem ferramentas de internet.")
    p.add_argument("--url", default=None)
    p.add_argument("--rodadas", type=int, default=1)
    p.add_argument("--pausa", type=float, default=1.0)
    p.add_argument("--so-conversa", action="store_true", help="só perguntas sem ferramenta")
    p.add_argument("-o", "--saida", type=Path, default=Path("medida_ferramentas.json"))
    args = p.parse_args()
    dados = asyncio.run(principal(args))
    args.saida.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(dados["resumo"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
