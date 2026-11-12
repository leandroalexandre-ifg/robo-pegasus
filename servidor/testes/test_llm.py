import asyncio
from types import SimpleNamespace as NS

import pytest

from app.config import carregar_config
from app.pipeline import llm
from app.pipeline.emocao import Emocao


class _Fluxo:
    """Imita o AsyncStream do SDK da OpenAI e registra se foi fechado."""

    def __init__(self, pedacos):
        self._pedacos = pedacos
        self.lidos = 0
        self.fechado = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.fechado = True
        return False

    def __aiter__(self):
        return self._gerar()

    async def _gerar(self):
        for p in self._pedacos:
            self.lidos += 1
            yield p


def _texto(t):
    return NS(choices=[NS(delta=NS(content=t))])


def _resposta_ferramenta(*chamadas):
    tool_calls = [NS(function=NS(name=n, arguments=a)) for n, a in chamadas]
    return NS(choices=[NS(message=NS(content="", tool_calls=tool_calls or None))])


@pytest.fixture
def cliente(monkeypatch):
    respostas, pedidos = [], []

    async def create(**kwargs):
        pedidos.append(kwargs)
        return respostas.pop(0)

    falso = NS(chat=NS(completions=NS(create=create)))

    async def preparar(config):
        return falso, "modelo-teste"

    monkeypatch.setattr(llm, "_preparar", preparar)
    return respostas, pedidos


def _gerar():
    async def coletar():
        return [x async for x in llm.gerar("oi", carregar_config({}))]

    return asyncio.run(coletar())


def _escolher():
    return asyncio.run(llm.escolher_emocao("oi", carregar_config({})))


def test_texto_vai_sem_ferramentas(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_texto("Que "), _texto("bom!")]))
    assert _gerar() == ["Que ", "bom!"]
    assert "tools" not in pedidos[0]
    assert pedidos[0]["stream"] is True
    assert pedidos[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_imitacao_de_chamada_encerra_a_fala_e_fecha_o_fluxo(cliente):
    respostas, _ = cliente
    pedacos = [_texto("Que bom!"), _texto("\n<tool_use>"), _texto('{"name": "x"}')]
    pedacos += [_texto("resto")] * 50
    fluxo = _Fluxo(pedacos)
    respostas.append(fluxo)
    assert "".join(_gerar()) == "Que bom!\n"
    assert fluxo.fechado
    assert fluxo.lidos < len(pedacos)


def test_escolher_emocao_obriga_a_ferramenta(cliente):
    respostas, pedidos = cliente
    respostas.append(_resposta_ferramenta(("definir_emocao", '{"emocao": "triste"}')))
    assert _escolher() == Emocao("triste")
    pedido = pedidos[0]
    assert pedido["tools"][0]["function"]["name"] == "definir_emocao"
    assert pedido["tool_choice"] == {"type": "function", "function": {"name": "definir_emocao"}}
    assert "stream" not in pedido


@pytest.mark.parametrize(
    "chamadas",
    [
        (),
        (("definir_emocao", '{"emocao": "eufórico"}'),),
        (("definir_emocao", "{}"),),
        (("outra", '{"emocao": "feliz"}'),),
    ],
)
def test_escolher_emocao_sem_emocao_valida_devolve_none(cliente, chamadas):
    respostas, _ = cliente
    respostas.append(_resposta_ferramenta(*chamadas))
    assert _escolher() is None
