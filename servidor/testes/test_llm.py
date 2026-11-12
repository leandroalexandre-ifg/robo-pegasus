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


def _chamada(nome, args, id_="c1"):
    funcao = NS(name=nome, arguments=args)
    tool_calls = [NS(index=0, id=id_, function=funcao)]
    return NS(choices=[NS(delta=NS(content=None, tool_calls=tool_calls))])


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


def _gerar(modo="paralelo"):
    config = carregar_config({"PEGASUS_EMOCAO_MODO": modo})

    async def coletar():
        return [x async for x in llm.gerar("oi", config)]

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


def test_modo_antes_oferece_a_ferramenta_e_pede_a_chamada_no_prompt(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_texto("Oi!")]))
    assert _gerar("antes") == ["Oi!"]
    assert pedidos[0]["tools"][0]["function"]["name"] == "definir_emocao"
    assert pedidos[0]["tool_choice"] == "auto"
    assert "definir_emocao" in pedidos[0]["messages"][0]["content"]


def test_modo_paralelo_nao_menciona_a_ferramenta_no_prompt(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_texto("Oi!")]))
    _gerar("paralelo")
    assert "definir_emocao" not in pedidos[0]["messages"][0]["content"]


def test_modo_antes_so_ferramenta_pede_a_fala_em_segunda_rodada(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_chamada("definir_emocao", '{"emocao": "triste"}', id_="abc")]))
    respostas.append(_Fluxo([_texto("Sinto "), _texto("muito.")]))
    assert _gerar("antes") == [Emocao("triste"), "Sinto ", "muito."]
    assert len(pedidos) == 2
    segunda = pedidos[1]
    assert "tools" not in segunda and "tool_choice" not in segunda
    assert segunda["messages"][-2]["tool_calls"][0]["id"] == "abc"
    assert segunda["messages"][-1] == {"role": "tool", "tool_call_id": "abc", "content": "ok"}


def test_modo_antes_texto_e_depois_ferramenta_nao_pede_segunda_rodada(cliente):
    respostas, pedidos = cliente
    fim = _chamada("definir_emocao", '{"emocao": "feliz"}')
    respostas.append(_Fluxo([_texto("Que bom!"), fim]))
    assert _gerar("antes") == ["Que bom!", Emocao("feliz")]
    assert len(pedidos) == 1


def test_modo_antes_emocao_invalida_e_ignorada(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_chamada("definir_emocao", '{"emocao": "eufórico"}')]))
    respostas.append(_Fluxo([_texto("Oi.")]))
    assert _gerar("antes") == ["Oi."]
    assert len(pedidos) == 2  # a fala ainda vem, na segunda rodada
