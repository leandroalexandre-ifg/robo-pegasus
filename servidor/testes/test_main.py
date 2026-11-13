import asyncio
import json
import time

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main, saude
from app import sessao as sessao_mod
from app.pipeline import llm, stt, tts
from app.pipeline.emocao import Emocao

TOKEN = "token-de-teste"
TAXA = 22_050


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
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

    async def gerar(texto, config, historico=()):
        estado.setdefault("historicos", []).append(list(historico))
        for p in estado["pedacos"]:
            if isinstance(p, Exception):
                raise p
            if p is None:
                await asyncio.sleep(30)  # LLM "travado", para testar o abort
            yield p

    async def sintetizar(texto, config):
        return b"\x01\x00" * int(TAXA * 0.25), TAXA  # 250 ms → 3 blocos de até 100 ms

    monkeypatch.setenv("PEGASUS_TOKENS", f"outro,{TOKEN}")
    monkeypatch.setenv("PEGASUS_LOG_PASTA", str(tmp_path))
    estado["llm_no_ar"] = True

    def verificador(config):
        async def verificar():
            return estado["llm_no_ar"]

        return verificar

    monkeypatch.setattr(saude, "verificador_http", verificador)
    monkeypatch.setattr(saude, "INTERVALO_S", 0.02)
    monkeypatch.setattr(saude, "INTERVALO_FORA_S", 0.02)
    estado["turnos"] = tmp_path / "turnos.jsonl"
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


def _receber_ate_estado(ws, estado):
    """Como _receber_ate_ocioso, até o estado pedido."""
    recebidas = []
    while True:
        quadro = ws.receive()
        if quadro.get("bytes") is not None:
            recebidas.append(("audio", len(quadro["bytes"])))
            continue
        mensagem = json.loads(quadro["text"])
        recebidas.append(mensagem)
        if mensagem == {"type": "state", "state": estado}:
            return recebidas


CONVERSANDO = {"type": "conversation", "state": "conversando", "timeout_ms": 8000}
ESPERANDO_NOME = {"type": "conversation", "state": "esperando_nome"}


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


class _DetectorFalso:
    """Simula o Silero: fala de `inicio_s` a `fim_s`, fim decidido em `decide_s`."""

    roteiro = (0.5, 1.5, 2.1)

    def __init__(self, config):
        self._inicio_s, self._fim_s, self._decide_s = self.roteiro
        self._amostras = 0
        self.inicio = self.fim = None
        self.terminou = False

    @property
    def falou(self):
        return self.inicio is not None

    @property
    def silencio_s(self):
        return 0.0 if self.fim is None else self._amostras / 16_000 - self._fim_s

    @property
    def fala_s(self):
        return 0.0 if self.inicio is None else self._amostras / 16_000 - self._inicio_s

    def processar(self, pcm):
        if self.terminou:
            return None
        self._amostras += len(pcm) // 2
        agora = self._amostras / 16_000
        if self.inicio is None and agora >= self._inicio_s:
            self.inicio = round(self._inicio_s * 16_000)
            return "inicio"
        if self.inicio is not None and agora >= self._fim_s:
            self.fim = round(self._fim_s * 16_000)  # o silêncio começou
        if self.fim is not None and agora >= self._decide_s:
            self.terminou = True
            return "fim"
        return None


def _enviar_audio(ws, segundos):
    for _ in range(int(segundos / 0.02)):
        ws.send_bytes(b"\x00\x00" * 320)


def test_vad_encerra_a_escuta_sem_listen_stop(cliente, pipeline, monkeypatch):
    monkeypatch.setattr(sessao_mod, "DetectorFala", _DetectorFalso)
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        ws.send_json({"type": "listen_start"})
        assert ws.receive_json()["state"] == "ouvindo"
        _enviar_audio(ws, 3.0)  # o fim é decidido aos 2,1 s; o resto é descartado
        recebidas = _receber_ate_ocioso(ws)
    assert _tipos(recebidas)[:3] == ["pensando", "stt", "emotion"]
    # fala de 0,5 s a 1,5 s, com 0,3 s antes e 0,2 s depois
    assert pipeline["audio_s"] == pytest.approx(1.5)


def test_listen_stop_continua_valendo(cliente, pipeline, monkeypatch):
    _DetectorFalso.roteiro = (0.2, 0.6, 99)  # o VAD nunca decide sozinho
    monkeypatch.setattr(sessao_mod, "DetectorFala", _DetectorFalso)
    try:
        with cliente.websocket_connect("/ws") as ws:
            _conectar(ws)
            _falar(ws, 1.0)
            assert _tipos(_receber_ate_ocioso(ws))[:2] == ["pensando", "stt"]
    finally:
        _DetectorFalso.roteiro = (0.5, 1.5, 2.1)
    # recortado em volta da fala detectada: 0,2 - 0,3 → 0; 0,6 + 0,2 = 0,8
    assert pipeline["audio_s"] == pytest.approx(0.8)


def test_escuta_sem_fala_volta_a_ocioso(monkeypatch, pipeline):
    monkeypatch.setenv("PEGASUS_VAD_SEM_FALA_MS", "400")
    with TestClient(main.app) as c, c.websocket_connect("/ws") as ws:
        _conectar(ws)
        ws.send_json({"type": "listen_start"})
        assert ws.receive_json()["state"] == "ouvindo"
        _enviar_audio(ws, 0.5)  # silêncio (o Silero de verdade não vê fala)
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}
    assert "audio_s" not in pipeline  # nada foi transcrito


def _turno(ws, transcricao, pipeline):
    pipeline["transcricao"] = transcricao
    _falar(ws)
    return _receber_ate_ocioso(ws)


def test_memoria_guarda_os_ultimos_turnos_da_conexao(monkeypatch, pipeline):
    monkeypatch.setenv("PEGASUS_MEMORIA_TURNOS", "2")
    pipeline["pedacos"] = ["Resposta."]
    with TestClient(main.app) as c:
        with c.websocket_connect("/ws") as ws:
            _conectar(ws)
            for fala in ("um", "dois", "três"):
                _turno(ws, fala, pipeline)
        with c.websocket_connect("/ws") as ws:  # nova conexão: memória vazia
            _conectar(ws)
            _turno(ws, "quatro", pipeline)
    assert pipeline["historicos"] == [
        [],
        [("um", "Resposta.")],
        [("um", "Resposta."), ("dois", "Resposta.")],
        [],
    ]


def test_resposta_interrompida_fica_na_memoria_com_o_que_foi_dito(cliente, pipeline):
    pipeline["pedacos"] = ["Primeira frase. ", None, "Nunca chega."]
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        while (m := ws.receive()).get("text") is None or json.loads(m["text"])["type"] != "tts_end":
            pass
        ws.send_json({"type": "abort"})
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}
        pipeline["pedacos"] = ["Ok."]
        _turno(ws, "e agora?", pipeline)
    assert pipeline["historicos"][-1] == [("qual é o seu nome?", "Primeira frase.")]


def test_abort_fecha_o_fluxo_do_llm_e_cancela_a_emocao(cliente, pipeline, monkeypatch):
    fechou, emocao_cancelada = [], []

    async def gerar(texto, config, historico=()):
        try:
            yield "Primeira frase. "
            await asyncio.sleep(30)  # o LLM ainda gerando quando chega o abort
            yield "Nunca chega."
        finally:
            fechou.append(True)

    async def escolher_emocao(texto, config, historico=()):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            emocao_cancelada.append(True)
            raise

    monkeypatch.setenv("PEGASUS_EMOCAO_MODO", "paralelo")
    monkeypatch.setenv("PEGASUS_EMOCAO_ESPERA_MS", "10")
    monkeypatch.setattr(llm, "gerar", gerar)
    monkeypatch.setattr(llm, "escolher_emocao", escolher_emocao)
    with TestClient(main.app) as c, c.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        while (m := ws.receive()).get("text") is None or json.loads(m["text"])["type"] != "tts_end":
            pass
        inicio = time.perf_counter()
        ws.send_json({"type": "abort"})
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}
        assert time.perf_counter() - inicio < 0.5
    assert fechou == [True]
    assert emocao_cancelada == [True]


def test_abort_durante_o_tts_responde_na_hora(cliente, pipeline, monkeypatch):
    async def sintetizar_lento(texto, config):
        await asyncio.sleep(30)
        return b"", TAXA

    monkeypatch.setattr(tts, "sintetizar", sintetizar_lento)
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        # pensando, stt, emotion; o Piper fica preso na primeira frase
        assert [ws.receive_json()["type"] for _ in range(3)] == ["state", "stt", "emotion"]
        inicio = time.perf_counter()
        ws.send_json({"type": "abort"})
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}
        assert time.perf_counter() - inicio < 0.5


def test_hello_informa_o_modo_de_ativacao(cliente):
    with cliente.websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        assert ws.receive_json()["activation"] == "toque"


@pytest.fixture
def escuta_continua(monkeypatch, pipeline):
    """Servidor no modo palavra, com VAD falso e transcrições em sequência."""
    monkeypatch.setenv("PEGASUS_ATIVACAO", "palavra")
    monkeypatch.setattr(sessao_mod, "DetectorFala", _DetectorFalso)
    falas = pipeline["falas"] = []
    transcritos = pipeline["transcritos"] = []

    async def transcrever(audio, config):
        transcritos.append(len(audio) / 16_000)
        return falas.pop(0)

    monkeypatch.setattr(stt, "transcrever", transcrever)
    with TestClient(main.app) as c:
        yield c


def _conectar_continuo(ws):
    ws.send_json(_hello())
    assert ws.receive_json()["activation"] == "palavra"
    assert ws.receive_json() == {"type": "state", "state": "ocioso"}


def _nada_mais_foi_enviado(ws):
    ws.send_json({"type": "ping", "t": 7})
    assert ws.receive_json() == {"type": "pong", "t": 7}


def test_palavra_com_pergunta_responde_sem_listen_start(escuta_continua, pipeline):
    pipeline["falas"].append("Pegasus, qual é o seu nome?")
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.0)  # uma fala de 0,5 s a 1,5 s; o resto é silêncio
        recebidas = _receber_ate_estado(ws, "ouvindo")
    assert _tipos(recebidas)[:4] == ["pensando", "stt", "emotion", "falando"]
    assert recebidas[1] == {"type": "stt", "text": "qual é o seu nome?"}
    assert recebidas[-2:] == [CONVERSANDO, {"type": "state", "state": "ouvindo"}]
    assert pipeline["transcritos"] == [pytest.approx(1.5)]  # recortada com as margens
    assert pipeline["historicos"] == [[]]


def test_fala_sem_a_palavra_e_descartada_sem_rastro(escuta_continua, pipeline, caplog):
    caplog.set_level("DEBUG")
    pipeline["falas"].append("conversa particular na sala")
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.0)
        _nada_mais_foi_enviado(ws)
    assert len(pipeline["transcritos"]) == 1  # a fala foi verificada...
    assert "historicos" not in pipeline  # ...mas não chegou ao LLM
    assert "particular" not in caplog.text


def test_so_a_palavra_responde_oi_e_abre_a_escuta(escuta_continua, pipeline):
    pipeline["falas"] += ["Pegasus.", "que horas são?"]
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 2.2)  # fim decidido aos 2,1 s
        recebidas = []
        while (m := ws.receive()).get("text") is None or json.loads(m["text"]) != {
            "type": "state",
            "state": "ouvindo",
        }:
            recebidas.append(("audio", 0) if m.get("bytes") else json.loads(m["text"]))
        assert _tipos(recebidas)[:2] == ["falando", "tts_start"]
        assert recebidas[1]["text"] == "Oi?"
        assert _tipos(recebidas)[-2] == "tts_end"
        assert recebidas[-1] == CONVERSANDO
        assert "emotion" not in _tipos(recebidas)
        # a pergunta vem sem a palavra, na escuta aberta pelo "Oi?"
        _enviar_audio(ws, 3.0)
        respostas = _receber_ate_estado(ws, "ouvindo")
    assert respostas[1] == {"type": "stt", "text": "que horas são?"}
    assert pipeline["historicos"] == [[]]


def test_abort_durante_a_verificacao_descarta_a_fala(escuta_continua, pipeline, monkeypatch):
    async def transcrever_lento(audio, config):
        await asyncio.sleep(0.3)
        return "Pegasus, me ouve?"

    monkeypatch.setattr(stt, "transcrever", transcrever_lento)
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 2.2)
        ws.send_json({"type": "abort"})
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}
        time.sleep(0.4)
        _nada_mais_foi_enviado(ws)
    assert "historicos" not in pipeline


def test_modo_toque_ignora_audio_em_ocioso(cliente, pipeline, monkeypatch):
    monkeypatch.setattr(sessao_mod, "DetectorFala", _DetectorFalso)
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _enviar_audio(ws, 3.0)
        _nada_mais_foi_enviado(ws)
    assert "audio_s" not in pipeline


def test_silencio_longo_antes_da_fala_nao_acumula_audio(escuta_continua, pipeline, monkeypatch):
    monkeypatch.setattr(_DetectorFalso, "roteiro", (6.0, 7.0, 7.6))
    pipeline["falas"].append("Pegasus, oi")
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 7.7)
        assert ws.receive_json() == {"type": "state", "state": "pensando"}
    # só a fala e as margens, mesmo depois de 6 s de silêncio guardado e cortado
    assert pipeline["transcritos"] == [pytest.approx(1.5)]


def test_fala_longa_na_escuta_continua_e_descartada_sem_transcrever(
    escuta_continua, pipeline, monkeypatch
):
    monkeypatch.setattr(_DetectorFalso, "roteiro", (0.5, 12.0, 12.6))  # 11,5 s de fala
    pipeline["falas"].append("Pegasus, ruído da sala")
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 13.0)  # sem o limite, o fim seria decidido aos 12,6 s
        _nada_mais_foi_enviado(ws)
    assert pipeline["transcritos"] == []


class _DetectorRetoma(_DetectorFalso):
    """Fala de 0,5 a 1,5 s, pausa (a prévia começa aos 1,8 s), volta a falar aos 1,9 s
    até 2,5 s; o fim é decidido aos 3,1 s."""

    roteiro = (0.5, 1.5, 3.1)

    def processar(self, pcm):
        if self.terminou:
            return None
        self._amostras += len(pcm) // 2
        agora = self._amostras / 16_000
        if self.inicio is None and agora >= 0.5:
            self.inicio = 8_000
            return "inicio"
        if 1.9 <= agora < 2.5:
            self.fim = None  # voltou a falar
        elif agora >= 1.5:
            self._fim_s = 1.5 if agora < 1.9 else 2.5
            self.fim = round(self._fim_s * 16_000)
        if agora >= 3.1:
            self.terminou = True
            return "fim"
        return None


def _transcricoes(monkeypatch, texto):
    duracoes = []

    async def transcrever(audio, config):
        duracoes.append(len(audio) / 16_000)
        return texto

    monkeypatch.setattr(stt, "transcrever", transcrever)
    return duracoes


def _escutar(ws, segundos):
    ws.send_json({"type": "listen_start"})
    assert ws.receive_json()["state"] == "ouvindo"
    _enviar_audio(ws, segundos)


def test_previa_comeca_o_turno_antes_do_fim_da_fala(cliente, pipeline, monkeypatch):
    monkeypatch.setattr(sessao_mod, "DetectorFala", _DetectorFalso)
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _escutar(ws, 3.0)  # prévia aos 1,8 s (300 ms de silêncio); fim aos 2,1 s
        recebidas = _receber_ate_ocioso(ws)
    assert _tipos(recebidas)[:4] == ["pensando", "stt", "emotion", "falando"]
    [r] = _registros(pipeline)
    assert r["tipo"] == "turno" and r["fim_escuta"] == "vad"
    assert "liberado" in r["ms"]
    assert r["ms"]["vad"] == 300  # o turno conta desde a prévia, com o silêncio já passado
    assert pipeline["audio_s"] == pytest.approx(1.5)


def test_previa_desligada(monkeypatch, pipeline):
    monkeypatch.setenv("PEGASUS_VAD_PREVIA_MS", "0")
    monkeypatch.setattr(sessao_mod, "DetectorFala", _DetectorFalso)
    with TestClient(main.app) as c, c.websocket_connect("/ws") as ws:
        _conectar(ws)
        _escutar(ws, 3.0)
        _receber_ate_ocioso(ws)
    [r] = _registros(pipeline)
    assert "liberado" not in r["ms"]
    assert r["ms"]["vad"] == 600


def test_previa_e_cancelada_quando_a_pessoa_volta_a_falar(cliente, pipeline, monkeypatch):
    monkeypatch.setattr(sessao_mod, "DetectorFala", _DetectorRetoma)
    duracoes = _transcricoes(monkeypatch, "qual é o seu nome?")
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _escutar(ws, 3.5)
        recebidas = _receber_ate_ocioso(ws)
    assert _tipos(recebidas).count("stt") == 1
    assert _tipos(recebidas)[:2] == ["pensando", "stt"]
    # a resposta é da fala inteira, de 0,2 s (0,5 - 0,3) a 2,7 s (2,5 + 0,2)
    assert duracoes[-1] == pytest.approx(2.5)
    [r] = _registros(pipeline)  # a prévia cancelada não deixa registro
    assert r["tipo"] == "turno"


def test_abort_durante_a_previa_nao_envia_nada(cliente, pipeline, monkeypatch):
    monkeypatch.setattr(sessao_mod, "DetectorFala", _DetectorFalso)
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _escutar(ws, 2.0)  # a prévia começou aos 1,8 s; o fim seria aos 2,1 s
        time.sleep(0.1)
        ws.send_json({"type": "abort"})
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}
        _nada_mais_foi_enviado(ws)
    assert pipeline["turnos"].read_text() == ""


def test_previa_no_modo_palavra_cancelada_ao_voltar_a_falar(escuta_continua, pipeline, monkeypatch):
    monkeypatch.setattr(sessao_mod, "DetectorFala", _DetectorRetoma)
    duracoes = _transcricoes(monkeypatch, "Pegasus, qual é o seu nome?")
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.5)
        recebidas = _receber_ate_estado(ws, "ouvindo")
    assert _tipos(recebidas)[:3] == ["pensando", "stt", "emotion"]
    assert _tipos(recebidas).count("stt") == 1
    assert duracoes[-1] == pytest.approx(2.5)
    [r] = _registros(pipeline)
    assert r["tipo"] == "turno" and "liberado" in r["ms"]


def test_conversa_aceita_a_pergunta_seguinte_sem_o_nome(escuta_continua, pipeline):
    pipeline["falas"] += ["Pegasus, qual é o seu nome?", "e quantos anos você tem?"]
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.0)
        assert _receber_ate_estado(ws, "ouvindo")[-2] == CONVERSANDO
        _enviar_audio(ws, 3.0)  # sem "Pegasus"
        segunda = _receber_ate_estado(ws, "ouvindo")
    assert segunda[1] == {"type": "stt", "text": "e quantos anos você tem?"}
    assert segunda[-2] == CONVERSANDO  # a nova resposta renova o prazo
    assert len(pipeline["historicos"][1]) == 1  # com a memória do primeiro turno


def test_nome_no_comeco_da_fala_da_conversa_sai_da_pergunta(escuta_continua, pipeline):
    pipeline["falas"] += ["Pegasus, qual é o seu nome?", "Pegasus, e a sua idade?"]
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.0)
        _receber_ate_estado(ws, "ouvindo")
        _enviar_audio(ws, 3.0)
        segunda = _receber_ate_estado(ws, "ouvindo")
    assert segunda[1] == {"type": "stt", "text": "e a sua idade?"}


def test_conversa_sem_fala_volta_a_esperar_o_nome(escuta_continua, pipeline, monkeypatch):
    monkeypatch.setenv("PEGASUS_CONVERSA_S", "0.3")  # vence antes da fala falsa (0,5 s)
    pipeline["falas"] += ["Pegasus, qual é o seu nome?", "conversa da sala"]
    with TestClient(main.app) as c, c.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.0)
        recebidas = _receber_ate_estado(ws, "ouvindo")
        assert recebidas[-2]["timeout_ms"] == 300
        _enviar_audio(ws, 0.32)
        assert ws.receive_json() == ESPERANDO_NOME
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}
        # de volta à escuta do nome: fala sem a palavra é descartada
        _enviar_audio(ws, 3.0)
        _nada_mais_foi_enviado(ws)
    assert len(pipeline["historicos"]) == 1


def test_despedida_encerra_a_conversa_na_hora(escuta_continua, pipeline):
    pipeline["falas"] += ["Pegasus, qual é o seu nome?", "Obrigado, é só isso."]
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.0)
        _receber_ate_estado(ws, "ouvindo")
        _enviar_audio(ws, 3.0)
        recebidas = _receber_ate_ocioso(ws)
    assert recebidas[1] == {"type": "stt", "text": "Obrigado, é só isso."}
    assert recebidas[3] == {"type": "tts_start", "text": sessao_mod.DESPEDIDA, "sample_rate": TAXA}
    assert "emotion" not in _tipos(recebidas)
    assert recebidas[-2:] == [ESPERANDO_NOME, {"type": "state", "state": "ocioso"}]
    assert len(pipeline["historicos"]) == 1  # a despedida não vai ao LLM
    assert [r["tipo"] for r in _registros(pipeline)] == ["turno", "despedida"]


def test_despedida_logo_depois_do_nome(escuta_continua, pipeline):
    pipeline["falas"].append("Pegasus, tchau!")
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.0)
        recebidas = _receber_ate_ocioso(ws)
    assert _tipos(recebidas)[:3] == ["pensando", "stt", "falando"]
    assert recebidas[3]["text"] == sessao_mod.DESPEDIDA
    assert CONVERSANDO not in recebidas and ESPERANDO_NOME not in recebidas
    assert "historicos" not in pipeline


def test_modo_toque_nao_abre_conversa(cliente, pipeline):
    pipeline["transcricao"] = "tchau"
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        recebidas = _receber_ate_ocioso(ws)
    assert "conversation" not in _tipos(recebidas)
    assert len(pipeline["historicos"]) == 1  # no toque, "tchau" vai ao LLM


def test_despedida_zera_a_memoria(escuta_continua, pipeline):
    pipeline["falas"] += ["Pegasus, qual é o seu nome?", "Tchau, Pegasus.", "Pegasus, oi"]
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.0)
        _receber_ate_estado(ws, "ouvindo")
        _enviar_audio(ws, 3.0)
        _receber_ate_ocioso(ws)  # despedida
        _enviar_audio(ws, 3.0)
        _receber_ate_estado(ws, "ouvindo")
    assert pipeline["historicos"] == [[], []]  # o segundo pedido ao LLM vai sem memória


def test_memoria_zerada_depois_do_prazo_sem_conversa(monkeypatch, pipeline):
    monkeypatch.setenv("PEGASUS_MEMORIA_S", "0.3")
    with TestClient(main.app) as c, c.websocket_connect("/ws") as ws:
        _conectar(ws)
        _turno(ws, "primeira", pipeline)
        _turno(ws, "segunda", pipeline)  # dentro do prazo: lembra a primeira
        time.sleep(0.5)
        _turno(ws, "terceira", pipeline)
    assert [len(h) for h in pipeline["historicos"]] == [0, 1, 0]


def _registros(pipeline):
    linhas = pipeline["turnos"].read_text().splitlines()
    return [json.loads(linha) for linha in linhas]


def test_turno_registra_tempos_sem_texto(cliente, pipeline, caplog):
    caplog.set_level("DEBUG")
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        _receber_ate_ocioso(ws)
    [r] = _registros(pipeline)
    assert r["tipo"] == "turno"
    assert r["frases"] == 2
    assert {"stt", "primeiro_envio", "vad"} <= set(r["ms"])
    texto_do_arquivo = pipeline["turnos"].read_text()
    for trecho in ("nome", "Olá", "Pegasus"):  # fala do usuário e resposta
        assert trecho not in texto_do_arquivo
        assert trecho not in caplog.text


def test_falha_registra_a_etapa(cliente, pipeline):
    pipeline["pedacos"] = [openai.APIConnectionError(request=httpx.Request("POST", "http://x"))]
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        _receber_ate_ocioso(ws)
    [r] = _registros(pipeline)
    assert (r["tipo"], r["etapa"], r["erro"]) == ("falha", "stt", "APIConnectionError")


def test_fala_descartada_nao_entra_no_registro(escuta_continua, pipeline):
    pipeline["falas"].append("conversa particular")
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 3.0)
        _nada_mais_foi_enviado(ws)
    assert pipeline["turnos"].read_text() == ""


def test_ativacao_registra_o_oi(escuta_continua, pipeline):
    pipeline["falas"].append("Pegasus")
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        _enviar_audio(ws, 2.2)
        while (m := ws.receive()).get("text") is None or json.loads(m["text"]).get("state") != (
            "ouvindo"
        ):
            pass
    [r] = _registros(pipeline)
    assert r["tipo"] == "ativacao"
    assert r["audio_s"] == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("variavel", "modulo", "funcao"),
    [("PEGASUS_STT_LIMITE_MS", stt, "transcrever"), ("PEGASUS_TTS_LIMITE_MS", tts, "sintetizar")],
)
def test_etapa_lenta_encerra_o_turno_com_erro(monkeypatch, pipeline, variavel, modulo, funcao):
    async def lento(*args, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setenv(variavel, "100")
    monkeypatch.setattr(modulo, funcao, lento)
    with TestClient(main.app) as c, c.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        recebidas = _receber_ate_ocioso(ws)
    erros = [m for m in recebidas if isinstance(m, dict) and m["type"] == "error"]
    assert erros == [{"type": "error", "message": "O servidor demorou demais para responder."}]
    [r] = _registros(pipeline)
    assert (r["tipo"], r["erro"]) == ("falha", "TimeoutError")


def test_limite_do_turno_inteiro(monkeypatch, pipeline):
    pipeline["pedacos"] = ["Primeira frase. ", None]  # o LLM trava depois da primeira frase
    monkeypatch.setenv("PEGASUS_TURNO_LIMITE_MS", "300")
    with TestClient(main.app) as c, c.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        recebidas = _receber_ate_ocioso(ws)
    tipos = _tipos(recebidas)
    assert tipos[-3:] == ["tts_end", "error", "ocioso"]
    [r] = _registros(pipeline)
    assert r["etapa"] == "primeiro_envio"


def _esperar_estado(ws, estado):
    while (m := ws.receive()).get("text") is None or json.loads(m["text"]).get("state") != estado:
        pass


def test_llm_cai_e_volta_avisando_o_tablet(cliente, pipeline):
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        pipeline["llm_no_ar"] = False
        assert ws.receive_json() == {"type": "state", "state": "desconectado"}
        ws.send_json({"type": "listen_start"})  # sem LLM, o robô não escuta
        assert ws.receive_json() == {"type": "state", "state": "desconectado"}
        pipeline["llm_no_ar"] = True
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}
        assert _tipos(_turno(ws, "voltou?", pipeline))[-1] == "ocioso"


def test_tablet_que_conecta_com_o_llm_fora_ve_desconectado(monkeypatch, pipeline):
    pipeline["llm_no_ar"] = False
    with TestClient(main.app) as c, c.websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        assert ws.receive_json()["type"] == "hello"
        assert ws.receive_json() == {"type": "state", "state": "desconectado"}
        pipeline["llm_no_ar"] = True
        assert ws.receive_json() == {"type": "state", "state": "ocioso"}


def test_turno_que_nao_alcanca_o_llm_termina_em_desconectado(cliente, pipeline, monkeypatch):
    pipeline["pedacos"] = [openai.APIConnectionError(request=httpx.Request("POST", "http://x"))]
    monkeypatch.setattr(saude, "INTERVALO_S", 30)  # só o próprio turno descobre a queda
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        time.sleep(0.05)  # a verificação em curso termina e a próxima fica para depois
        pipeline["llm_no_ar"] = False  # caiu bem na hora do turno
        _falar(ws)
        recebidas = []
        while True:
            m = ws.receive_json()
            recebidas.append(m)
            if m.get("state") in ("desconectado", "ocioso"):
                break
        assert _tipos(recebidas) == ["pensando", "stt", "error", "desconectado"]
        ws.send_json({"type": "ping", "t": 1})  # nenhum desconectado repetido no meio
        assert ws.receive_json() == {"type": "pong", "t": 1}


def test_queda_do_llm_interrompe_a_resposta_em_andamento(cliente, pipeline):
    pipeline["pedacos"] = ["Primeira frase. ", None]
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        while (m := ws.receive()).get("text") is None or json.loads(m["text"])["type"] != "tts_end":
            pass
        pipeline["llm_no_ar"] = False
        assert ws.receive_json() == {"type": "state", "state": "desconectado"}


def test_escuta_continua_parada_com_o_llm_fora(escuta_continua, pipeline):
    pipeline["falas"].append("Pegasus, oi")
    with escuta_continua.websocket_connect("/ws") as ws:
        _conectar_continuo(ws)
        pipeline["llm_no_ar"] = False
        assert ws.receive_json() == {"type": "state", "state": "desconectado"}
        _enviar_audio(ws, 3.0)
        _nada_mais_foi_enviado(ws)
    assert pipeline["transcritos"] == []  # o áudio nem chega ao Whisper


def test_status_mostra_llm_sessoes_e_latencia(cliente, pipeline):
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        _receber_ate_ocioso(ws)
        status = cliente.get("/status").json()
    assert status["llm"]["disponivel"] is True
    assert status["sessoes"] == {"total": 1, "por_estado": {"ocioso": 1}}
    assert status["turnos"]["por_tipo"]["turno"] >= 1
    assert "tablet-teste" not in json.dumps(status)


def test_status_recusa_quem_nao_e_local(pipeline):
    with TestClient(main.app, client=("10.0.0.5", 5000)) as c:
        assert c.get("/status").status_code == 404


def _llm_em_sequencia(monkeypatch, *respostas):
    """Cada chamada ao LLM devolve a próxima lista de pedaços (a última se repete)."""
    chamadas = []

    async def gerar(texto, config, historico=()):
        chamadas.append(list(historico))
        for p in respostas[min(len(chamadas), len(respostas)) - 1]:
            yield p

    monkeypatch.setattr(llm, "gerar", gerar)
    return chamadas


def test_llm_mudo_uma_vez_repete_o_pedido(cliente, pipeline, monkeypatch):
    chamadas = _llm_em_sequencia(monkeypatch, [], ["Oito pernas."])
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        recebidas = _receber_ate_ocioso(ws)
    falas = [m["text"] for m in recebidas if isinstance(m, dict) and m["type"] == "tts_start"]
    assert falas == ["Oito pernas."]
    assert len(chamadas) == 2
    [r] = _registros(pipeline)
    assert "llm_repeticao" in r["ms"]


def test_repeticao_vai_sem_a_memoria(cliente, pipeline, monkeypatch):
    chamadas = _llm_em_sequencia(monkeypatch, ["Primeira."], [], ["Segunda."])
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _turno(ws, "um", pipeline)
        _turno(ws, "dois", pipeline)  # vem vazio com memória; repete sem ela
    assert chamadas == [[], [("um", "Primeira.")], []]


def test_llm_mudo_sempre_usa_a_fala_de_reserva(cliente, pipeline, monkeypatch):
    from app.pipeline.turno import FALA_RESERVA

    chamadas = _llm_em_sequencia(monkeypatch, [])
    with cliente.websocket_connect("/ws") as ws:
        _conectar(ws)
        _falar(ws)
        recebidas = _receber_ate_ocioso(ws)
        _turno(ws, "de novo", pipeline)
    tipos = _tipos(recebidas)
    assert tipos.index("emotion") < tipos.index("tts_start")
    falas = [m["text"] for m in recebidas if isinstance(m, dict) and m["type"] == "tts_start"]
    assert falas == [FALA_RESERVA]
    assert chamadas[-1] == []  # a fala de reserva não entra na memória
