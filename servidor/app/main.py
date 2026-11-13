"""Servidor do Robô Pegasus: WebSocket em /ws (protocolo em docs/protocolo.md).

Uso, a partir de servidor/:

    set -a; . ~/.config/robo-pegasus/pegasus.env; set +a
    ../.venv/bin/python -m app.main
"""

import asyncio
import collections
import contextlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket

from app import persona, registro, saude, seguranca
from app.config import Config, carregar_config, resumo_publico
from app.pipeline import stt, tts, vad
from app.sessao import Sessao
from app.wav import TAXA_ENTRADA

log = logging.getLogger("pegasus")

VERSAO_PROTOCOLO = 1
TEMPO_HELLO_S = 5
TEMPO_INATIVO_S = 45

FECHA_PROTOCOLO = 4000
FECHA_TOKEN = 4001
FECHA_TEMPO = 4008
FECHA_POLITICA = 1008  # IP bloqueado (antes do accept: o cliente recebe HTTP 403)


async def preparar_modelos(config: Config) -> int:
    """Carrega e aquece Whisper e Piper; devolve a taxa do áudio de saída."""
    await stt.carregar(config)
    voz = await tts.carregar(config)
    vad.preparar()
    # A primeira execução compila os kernels do CTranslate2; melhor aqui que no 1º turno.
    await stt.transcrever(np.zeros(TAXA_ENTRADA, dtype=np.float32), config)
    await tts.sintetizar("Olá.", config)
    return voz.config.sample_rate


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # O faster-whisper registra a duração de cada áudio; na escuta contínua isso
    # deixaria rastro das falas descartadas.
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    # O httpx registra cada verificação de saúde do vLLM (uma a cada 5 s).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    config = carregar_config()
    arquivo_turnos = registro.configurar(config.log_pasta, config.log_dias)
    if not config.tablets:
        log.warning("PEGASUS_TABLETS vazio: todas as conexões serão recusadas.")
    if "PEGASUS_TOKENS" in os.environ:
        log.warning("PEGASUS_TOKENS é ignorado: os tokens agora são por tablet (PEGASUS_TABLETS)")
    log.info("configuração: %s", json.dumps(resumo_publico(config), ensure_ascii=False))
    p = persona.carregar(config.persona_arquivo)
    log.info("turnos registrados em %s", arquivo_turnos)
    log.info("persona: %s (%d frases no máximo)", p.nome, p.frases_max)
    app.state.config = config
    app.state.taxa_saida = await preparar_modelos(config)
    log.info("modelos prontos; áudio de saída a %d Hz", app.state.taxa_saida)
    app.state.bloqueio = seguranca.Bloqueio(config.proxies)
    sessoes: set[Sessao] = set()
    app.state.sessoes = sessoes
    app.state.inicio = time.time()

    async def avisar(disponivel: bool) -> None:
        await asyncio.gather(*(s.ao_llm(disponivel) for s in list(sessoes)), return_exceptions=True)

    monitor = saude.MonitorLLM(saude.verificador_http(config), avisar)
    app.state.monitor = monitor
    await monitor.iniciar()
    if not monitor.disponivel:
        log.error("LLM fora do ar na subida; os tablets ficam em desconectado até ele subir")
    try:
        yield
    finally:
        await monitor.parar()


app = FastAPI(title="Robô Pegasus", lifespan=lifespan)


# "testclient" é o endereço que o TestClient do Starlette informa nos testes.
_LOCAIS = {"127.0.0.1", "::1", "testclient"}


@app.get("/status")
async def status(request: Request) -> dict:
    """Estado da API para o pegasus-status. Só para quem está no próprio servidor;
    sem segredos, textos ou nomes de tablets."""
    if request.client is None or request.client.host not in _LOCAIS:
        raise HTTPException(status_code=404)
    estado = request.app.state
    monitor: saude.MonitorLLM = estado.monitor
    return {
        "versao_protocolo": VERSAO_PROTOCOLO,
        "ativacao": estado.config.ativacao,
        "no_ar_s": round(time.time() - estado.inicio),
        "llm": {
            "disponivel": monitor.disponivel,
            "desde_s": round(time.time() - monitor.desde),
            "quedas": monitor.quedas,
        },
        "sessoes": {
            "total": len(estado.sessoes),
            "por_estado": dict(collections.Counter(s.estado for s in estado.sessoes)),
        },
        "turnos": registro.resumo(),
    }


def _validar_hello(mensagem: dict, config: Config) -> tuple[int, str] | str:
    """Devolve o nome do tablet, se o hello é válido, ou (código, motivo) para fechar."""
    if mensagem.get("type") != "hello":
        return FECHA_PROTOCOLO, "a primeira mensagem deve ser hello"
    if mensagem.get("version") != VERSAO_PROTOCOLO:
        return FECHA_PROTOCOLO, f"versão do protocolo não suportada (esperada {VERSAO_PROTOCOLO})"
    audio = mensagem.get("audio") or {}
    esperado = {"format": "pcm_s16le", "sample_rate": TAXA_ENTRADA, "channels": 1}
    if any(audio.get(k, v) != v for k, v in esperado.items()):
        return FECHA_PROTOCOLO, "formato de áudio não suportado"
    tablet = seguranca.identificar(mensagem.get("token"), config.tablets)
    if tablet is None:
        return FECHA_TOKEN, "token inválido"
    return tablet


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


async def _recusar(ws: WebSocket, ip: str, codigo: int, motivo: str, hello: dict | None) -> None:
    """Fecha a conexão com um hello inválido, registra a tentativa (sem o token) e
    conta a falha para o bloqueio do IP."""
    detalhe = ""
    if hello is not None and "device_id" in hello:
        detalhe = f" (device_id {seguranca.limpar_para_log(hello['device_id'])})"
    log.warning("conexão recusada de %s: %s%s", ip, motivo, detalhe)
    bloqueio: seguranca.Bloqueio = ws.app.state.bloqueio
    if bloqueio.falhou(ip):
        log.warning("IP %s bloqueado por 15 min: 5 hellos inválidos em 10 min", ip)
    with contextlib.suppress(Exception):
        await ws.close(codigo, motivo)


@app.websocket("/ws")
async def conexao(ws: WebSocket) -> None:
    config: Config = ws.app.state.config
    direto = ws.client.host if ws.client else None
    ip = seguranca.ip_real(direto, ws.headers.get("x-forwarded-for"), config.proxies)
    bloqueio: seguranca.Bloqueio = ws.app.state.bloqueio
    if bloqueio.bloqueado(ip):
        n = bloqueio.recusadas(ip)
        if n == 1 or n % 100 == 0:  # sem inundar o log durante um ataque
            log.warning("conexão recusada de %s: IP bloqueado (%d recusadas no bloqueio)", ip, n)
        await ws.close(FECHA_POLITICA)
        return
    await ws.accept()

    hello = None
    try:
        hello = await _receber_json(ws, TEMPO_HELLO_S)
    except TimeoutError:
        await _recusar(ws, ip, FECHA_TEMPO, "hello não recebido em 5 s", None)
        return
    except ValueError:
        await _recusar(ws, ip, FECHA_PROTOCOLO, "hello inválido", None)
        return
    if hello is None:
        return
    tablet = _validar_hello(hello, config)
    if isinstance(tablet, tuple):
        await _recusar(ws, ip, *tablet, hello)
        return

    # O tablet é quem o token diz; o device_id do hello não identifica ninguém.
    monitor: saude.MonitorLLM = ws.app.state.monitor
    sessao = Sessao(ws, config, tablet, monitor)
    log.info("sessão %s: tablet %s conectado de %s", sessao.id, sessao.device_id, ip)
    await sessao.enviar_json(
        {
            "type": "hello",
            "version": VERSAO_PROTOCOLO,
            "session_id": sessao.id,
            "audio": {"format": "pcm_s16le", "sample_rate": ws.app.state.taxa_saida, "channels": 1},
            "activation": config.ativacao,
        }
    )
    await sessao.mudar_estado(sessao.estado_livre())
    ws.app.state.sessoes.add(sessao)

    try:
        await _atender(ws, sessao)
    finally:
        ws.app.state.sessoes.discard(sessao)
        with contextlib.suppress(Exception):
            await sessao.encerrar()
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
            await sessao.ao_audio(quadro["bytes"])
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
    # proxy_headers=False: o IP real é decidido aqui (seguranca.ip_real), não pelo uvicorn.
    uvicorn.run(
        "app.main:app",
        host=config.api_host,
        port=config.api_porta,
        ws="websockets-sansio",
        proxy_headers=False,
    )
