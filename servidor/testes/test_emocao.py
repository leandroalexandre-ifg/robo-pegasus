import asyncio

import pytest

from app.pipeline.emocao import (
    EMOCOES,
    FERRAMENTA,
    Emocao,
    cortar_marcacoes,
    emocao_da_chamada,
    limpar_para_voz,
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


def _cortar(pedacos):
    consumidos = []

    async def fluxo():
        for p in pedacos:
            consumidos.append(p)
            yield p

    async def coletar():
        return "".join([x async for x in cortar_marcacoes(fluxo())])

    return asyncio.run(coletar()), len(consumidos)


def test_texto_sem_marcacao_passa_inteiro():
    assert _cortar(["Olá! ", "Tudo bem?"]) == ("Olá! Tudo bem?", 2)


@pytest.mark.parametrize(
    "imitacao",
    [
        '<tool_use>\n{"name": "definir_emocao", "arguments": {"emocao": "feliz"}}\n</tool_use>',
        "<tool_call>\n<function=definir_emocao>\n<parameter=emocao>\nfeliz\n</parameter>",
        "definir_emocao(feliz)",
        "Definir_emoção: feliz",
        '{"emocao": "feliz"}',
        '{\n  "name": "definir_emocao"\n}',
    ],
)
def test_corta_imitacao_de_chamada_e_para_de_ler(imitacao):
    pedacos = ["Que notícia boa!", "\n"] + [imitacao[i : i + 3] for i in range(0, len(imitacao), 3)]
    pedacos += ["Isto nunca é lido."]
    texto, consumidos = _cortar(pedacos)
    assert texto == "Que notícia boa!\n"
    assert consumidos < len(pedacos)  # o fluxo do LLM é abandonado


def test_menor_que_e_chave_comuns_passam():
    assert _cortar(["3 < 5 ", "é verdade, {ok}."])[0] == "3 < 5 é verdade, {ok}."


def test_palavra_parecida_com_marcador_passa():
    assert _cortar(["Vamos def", "inir um plano."])[0] == "Vamos definir um plano."


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
        ("Oi! definir_emocao(feliz)", "Oi!"),
        ('Oi! {"emocao": "feliz"}', "Oi!"),
        ("Estou feliz por você.", "Estou feliz por você."),
    ],
)
def test_limpar_para_voz(texto, limpo):
    assert limpar_para_voz(texto) == limpo
