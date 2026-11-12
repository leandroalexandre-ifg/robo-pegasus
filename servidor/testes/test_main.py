import asyncio
import json

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main
from app.pipeline import llm, stt, tts
from app.pipeline.emocao import Emocao

TOKEN = "token-de-teste"
TAXA = 22_050


@pytest.fixture
def pipeline(monkeypatch):
    """Substitui Whisper, LLM e Piper por falsos; devolve o que eles recebem."""
    estado = {
        "transcricao": "qual é o seu nome?",
        "pedacos": [Emocao("feliz"), "Olá! ", "Sou o Pegasus."],
    }

    async def preparar_modelos(config):
        return TAXA

    async def transcrever(audio, config):
        estado["audio_s"] = len(audio) / 16_000
        return estado["transcricao"]

    async def gerar(texto, config):
        for p in estado["pedacos"]:
            if isinstance(p, Exception):
                raise p
            if p is None:
                await asyncio.sleep(30)  # LLM "travado", para testar o abort
            yield p

    async def sintetizar(texto, config):
        return b"\x01\x00" * int(TAXA * 0.25), TAXA  # 250 ms → 3 blocos de até 100 ms

    monkeypatch.setenv("PEGASUS_TOKENS", f"outro,{TOKEN}")
    monkeypatch.setattr(main, "preparar_modelos", preparar_modelos)
    monkeypatch.setattr(stt, "transcrever", transcrever)
    monkeypatch.setattr(llm, "gerar", gerar)
    monkeypatch.setattr(tts, "sintetizar", sintetizar)
    return estado


@pytest.fixture
def cliente(pipeline):
    with TestClient(main.app) as c:
        yield c


def _hello(**extra):
    return {
        "type": "hello",
        "version": 1,
        "token": TOKEN,
        "device_id": "tablet-teste",
        "audio": {"format": "pcm_s16le", "sample_rate": 16000, "channels": 1, "frame_ms": 20},
    } | extra


def _conectar(ws):
    ws.send_json(_hello())
    resposta = ws.receive_json()
    assert resposta["type"] == "hello"
    assert resposta["audio"]["sample_rate"] == TAXA
    assert ws.receive_json() == {"type": "state", "state": "ocioso"}


def _receber_ate_ocioso(ws):
    """Recebe mensagens até o estado ocioso; binários viram ('audio', n_bytes)."""
    recebidas = []
    while True:
        quadro = ws.receive()
        if quadro.get("bytes") is not None:
            recebidas.append(("audio", len(quadro["bytes"])))
            continue
        mensagem = json.loads(quadro["text"])
        recebidas.append(mensagem)
        if mensagem == {"type": "state", "state": "ocioso"}:
            return recebidas


def _falar(ws, segundos=1.0):
    ws.send_json({"type": "listen_start"})
    assert ws.receive_json() == {"type": "state", "state": "ouvindo"}
    for _ in range(int(segundos / 0.02)):
        ws.send_bytes(b"\x00\x00" * 320)
    ws.send_json({"type": "listen_stop"})


def _tipos(recebidas):
    return [m[0] if isinstance(m, tuple) else m.get("state", m["type"]) for m in recebidas]


def test_turno_completo(cliente, pipeline):
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws, 1.0)
        recebidas = _receber_ate_ocioso(ws)

    assert pipeline["audio_s"] == pytest.approx(1.0)
    frase = ["tts_start", "audio", "audio", "audio", "tts_end"]
    esperado = ["pensando", "stt", "emotion", "falando", *frase, *frase, "ocioso"]
    assert _tipos(recebidas) == esperado
    assert recebidas[1] == {"type": "stt", "text": "qual é o seu nome?"}
    assert recebidas[2] == {"type": "emotion", "emotion": "feliz"}
    assert recebidas[4] == {"type": "tts_start", "text": "Olá!", "sample_rate": TAXA}
    assert recebidas[9]["text"] == "Sou o Pegasus."
    # 5512 amostras (11024 bytes) em blocos de 100 ms (2205 amostras, 4410 bytes)
    assert [n for _, n in recebidas[5:8]] == [4410, 4410, 2204]


def test_sem_fala_reconhecida_volta_a_ocioso(cliente, pipeline):
    pipeline["transcricao"] = ""
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        assert _tipos(_receber_ate_ocioso(ws)) == ["pensando", "stt", "ocioso"]


def test_audio_fora_da_escuta_e_ignorado(cliente):
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        ws.send_bytes(b"\x00\x00" * 320)  # antes do listen_start: descartado
        ws.send_json({"type": "listen_start"})
        assert ws.receive_json()["state"] == "ouvindo"
        ws.send_json({"type": "listen_stop"})
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}


def test_abort_interrompe_a_resposta(cliente, pipeline):
    pipeline["pedacos"] = ["Primeira frase. ", None, "Nunca chega."]
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        # pensando, stt, emotion, falando, tts_start
        recebidas = [ws.receive_json() for _ in range(5)]
        assert recebidas[4]["text"] == "Primeira frase."
        while (q := ws.receive()).get("bytes") is not None:
            pass
        assert json.loads(q["text"]) == {"type": "tts_end"}
        ws.send_json({"type": "abort"})
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}
        ws.send_json({"type": "ping", "t": 1})  # a conexão segue viva
        assert ws.receive_json() == {"type": "pong", "t": 1}


def test_llm_fora_do_ar_envia_erro(cliente, pipeline):
    pipeline["pedacos"] = [openai.APIConnectionError(request=httpx.Request("POST", "http://x"))]
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        recebidas = _receber_ate_ocioso(ws)
    assert _tipos(recebidas) == ["pensando", "stt", "error", "ocioso"]
    assert "linguagem" in recebidas[2]["message"]


def test_ping_pong(cliente):
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        ws.send_json({"type": "ping", "t": 123})
        assert ws.receive_json() == {"type": "pong", "t": 123}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


@pytest.mark.parametrize(
    ("primeira", "codigo"),
    [
        (_hello(token="errado"), 4001),
        (_hello(token=None), 4001),
        (_hello(version=2), 4000),
        (_hello(audio={"format": "opus"}), 4000),
        ({"type": "listen_start"}, 4000),
    ],
)
def test_hello_recusado(cliente, primeira, codigo):
    with cliente.websocket_connect("/ws") as ws:
        ws.send_json(primeira)
        with pytest.raises(WebSocketDisconnect) as erro:
            ws.receive_json()
    assert erro.value.code == codigo


def test_sem_tokens_configurados_recusa(monkeypatch, pipeline):
    monkeypatch.setenv("PEGASUS_TOKENS", "")
    with TestClient(main.app) as c, c.websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        with pytest.raises(WebSocketDisconnect) as erro:
            ws.receive_json()
    assert erro.value.code == 4001


def test_token_valido():
    assert main.token_valido("b", frozenset({"a", "b"}))
    assert not main.token_valido("c", frozenset({"a", "b"}))
    assert not main.token_valido(123, frozenset({"a"}))
    assert not main.token_valido("a", frozenset())


def test_sem_emocao_do_llm_envia_neutro_antes_do_audio(cliente, pipeline):
    pipeline["pedacos"] = ["Olá! ", "Sou o Pegasus."]
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        recebidas = _receber_ate_ocioso(ws)
    emocoes = [m for m in recebidas if isinstance(m, dict) and m["type"] == "emotion"]
    assert emocoes == [{"type": "emotion", "emotion": "neutro"}]
    primeiro_audio = next(i for i, m in enumerate(recebidas) if isinstance(m, tuple))
    assert recebidas.index(emocoes[0]) < primeiro_audio
