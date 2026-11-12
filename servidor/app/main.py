"""Servidor do Robô Pegasus: WebSocket em /ws (protocolo em docs/protocolo.md).

Uso, a partir de servidor/:

    set -a; . ~/.config/robo-pegasus/pegasus.env; set +a
    ../.venv/bin/python -m app.main
"""

import asyncio
import contextlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, WebSocket

from app.config import Config, carregar_config
from app.pipeline import stt, tts
from app.sessao import Sessao
from app.wav import TAXA_ENTRADA

log = logging.getLogger("pegasus")

VERSAO_PROTOCOLO = 1
TEMPO_HELLO_S = 5
TEMPO_INATIVO_S = 45

FECHA_PROTOCOLO = 4000
FECHA_TOKEN = 4001
FECHA_TEMPO = 4008


async def preparar_modelos(config: Config) -> int:
    """Carrega e aquece Whisper e Piper; devolve a taxa do áudio de saída."""
    await stt.carregar(config)
    voz = await tts.carregar(config)
    # A primeira execução compila os kernels do CTranslate2; melhor aqui que no 1º turno.
    await stt.transcrever(np.zeros(TAXA_ENTRADA, dtype=np.float32), config)
    await tts.sintetizar("Olá.", config)
    return voz.config.sample_rate


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = carregar_config()
    if not config.tokens:
        log.warning("PEGASUS_TOKENS vazio: todas as conexões serão recusadas.")
    app.state.config = config
    app.state.taxa_saida = await preparar_modelos(config)
    log.info("modelos prontos; áudio de saída a %d Hz", app.state.taxa_saida)
    yield


app = FastAPI(title="Robô Pegasus", lifespan=lifespan)


def token_valido(token: object, tokens: frozenset[str]) -> bool:
    if not isinstance(token, str):
        return False
    # Compara com todos, em tempo constante, para não vazar qual token quase bateu.
    return any([hmac.compare_digest(token.encode(), t.encode()) for t in tokens])


def _validar_hello(mensagem: dict, config: Config) -> tuple[int, str] | None:
    """Devolve (código, motivo) para fechar a conexão, ou None se o hello é válido."""
    if mensagem.get("type") != "hello":
        return FECHA_PROTOCOLO, "a primeira mensagem deve ser hello"
    if mensagem.get("version") != VERSAO_PROTOCOLO:
        return FECHA_PROTOCOLO, f"versão do protocolo não suportada (esperada {VERSAO_PROTOCOLO})"
    audio = mensagem.get("audio") or {}
    esperado = {"format": "pcm_s16le", "sample_rate": TAXA_ENTRADA, "channels": 1}
    if any(audio.get(k, v) != v for k, v in esperado.items()):
        return FECHA_PROTOCOLO, "formato de áudio não suportado"
    if not token_valido(mensagem.get("token"), config.tokens):
        return FECHA_TOKEN, "token inválido"
    return None


async def _receber_json(ws: WebSocket, tempo_s: float) -> dict | None:
    """Recebe um quadro de texto JSON; None se a conexão fechou."""
    quadro = await asyncio.wait_for(ws.receive(), tempo_s)
    if quadro["type"] == "websocket.disconnect":
        return None
    if quadro.get("text") is None:
        raise ValueError("quadro binário fora de hora")
    mensagem = json.loads(quadro["text"])
    if not isinstance(mensagem, dict):
        raise ValueError("mensagem JSON deve ser um objeto")
    return mensagem


@app.websocket("/ws")
async def conexao(ws: WebSocket) -> None:
    await ws.accept()
    config: Config = ws.app.state.config

    try:
        hello = await _receber_json(ws, TEMPO_HELLO_S)
    except TimeoutError:
        await ws.close(FECHA_TEMPO, "hello não recebido")
        return
    except ValueError:
        await ws.close(FECHA_PROTOCOLO, "hello inválido")
        return
    if hello is None:
        return
    if falha := _validar_hello(hello, config):
        log.warning("conexão recusada: %s", falha[1])
        await ws.close(*falha)
        return

    sessao = Sessao(ws, config, str(hello.get("device_id") or "sem-id")[:64])
    log.info("sessão %s: tablet %s conectado", sessao.id, sessao.device_id)
    await sessao.enviar_json(
        {
            "type": "hello",
            "version": VERSAO_PROTOCOLO,
            "session_id": sessao.id,
            "audio": {"format": "pcm_s16le", "sample_rate": ws.app.state.taxa_saida, "channels": 1},
        }
    )
    await sessao.mudar_estado("ocioso")

    try:
        await _atender(ws, sessao)
    finally:
        with contextlib.suppress(Exception):
            await sessao.cancelar_turno()
        log.info("sessão %s: desconectada", sessao.id)


async def _atender(ws: WebSocket, sessao: Sessao) -> None:
    while True:
        try:
            quadro = await asyncio.wait_for(ws.receive(), TEMPO_INATIVO_S)
        except TimeoutError:
            await ws.close(FECHA_TEMPO, "sem mensagens do tablet")
            return
        if quadro["type"] == "websocket.disconnect":
            return
        if quadro.get("bytes") is not None:
            sessao.ao_audio(quadro["bytes"])
            continue
        try:
            mensagem = json.loads(quadro["text"])
            tipo = mensagem.get("type")
        except (ValueError, AttributeError):
            await ws.close(FECHA_PROTOCOLO, "mensagem JSON inválida")
            return

        match tipo:
            case "listen_start":
                await sessao.ao_listen_start()
            case "listen_stop":
                await sessao.ao_listen_stop()
            case "abort":
                await sessao.ao_abort()
            case "ping":
                pong = {"type": "pong"}
                if "t" in mensagem:
                    pong["t"] = mensagem["t"]
                await sessao.enviar_json(pong)
            case "hello":
                await ws.close(FECHA_PROTOCOLO, "hello repetido")
                return
            case _:
                log.debug("sessão %s: mensagem ignorada: %s", sessao.id, tipo)


if __name__ == "__main__":
    import uvicorn

    config = carregar_config()
    uvicorn.run("app.main:app", host=config.api_host, port=config.api_porta, ws="websockets-sansio")
