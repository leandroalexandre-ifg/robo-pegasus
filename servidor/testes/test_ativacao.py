import pytest

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
