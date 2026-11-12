import asyncio

from app.pipeline.frases import cortar_frases


async def _fluxo(pedacos):
    for p in pedacos:
        yield p


def _cortar(pedacos):
    async def coletar():
        return [f async for f in cortar_frases(_fluxo(pedacos))]

    return asyncio.run(coletar())


def test_corta_em_pontuacao_final():
    assert _cortar(["Olá! Meu nome é ", "Pegasus. Tudo bem", "?"]) == [
        "Olá!",
        "Meu nome é Pegasus.",
        "Tudo bem?",
    ]


def test_frase_sai_antes_do_fim_do_fluxo():
    async def coletar():
        vistos = []
        async for frase in cortar_frases(_fluxo(["Oi. ", "Mais"])):
            vistos.append(frase)
            if len(vistos) == 1:
                return vistos
        return vistos

    assert asyncio.run(coletar()) == ["Oi."]


def test_nao_corta_numero_decimal():
    assert _cortar(["Custa 3.5 reais. Certo?"]) == ["Custa 3.5 reais.", "Certo?"]


def test_reticencias_aspas_e_quebra_de_linha():
    assert _cortar(['Hmm... Ele disse "oi." ', "Fim\nOutra linha"]) == [
        "Hmm...",
        'Ele disse "oi."',
        "Fim",
        "Outra linha",
    ]


def test_ignora_pedacos_sem_texto():
    assert _cortar(["  ", "... ", "\n"]) == []


def test_itens_que_nao_sao_texto_passam_na_hora():
    evento = object()
    assert _cortar(["Olá, tudo ", evento, "bem? Sim."]) == [evento, "Olá, tudo bem?", "Sim."]
