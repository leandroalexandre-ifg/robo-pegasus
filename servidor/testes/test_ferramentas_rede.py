import asyncio
import json

import httpx
import pytest

from app.ferramentas import clima, rede, wikipedia


@pytest.fixture
def servidor():
    """Troca a internet por respostas fixas e registra os pedidos."""
    respostas: dict[str, object] = {}
    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        corpo = respostas.get(pedido.url.host)
        if isinstance(corpo, int):
            return httpx.Response(corpo)
        return httpx.Response(200, json=corpo)

    rede.usar_transporte(httpx.MockTransport(responder))
    clima.limpar_cache()
    wikipedia.limpar_cache()
    yield respostas, pedidos
    asyncio.run(rede.fechar())
    rede.usar_transporte(None)


GOIANIA = {
    "results": [
        {
            "name": "Goiânia",
            "admin1": "Goiás",
            "country": "Brasil",
            "latitude": -16.7,
            "longitude": -49.3,
            "population": 1_500_000,
        },
        {
            "name": "Goiânia",
            "admin1": "Outro",
            "country": "Brasil",
            "latitude": 1,
            "longitude": 1,
            "population": 10,
        },
    ]
}
PREVISAO = {
    "current": {
        "temperature_2m": 26.4,
        "apparent_temperature": 29.6,
        "relative_humidity_2m": 69,
        "weather_code": 0,
        "wind_speed_10m": 5.2,
    },
    "daily": {
        "weather_code": [80, 95, 3],
        "temperature_2m_max": [28.2, 30, 31],
        "temperature_2m_min": [19, 20.4, 21],
        "precipitation_probability_max": [96, 80, 10],
    },
}


def _rodar(coro):
    return asyncio.run(coro)


def test_clima_cidade_padrao_mais_populosa_e_em_palavras(servidor):
    respostas, pedidos = servidor
    respostas["geocoding-api.open-meteo.com"] = GOIANIA
    respostas["api.open-meteo.com"] = PREVISAO
    r = _rodar(clima.clima(None, "Goiânia"))
    assert r.fonte == "o Open-Meteo"
    dados = json.loads(r.texto)
    assert dados["cidade"] == "Goiânia, Goiás, Brasil"
    assert dados["agora"]["temperatura"] == "26 graus"
    assert dados["agora"]["tempo"] == "céu limpo"
    assert dados["previsao"][1] == {
        "dia": "amanhã",
        "tempo": "trovoadas",
        "minima": "20 graus",
        "maxima": "30 graus",
        "chance_de_chuva": "80 por cento",
    }
    assert pedidos[1].url.params["latitude"] == "-16.7"
    assert pedidos[0].headers["user-agent"].startswith("RoboPegasus/0.1 (+https://github.com/")
    assert "@" not in pedidos[0].headers["user-agent"]


def test_clima_usa_o_cache(servidor):
    respostas, pedidos = servidor
    respostas["geocoding-api.open-meteo.com"] = GOIANIA
    respostas["api.open-meteo.com"] = PREVISAO
    _rodar(clima.clima("Goiânia", "Goiânia"))
    _rodar(clima.clima("goiânia", "Goiânia"))
    assert len(pedidos) == 2


def test_clima_cidade_desconhecida_sem_fonte(servidor):
    respostas, _ = servidor
    respostas["geocoding-api.open-meteo.com"] = {}
    r = _rodar(clima.clima("Xyzzy", "Goiânia"))
    assert r.fonte is None and "não encontrada" in r.texto


def test_clima_erro_http_vira_excecao(servidor):
    respostas, _ = servidor
    respostas["geocoding-api.open-meteo.com"] = 503
    with pytest.raises(httpx.HTTPStatusError):
        _rodar(clima.clima("Goiânia", "Goiânia"))


def test_wikipedia_corta_na_frase_e_cita(servidor):
    respostas, pedidos = servidor
    frase = "Santos Dumont foi um inventor brasileiro. "
    respostas["pt.wikipedia.org"] = {
        "query": {"pages": [{"title": "Santos Dumont", "extract": frase * 40}]}
    }
    r = _rodar(wikipedia.wikipedia("Santos Dumont"))
    assert r.fonte == "a Wikipédia"
    assert r.texto.startswith("Verbete Santos Dumont: Santos Dumont foi")
    assert r.texto.endswith("brasileiro.")
    assert len(r.texto) <= len("Verbete Santos Dumont: ") + wikipedia.LIMITE_CARACTERES
    assert pedidos[0].url.params["gsrsearch"] == "Santos Dumont"


def test_wikipedia_nada_encontrado(servidor):
    respostas, _ = servidor
    respostas["pt.wikipedia.org"] = {"batchcomplete": True}
    r = _rodar(wikipedia.wikipedia("qwxz"))
    assert r.fonte is None


def test_wikipedia_assunto_cortado_em_100(servidor):
    respostas, pedidos = servidor
    respostas["pt.wikipedia.org"] = {}
    _rodar(wikipedia.wikipedia("a" * 500))
    assert len(pedidos[0].url.params["gsrsearch"]) == 100


def test_redirecionamento_nao_e_seguido(servidor):
    def responder(pedido):
        return httpx.Response(302, headers={"Location": "http://127.0.0.1:8100/status"})

    rede.usar_transporte(httpx.MockTransport(responder))
    with pytest.raises(httpx.HTTPStatusError):
        _rodar(wikipedia.wikipedia("x"))


def test_cortar_sem_frase_corta_na_palavra():
    assert wikipedia.cortar("palavra " * 100, 30) == "palavra palavra palavra…"
