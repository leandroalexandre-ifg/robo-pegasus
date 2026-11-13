import asyncio

import pytest

from app import ferramentas
from app.config import carregar_config
from app.ferramentas import Consulta, busca, clima, wikipedia
from app.ferramentas.rede import Resultado


def _config(**amb):
    return carregar_config({"PEGASUS_FERRAMENTAS": "clima,wikipedia,busca_web"} | amb)


def test_citacao():
    c = [Consulta("wikipedia", True, "x", "a Wikipédia", 1)]
    assert ferramentas.citacao(c) == "Segundo a Wikipédia,"
    c.append(Consulta("clima", True, "x", "o Open-Meteo", 1))
    assert ferramentas.citacao(c) == "Segundo a Wikipédia e o Open-Meteo,"
    assert ferramentas.citacao([Consulta("clima", False, "x", None, 1)]) is None


def test_executar_passa_os_argumentos(monkeypatch):
    vistos = []

    async def falso_clima(cidade, padrao):
        vistos.append((cidade, padrao))
        return Resultado("{}", "o Open-Meteo")

    monkeypatch.setattr(clima, "clima", falso_clima)
    r = asyncio.run(ferramentas.executar([("clima", '{"cidade": 7}')], _config()))
    assert vistos == [("", "Goiânia")]  # argumento que não é texto vira vazio
    assert r[0].ok and r[0].fonte == "o Open-Meteo"


def test_argumentos_invalidos_viram_vazios(monkeypatch):
    vistos = []

    async def falsa(assunto):
        vistos.append(assunto)
        return Resultado("nada")

    monkeypatch.setattr(wikipedia, "wikipedia", falsa)
    asyncio.run(ferramentas.executar([("wikipedia", "não é json")], _config()))
    assert vistos == [""]


def test_limite_de_tempo_da_ferramenta(monkeypatch):
    async def lenta(assunto):
        await asyncio.sleep(5)

    monkeypatch.setattr(wikipedia, "wikipedia", lenta)
    r = asyncio.run(
        ferramentas.executar([("wikipedia", "{}")], _config(PEGASUS_WIKIPEDIA_LIMITE_MS="50"))
    )
    assert not r[0].ok and r[0].fonte is None and "erro" in r[0].texto
    assert r[0].ms < 1000


def test_limite_da_fase_inteira(monkeypatch):
    async def lenta(*_):
        await asyncio.sleep(5)

    monkeypatch.setattr(busca, "busca_web", lenta)
    monkeypatch.setattr(clima, "clima", lenta)
    config = _config(PEGASUS_FERRAMENTAS_LIMITE_MS="50")
    r = asyncio.run(ferramentas.executar([("busca_web", "{}"), ("clima", "{}")], config))
    assert [c.ok for c in r] == [False, False]


def test_no_maximo_duas_chamadas(monkeypatch):
    async def rapida(assunto):
        return Resultado("ok", "a Wikipédia")

    monkeypatch.setattr(wikipedia, "wikipedia", rapida)
    r = asyncio.run(ferramentas.executar([("wikipedia", "{}")] * 5, _config()))
    assert len(r) == ferramentas.MAX_CHAMADAS


def test_limite_de_buscas_vira_erro(monkeypatch):
    async def cheia(*_):
        raise busca.LimiteDeBuscas

    monkeypatch.setattr(busca, "busca_web", cheia)
    r = asyncio.run(ferramentas.executar([("busca_web", '{"consulta": "x"}')], _config()))
    assert not r[0].ok


@pytest.mark.parametrize("lista", ["", "data_hora"])
def test_sem_ferramentas_de_rede(lista):
    config = carregar_config({"PEGASUS_FERRAMENTAS": lista})
    assert ferramentas.definicoes(config) == []
    assert ferramentas.ativas_de_rede(config) == ()
