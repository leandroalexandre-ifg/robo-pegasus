import pytest

from app.pipeline.voz import extenso, ordinal, para_voz


@pytest.mark.parametrize(
    ("n", "falado"),
    [
        (0, "zero"),
        (16, "dezesseis"),
        (21, "vinte e um"),
        (100, "cem"),
        (101, "cento e um"),
        (999, "novecentos e noventa e nove"),
        (1000, "mil"),
        (1200, "mil e duzentos"),
        (1234, "mil duzentos e trinta e quatro"),
        (2026, "dois mil e vinte e seis"),
        (1_000_000, "um milhão"),
        (1_000_005, "um milhão e cinco"),
        (2_500_000, "dois milhões e quinhentos mil"),
        (1_234_000, "um milhão duzentos e trinta e quatro mil"),
        (3_000_000_000, "três bilhões"),
        (-7, "menos sete"),
    ],
)
def test_extenso(n, falado):
    assert extenso(n) == falado


def test_extenso_feminino():
    assert extenso(2, fem=True) == "duas"
    assert extenso(21, fem=True) == "vinte e uma"
    assert extenso(200, fem=True) == "duzentas"
    assert extenso(2000, fem=True) == "duas mil"
    assert extenso(2_000_000, fem=True) == "dois milhões"


def test_ordinal():
    assert ordinal(1) == "primeiro"
    assert ordinal(25) == "vigésimo quinto"
    assert ordinal(2, fem=True) == "segunda"
    assert ordinal(110) == "centésimo décimo"


@pytest.mark.parametrize(
    ("texto", "falado"),
    [
        # moeda
        ("R$ 5,32", "cinco reais e trinta e dois centavos"),
        ("R$5,3", "cinco reais e trinta centavos"),
        ("R$ 1,00", "um real"),
        ("R$ 0,50", "cinquenta centavos"),
        ("R$ 0,01", "um centavo"),
        ("R$ 1.234,56", "mil duzentos e trinta e quatro reais e cinquenta e seis centavos"),
        ("R$ 1.000.000", "um milhão de reais"),
        ("R$ 2 milhões", "dois milhões de reais"),
        ("R$ 1,5 bilhão", "um bilhão e meio de reais"),
        ("R$ 2,3 milhões", "dois vírgula três milhões de reais"),
        ("US$ 3", "três dólares"),
        ("€ 10,5", "dez euros e cinquenta centavos"),
        # porcentagem
        ("12,5%", "doze vírgula cinco por cento"),
        ("alta de 3 %", "alta de três por cento"),
        ("-3%", "menos três por cento"),
        # temperatura
        ("25°C", "vinte e cinco graus"),
        ("25 °C", "vinte e cinco graus"),
        ("25ºC", "vinte e cinco graus"),
        ("faz 25°.", "faz vinte e cinco graus."),
        ("-3°C", "menos três graus"),
        ("1°C", "um grau"),
        ("18,5°C", "dezoito vírgula cinco graus"),
        ("77°F", "setenta e sete graus Fahrenheit"),
        # horas
        ("14h30", "catorze e trinta"),
        ("14:30", "catorze e trinta"),
        ("às 8h05min", "às oito e cinco"),
        ("14:00", "catorze horas"),
        ("1h", "uma hora"),
        ("às 21h.", "às vinte e uma horas."),
        ("2 horas", "duas horas"),
        # números
        ("1.234", "mil duzentos e trinta e quatro"),
        ("3.5", "três vírgula cinco"),
        ("3,14", "três vírgula catorze"),
        ("0,05", "zero vírgula zero cinco"),
        ("o 25.º presidente", "o vigésimo quinto presidente"),
        ("a 1ª vez", "a primeira vez"),
        ("venceu por 2 a 1", "venceu por dois a um"),
        ("de 10-15 anos", "de dez a quinze anos"),
        ("200 pessoas", "duzentas pessoas"),
        ("7 vezes 8", "sete vezes oito"),
        ("13/11/2026", "treze de novembro de dois mil e vinte e seis"),
        ("1/5/26", "primeiro de maio de dois mil e vinte e seis"),
        ("1/4 do total", "um quarto do total"),
        ("Em 2026, a Espanha", "Em dois mil e vinte e seis, a Espanha"),
    ],
)
def test_para_voz(texto, falado):
    assert para_voz(texto) == falado


@pytest.mark.parametrize("texto", ["Oi! Tudo bem?", "Bem-vindo, amigo.", "Leão XIV", "x-y"])
def test_sem_numeros_o_texto_fica(texto):
    # Algarismos romanos o espeak já lê ("Leão catorze").
    assert para_voz(texto) == texto


def test_pegasus_com_a_tonica_na_primeira_silaba():
    assert para_voz("Eu sou o Pegasus.") == "Eu sou o Pégasus."
    assert para_voz("PEGASUS") == "Pégasus"
