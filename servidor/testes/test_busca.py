import asyncio

import httpx
import pytest

from app.ferramentas import busca, rede


@pytest.fixture
def searxng():
    estado = {"corpo": {}, "pedidos": []}

    def responder(pedido):
        estado["pedidos"].append(pedido)
        return httpx.Response(200, json=estado["corpo"])

    rede.usar_transporte(httpx.MockTransport(responder))
    busca.limpar()
    yield estado
    asyncio.run(rede.fechar())
    rede.usar_transporte(None)


def _buscar(consulta, por_minuto=20):
    return asyncio.run(busca.busca_web(consulta, "http://127.0.0.1:8104", por_minuto))


def test_tres_resultados_com_dominio_e_safesearch(searxng):
    searxng["corpo"] = {
        "results": [
            {"url": f"https://www.site{i}.com.br/x", "title": f"Título {i}", "content": "Trecho."}
            for i in range(6)
        ]
    }
    r = _buscar("jogo do Flamengo")
    assert r.fonte == "uma busca na internet"
    assert r.texto.splitlines() == [
        "1. site0.com.br — Título 0. Trecho.",
        "2. site1.com.br — Título 1. Trecho.",
        "3. site2.com.br — Título 2. Trecho.",
    ]
    params = searxng["pedidos"][0].url.params
    assert params["safesearch"] == "2" and params["format"] == "json"
    assert searxng["pedidos"][0].url.host == "127.0.0.1"


def test_texto_total_limitado(searxng):
    searxng["corpo"] = {
        "results": [{"url": "https://a.b/", "title": "T" * 500, "content": "x " * 900}] * 3
    }
    r = _buscar("algo")
    assert len(r.texto) <= busca.LIMITE_TOTAL


def test_consulta_cortada_e_sem_resultados(searxng):
    r = _buscar("a " * 300)
    assert len(searxng["pedidos"][0].url.params["q"]) <= busca.LIMITE_CONSULTA
    assert r.fonte is None


def test_limite_por_minuto_e_cache(searxng):
    searxng["corpo"] = {"results": [{"url": "https://a.b/", "title": "T", "content": "c"}]}
    _buscar("um", por_minuto=2)
    _buscar("um", por_minuto=2)  # do cache: não conta
    _buscar("dois", por_minuto=2)
    with pytest.raises(busca.LimiteDeBuscas):
        _buscar("três", por_minuto=2)
    assert len(searxng["pedidos"]) == 2
