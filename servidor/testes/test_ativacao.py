import pytest

from app.pipeline import ativacao
from app.pipeline.ativacao import e_ativacao, pergunta


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Pegasus, qual é o seu nome?", "qual é o seu nome?"),
        ("Pegasus qual é a capital do Brasil?", "qual é a capital do Brasil?"),
        ("pégasus. Me conta uma história.", "Me conta uma história."),
        ("Pégaso, tudo bem?", "tudo bem?"),
        ("Pegasos, oi", "oi"),
        ("PEGASUS! Que horas são?", "Que horas são?"),
        ("...Pegasus, você gosta de música?", "você gosta de música?"),
        ("Pegasus", ""),
        ("Pegasus.", ""),
        ("Pegasus?", ""),
        (" Pegasus! ", ""),
        ("Ei, Pegasus, qual é o seu nome?", "qual é o seu nome?"),
        ("Oi Pegasus, tudo bem?", "tudo bem?"),
        ("Oi, Pégaso. Me ajuda?", "Me ajuda?"),
        ("Hey Pegasus!", ""),
        ("Ei, Pegasus.", ""),
    ],
)
def test_reconhece_a_palavra_no_comeco(texto, esperado):
    assert pergunta(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "...",
        "Qual é o seu nome, Pegasus?",  # a palavra precisa abrir a frase
        "Oi, tudo bem?",
        "Pegas o livro pra mim?",
        "Pega sua bola.",
        "Pegamos o ônibus.",
        "Se ele pegasse o trem.",
        "Oi, tudo bem, Pegasus?",  # o chamamento não muda a regra: a palavra vem logo depois
        "Ei, ei, Pegasus",  # só um chamamento antes da palavra
        "Olá, Pegasus",  # fora da lista de chamamentos
    ],
)
def test_ignora_falas_sem_a_palavra(texto):
    assert pergunta(texto) is None


@pytest.mark.parametrize("palavra", ["Pegasus", "Pegassus", "Pegazus", "Begasus", "Pegasu"])
def test_variacoes_proximas(palavra):
    assert e_ativacao(palavra)


@pytest.mark.parametrize("palavra", ["pegas", "pega", "pegasse", "pegamos", "gás"])
def test_palavras_comuns_nao_ativam(palavra):
    assert not e_ativacao(palavra)


@pytest.mark.parametrize(
    "texto",
    [
        "Tchau, Pegasus!",
        "Obrigado, é só isso.",
        "Ok, obrigado, tchau.",
        "Tchau tchau.",
        "Até logo, Pégasus.",
        "Valeu, até mais!",
        "É só isso, obrigada.",
        "Pegasus, pode descansar.",
        "TCHAU",
    ],
)
def test_despedidas_encerram(texto):
    assert ativacao.encerra(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "Tchau, mas antes me diz uma coisa.",
        "Obrigado.",
        "Obrigado pela resposta, e o sol?",
        "Só isso mesmo?",
        "Como se diz tchau em inglês?",
        "Pegasus",
        "ok",
        "",
    ],
)
def test_outras_falas_nao_encerram(texto):
    assert not ativacao.encerra(texto)
