import asyncio

import pytest

from app.pipeline.emocao import (
    EMOCOES,
    FERRAMENTA,
    Emocao,
    emocao_da_chamada,
    limpar_para_voz,
    separar_marcacoes,
)


def test_ferramenta_lista_as_emocoes():
    propriedade = FERRAMENTA["function"]["parameters"]["properties"]["emocao"]
    assert propriedade["enum"] == list(EMOCOES)
    assert FERRAMENTA["function"]["name"] == "definir_emocao"


@pytest.mark.parametrize(
    ("nome", "argumentos", "esperado"),
    [
        ("definir_emocao", '{"emocao": "feliz"}', Emocao("feliz")),
        ("definir_emocao", '{"emocao": " Triste "}', Emocao("triste")),
        ("definir_emocao", '{"emocao": "eufórico"}', None),
        ("definir_emocao", "não é json", None),
        ("definir_emocao", "[]", None),
        ("outra_ferramenta", '{"emocao": "feliz"}', None),
    ],
)
def test_emocao_da_chamada(nome, argumentos, esperado):
    assert emocao_da_chamada(nome, argumentos) == esperado


def _separar(pedacos):
    async def fluxo():
        for p in pedacos:
            yield p

    async def coletar():
        return [x async for x in separar_marcacoes(fluxo())]

    itens = asyncio.run(coletar())
    return "".join(x for x in itens if isinstance(x, str)), [
        x for x in itens if not isinstance(x, str)
    ]


def test_texto_sem_marcacao_passa_inteiro():
    assert _separar(["Olá! ", "Tudo bem?"]) == ("Olá! Tudo bem?", [])


def test_chamada_xml_vazada_vira_emocao():
    xml = (
        "<tool_call>\n<function=definir_emocao>\n<parameter=emocao>\nfeliz\n"
        "</parameter>\n</function>\n</tool_call>"
    )
    pedacos = ["Que legal!", " <tool", "_call>"] + [xml[11:20], xml[20:]] + [" Parabéns."]
    assert _separar(pedacos) == ("Que legal!  Parabéns.", [Emocao("feliz")])


def test_chamada_json_vazada_vira_emocao():
    bloco = '<tool_call>{"name": "definir_emocao", "arguments": {"emocao": "triste"}}</tool_call>'
    assert _separar(["Sinto muito. ", bloco]) == ("Sinto muito. ", [Emocao("triste")])


def test_menor_que_comum_nao_e_retido():
    assert _separar(["3 < 5 ", "é verdade."]) == ("3 < 5 é verdade.", [])


def test_bloco_sem_fechamento_no_fim_e_descartado():
    assert _separar(["Oi. <tool_call><parameter=emocao>bravo"]) == ("Oi. ", [Emocao("bravo")])


@pytest.mark.parametrize(
    ("texto", "limpo"),
    [
        ("Olá! Meu nome é Pegasus.", "Olá! Meu nome é Pegasus."),
        ("[feliz] Que notícia boa!", "Que notícia boa!"),
        ("Que pena (triste).", "Que pena."),
        ("(emoção: surpreso) Uau!", "Uau!"),
        ("*sorri* Oi, tudo bem?", "Oi, tudo bem?"),
        ("Que legal! 😄🎉", "Que legal!"),
        ("**Sete** vezes oito é `56`.", "Sete vezes oito é 56."),
        ("Oi <tool_call><function=definir_emocao></tool_call>", "Oi"),
        ("Fico <b>feliz</b> em ajudar.", "Fico feliz em ajudar."),
        ("Estou feliz por você.", "Estou feliz por você."),
    ],
)
def test_limpar_para_voz(texto, limpo):
    assert limpar_para_voz(texto) == limpo
