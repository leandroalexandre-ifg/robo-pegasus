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


def test_historico_entra_antes_da_fala_atual(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_texto("Leandro.")]))
    config = carregar_config({"PEGASUS_EMOCAO_MODO": "paralelo"})
    historico = [("Meu nome é Leandro.", "Prazer, Leandro!"), ("Tudo bem?", "Tudo ótimo.")]

    async def coletar():
        return [x async for x in llm.gerar("Qual é o meu nome?", config, historico)]

    asyncio.run(coletar())
    papeis = [(m["role"], m["content"]) for m in pedidos[0]["messages"][1:]]
    assert papeis == [
        ("user", "Meu nome é Leandro."),
        ("assistant", "Prazer, Leandro!"),
        ("user", "Tudo bem?"),
        ("assistant", "Tudo ótimo."),
        ("user", "Qual é o meu nome?"),
    ]


def test_escolher_emocao_tambem_ve_o_historico(cliente):
    respostas, pedidos = cliente
    respostas.append(_resposta_ferramenta(("definir_emocao", '{"emocao": "feliz"}')))
    historico = [("Ganhei!", "Parabéns!")]
    asyncio.run(llm.escolher_emocao("De novo!", carregar_config({}), historico))
    assert [m["content"] for m in pedidos[0]["messages"][1:]] == [
        "Ganhei!",
        "Parabéns!",
        "De novo!",
    ]


def test_cliente_sem_novas_tentativas_e_com_limite(monkeypatch):
    monkeypatch.setattr(llm, "_cliente", None)
    monkeypatch.setattr(llm, "_modelo", None)
    config = carregar_config({"PEGASUS_MODELO": "m", "PEGASUS_LLM_LIMITE_MS": "7000"})
    cliente, _ = asyncio.run(llm._preparar(config))
    assert cliente.max_retries == 0
    assert cliente.timeout.read == 7.0
    assert cliente.timeout.connect == llm.LIMITE_CONEXAO_S


# Ferramentas de rede


def _gerar_com(
    ferramentas="clima,wikipedia,busca_web", modo="paralelo", fala="Quem foi Santos Dumont?"
):
    config = carregar_config({"PEGASUS_EMOCAO_MODO": modo, "PEGASUS_FERRAMENTAS": ferramentas})

    async def coletar():
        return [x async for x in llm.gerar(fala, config)]

    return asyncio.run(coletar())


@pytest.fixture
def consultas(monkeypatch):
    from app import ferramentas

    feitas, respostas = [], []

    async def executar(chamadas, config):
        feitas.append(chamadas)
        return respostas.pop(0)

    monkeypatch.setattr(ferramentas, "executar", executar)
    return feitas, respostas


def _consulta(nome="wikipedia", ok=True, fonte="a Wikipédia", texto="Verbete X: dados."):
    from app.ferramentas import Consulta

    return Consulta(nome, ok, texto, fonte if ok else None, 300)


def test_ferramentas_oferecidas_e_prompt(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_texto("Oi!")]))
    assert _gerar_com() == ["Oi!"]
    nomes = [t["function"]["name"] for t in pedidos[0]["tools"]]
    assert nomes == ["clima", "wikipedia", "busca_web"]
    assert "ferramentas" in pedidos[0]["messages"][0]["content"]


def test_so_data_hora_nao_oferece_ferramentas(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_texto("Oi!")]))
    _gerar_com("data_hora")
    assert "tools" not in pedidos[0]


def test_chamada_de_rede_espera_consulta_e_cita_a_fonte(cliente, consultas):
    from app.ferramentas import Consulta, Espera

    respostas, pedidos = cliente
    feitas, resultados = consultas
    resultados.append([_consulta()])
    respostas.append(_Fluxo([_chamada("wikipedia", '{"assunto": "Santos Dumont"}', id_="w1")]))
    respostas.append(_Fluxo([_texto(" ele foi"), _texto(" um inventor.")]))
    itens = _gerar_com()
    assert itens[0] == Espera("wikipedia")
    assert isinstance(itens[1], Consulta)
    assert itens[2:] == ["Segundo a Wikipédia,", " ele foi", " um inventor."]
    assert feitas == [[("wikipedia", '{"assunto": "Santos Dumont"}')]]
    segunda = pedidos[1]
    assert "tools" not in segunda
    assert segunda["extra_body"]["continue_final_message"] is True
    assert segunda["extra_body"]["add_generation_prompt"] is False
    assert segunda["messages"][-1] == {"role": "assistant", "content": "Segundo a Wikipédia,"}
    assert segunda["messages"][-2]["role"] == "tool"
    assert segunda["messages"][-2]["tool_call_id"] == "w1"


def test_citacao_ganha_espaco_quando_a_continuacao_nao_tem(cliente, consultas):
    respostas, _ = cliente
    consultas[1].append([_consulta()])
    respostas.append(_Fluxo([_chamada("wikipedia", '{"assunto": "x"}')]))
    respostas.append(_Fluxo([_texto("ele foi.")]))
    textos = [x for x in _gerar_com() if isinstance(x, str)]
    assert "".join(textos) == "Segundo a Wikipédia, ele foi."


def test_continuacao_vazia_repete_sem_citacao(cliente, consultas):
    respostas, pedidos = cliente
    consultas[1].append([_consulta()])
    respostas.append(_Fluxo([_chamada("wikipedia", '{"assunto": "x"}')]))
    respostas.append(_Fluxo([]))
    respostas.append(_Fluxo([_texto("Ele foi um inventor.")]))
    textos = [x for x in _gerar_com() if isinstance(x, str)]
    assert textos == ["Ele foi um inventor."]
    assert "continue_final_message" not in pedidos[2]["extra_body"]
    assert pedidos[2]["messages"][-1]["role"] == "tool"


def test_falha_na_consulta_nao_cita(cliente, consultas):
    respostas, pedidos = cliente
    consultas[1].append([_consulta(ok=False, texto='{"erro": "consulta indisponível agora"}')])
    respostas.append(_Fluxo([_chamada("clima", "{}")]))
    respostas.append(_Fluxo([_texto("Não consegui ver o tempo agora.")]))
    textos = [x for x in _gerar_com() if isinstance(x, str)]
    assert textos == ["Não consegui ver o tempo agora."]
    assert "continue_final_message" not in pedidos[1]["extra_body"]


def test_ferramenta_desligada_nao_e_executada(cliente, consultas):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_chamada("busca_web", '{"consulta": "x"}')]))
    respostas.append(_Fluxo([_texto("Não consigo buscar isso.")]))
    itens = _gerar_com("clima")
    assert itens == ["Não consigo buscar isso."]  # sem Espera nem Consulta
    assert consultas[0] == []
    assert pedidos[1]["messages"][-1]["content"] == '{"erro": "ferramenta indisponível"}'
    assert "tools" not in pedidos[1]


def test_modo_antes_emocao_e_consulta_na_mesma_rodada(cliente, consultas):
    from app.ferramentas import Espera

    respostas, pedidos = cliente
    consultas[1].append([_consulta("clima", fonte="a previsão do tempo")])
    chamadas = [
        NS(index=0, id="e", function=NS(name="definir_emocao", arguments='{"emocao": "feliz"}')),
        NS(index=1, id="c", function=NS(name="clima", arguments="{}")),
    ]
    respostas.append(_Fluxo([NS(choices=[NS(delta=NS(content=None, tool_calls=chamadas))])]))
    respostas.append(_Fluxo([_texto(" faz sol.")]))
    itens = _gerar_com(modo="antes")
    assert Espera("clima") in itens and Emocao("feliz") in itens
    assert [x for x in itens if isinstance(x, str)] == ["Segundo a previsão do tempo,", " faz sol."]
    ferramentas = [m for m in pedidos[1]["messages"] if m["role"] == "tool"]
    assert [m["content"] for m in ferramentas] == ["ok", "Verbete X: dados."]


def test_texto_antes_da_chamada_de_rede_volta_ao_modelo(cliente, consultas):
    respostas, pedidos = cliente
    consultas[1].append([_consulta("busca_web", fonte="uma busca na internet")])
    respostas.append(_Fluxo([_texto("Vou verificar."), _chamada("busca_web", "{}")]))
    respostas.append(_Fluxo([_texto(" foi 2 a 1.")]))
    itens = _gerar_com()
    assert [x for x in itens if isinstance(x, str)] == [
        "Vou verificar.",
        "Segundo uma busca na internet,",
        " foi 2 a 1.",
    ]
    chamada = pedidos[1]["messages"][-3]
    assert chamada["content"] == "Vou verificar." and chamada["tool_calls"]


def test_pergunta_recente_obriga_a_busca(cliente, consultas):
    respostas, pedidos = cliente
    consultas[1].append([_consulta("busca_web", fonte="uma busca na internet")])
    respostas.append(_Fluxo([_chamada("busca_web", '{"consulta": "presidente da França"}')]))
    respostas.append(_Fluxo([_texto(" é Fulano.")]))
    _gerar_com(fala="Quem é o atual presidente da França?")
    assert pedidos[0]["tool_choice"] == {"type": "function", "function": {"name": "busca_web"}}
    assert [t["function"]["name"] for t in pedidos[0]["tools"]] == [
        "clima",
        "wikipedia",
        "busca_web",
    ]
    assert "tools" not in pedidos[1]


def test_pergunta_sem_termo_de_atualidade_deixa_a_escolha(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_texto("Oi!")]))
    _gerar_com(fala="Me conta uma piada.")
    assert pedidos[0]["tool_choice"] == "auto"


def test_sem_busca_ligada_nao_obriga(cliente):
    respostas, pedidos = cliente
    respostas.append(_Fluxo([_texto("Oi!")]))
    _gerar_com("clima,wikipedia", fala="Quem é o atual presidente da França?")
    assert pedidos[0]["tool_choice"] == "auto"
