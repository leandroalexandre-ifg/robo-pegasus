import pytest

from app.ferramentas.atualidade import pede_busca
from scripts.medir_ferramentas import PERGUNTAS

# As 10 perguntas de fatos recentes do teste da escolha da ferramenta.
RECENTES = [
    "Quem ganhou a última Copa do Mundo de futebol?",
    "Qual é a cotação do dólar hoje?",
    "Quem é o atual presidente da França?",
    "Qual foi o resultado do último jogo do Flamengo?",
    "Quem é o atual governador de Goiás?",
    "Quanto está o preço da gasolina hoje?",
    "Quem ganhou o último Oscar de melhor filme?",
    "Quem é o atual campeão da Fórmula 1?",
    "Qual é o atual papa da Igreja Católica?",
    "Quais são as notícias de hoje no Brasil?",
]


@pytest.mark.parametrize(
    "fala",
    RECENTES
    + [
        "qual foi o placar do jogo?",
        "quem é a ministra da saúde?",
        "o que aconteceu agora em Brasília",
        "Me conta uma notícia boa.",
        "quais os preços do feijão",
        "Atualmente quem manda no Senado?",
    ],
)
def test_termos_de_atualidade_pedem_busca(fala):
    assert pede_busca(fala)


@pytest.mark.parametrize(
    "fala",
    PERGUNTAS["conversa"]
    + PERGUNTAS["data_hora"]
    + PERGUNTAS["clima"]
    + PERGUNTAS["wikipedia"]
    + [
        "que horas são agora?",
        "hoje é que dia?",
        "qual a temperatura atual?",
        "vai chover hoje?",
        "como você está hoje?",
        "o que eu falei por último?",
        "me conta uma piada agora",
        "conta uma história agora",
        "qual o resultado de sete vezes oito?",
        "quanto é 3 x 4 agora?",
        "quem é você?",
    ],
)
def test_conversa_hora_clima_e_contas_nao_pedem(fala):
    assert not pede_busca(fala)
