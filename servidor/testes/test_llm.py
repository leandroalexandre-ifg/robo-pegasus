import asyncio
from types import SimpleNamespace as NS

import pytest

from app.config import carregar_config
from app.pipeline import llm
from app.pipeline.emocao import Emocao


class _Fluxo:
    """Imita o AsyncStream do SDK da OpenAI."""

    def __init__(self, pedacos):
        self._pedacos = pedacos

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def __aiter__(self):
        return self._gerar()

    async def _gerar(self):
        for p in self._pedacos:
            yield p


def _texto(t):
    return NS(choices=[NS(delta=NS(content=t, tool_calls=None))])


def _chamada(nome, args, id_="c1"):
    funcao = NS(name=nome, arguments=args)
    return NS(
        choices=[NS(delta=NS(content=None, tool_calls=[NS(index=0, id=id_, function=funcao)]))]
    )


@pytest.fixture
def cliente(monkeypatch):
    respostas, pedidos = [], []

    async def create(**kwargs):
        pedidos.append(kwargs)
        return _Fluxo(respostas.pop(0))

    falso = NS(chat=NS(completions=NS(create=create)))

    async def preparar(config):
        return falso, "modelo-teste"

    monkeypatch.setattr(llm, "_preparar", preparar)
    return respostas, pedidos


def _gerar():
    async def coletar():
        return [x async for x in llm.gerar("oi", carregar_config({}))]

    return asyncio.run(coletar())


def test_texto_e_depois_ferramenta(cliente):
    respostas, pedidos = cliente
    respostas.append(
        [_texto("Que "), _texto("bom!"), _chamada("definir_emocao", '{"emocao": "feliz"}')]
    )
    assert _gerar() == ["Que ", "bom!", Emocao("feliz")]
    assert len(pedidos) == 1
    assert pedidos[0]["tools"][0]["function"]["name"] == "definir_emocao"
    assert pedidos[0]["tool_choice"] == "auto"
    assert pedidos[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_so_ferramenta_pede_a_fala_em_segunda_rodada(cliente):
    respostas, pedidos = cliente
    respostas.append([_chamada("definir_emocao", '{"emocao": "triste"}', id_="abc")])
    respostas.append([_texto("Sinto muito.")])
    assert _gerar() == [Emocao("triste"), "Sinto muito."]
    assert len(pedidos) == 2
    segunda = pedidos[1]
    assert "tools" not in segunda and "tool_choice" not in segunda
    assert segunda["messages"][-2]["tool_calls"][0]["id"] == "abc"
    assert segunda["messages"][-1] == {"role": "tool", "tool_call_id": "abc", "content": "ok"}


def test_emocao_invalida_e_ignorada(cliente):
    respostas, _ = cliente
    respostas.append([_texto("Oi."), _chamada("definir_emocao", '{"emocao": "eufórico"}')])
    assert _gerar() == ["Oi."]


def test_marcacao_vazada_no_texto_vira_emocao(cliente):
    respostas, pedidos = cliente
    vazada = "<tool_call>\n<function=definir_emocao>\n<parameter=emocao>\nsurpreso\n</parameter>"
    respostas.append([_texto("Uau! "), _texto(vazada), _texto("\n</function>\n</tool_call>")])
    itens = _gerar()
    assert [i for i in itens if isinstance(i, Emocao)] == [Emocao("surpreso")]
    assert "".join(i for i in itens if isinstance(i, str)).strip() == "Uau!"
    assert len(pedidos) == 1  # houve fala: não precisa de segunda rodada
