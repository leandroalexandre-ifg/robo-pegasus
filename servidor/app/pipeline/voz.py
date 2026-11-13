"""Texto → forma falada, antes do Piper: moeda, porcentagem, temperatura, horas, datas,
ordinais e números por extenso.

O espeak (fonemizador do Piper) lê "R$ 5,32" como "erre cifrão cinco vírgula trinta e
dois", "25°C" como "vinte e cinco grau C", "14h30" como "catorze agá trinta", "3.5"
como "três cinco", "25.º" como "vinte e cinco ordinal masculino" e "2 horas" como
"dois horas". Só a voz usa este texto: o que vai ao tablet e à memória fica como o
LLM escreveu."""

import re
from collections.abc import Callable

_UNIDADES = (
    "zero um dois três quatro cinco seis sete oito nove dez onze doze treze catorze "
    "quinze dezesseis dezessete dezoito dezenove"
).split()
_DEZENAS = "_ _ vinte trinta quarenta cinquenta sessenta setenta oitenta noventa".split()
_CENTENAS = (
    "_ cento duzentos trezentos quatrocentos quinhentos seiscentos setecentos oitocentos novecentos"
).split()
_ESCALAS = (
    (10**12, "trilhão", "trilhões"),
    (10**9, "bilhão", "bilhões"),
    (10**6, "milhão", "milhões"),
    (10**3, "mil", "mil"),
)
_MESES = (
    "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro"
).split()

_ORD_UN = "_ primeiro segundo terceiro quarto quinto sexto sétimo oitavo nono".split()
_ORD_DEZ = (
    "_ décimo vigésimo trigésimo quadragésimo quinquagésimo sexagésimo septuagésimo "
    "octogésimo nonagésimo"
).split()
_ORD_CEN = (
    "_ centésimo ducentésimo trecentésimo quadringentésimo quingentésimo sexcentésimo "
    "septingentésimo octingentésimo noningentésimo"
).split()

# Palavras femininas comuns depois de um número: "2 horas" → "duas horas".
_FEMININOS = frozenset(
    "hora horas pessoa pessoas vez vezes semana semanas criança crianças casa casas "
    "mulher mulheres menina meninas cidade cidades página páginas letra letras "
    "tonelada toneladas".split()
)

_MOEDAS = {
    "R$": ("real", "reais"),
    "US$": ("dólar", "dólares"),
    "U$": ("dólar", "dólares"),
    "$": ("dólar", "dólares"),
    "€": ("euro", "euros"),
}

# Um número escrito com algarismos: "1.234,56", "1.234", "3,5", "3.5", "42".
_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
# Sinal de menos só no começo ou depois de espaço ou parêntese: "-3°C", não "10-15".
_SINAL = r"(?:(?<![\w.,])-)?"


def _feminino(palavra: str) -> str:
    if palavra == "um":
        return "uma"
    if palavra == "dois":
        return "duas"
    return palavra[:-2] + "as" if palavra.endswith("entos") else palavra


def _ate_mil(n: int, fem: bool) -> str:
    """0 < n < 1000."""
    if n == 100:
        return "cem"
    centena, resto = divmod(n, 100)
    partes = []
    if centena:
        partes.append(_CENTENAS[centena])
    if resto >= 20:
        dezena, unidade = divmod(resto, 10)
        partes.append(_DEZENAS[dezena])
        if unidade:
            partes.append(_UNIDADES[unidade])
    elif resto:
        partes.append(_UNIDADES[resto])
    if fem:
        partes = [_feminino(p) for p in partes]
    return " e ".join(partes)


def extenso(n: int, fem: bool = False) -> str:
    """Inteiro por extenso: 2026 → "dois mil e vinte e seis"; fem: 2 → "duas"."""
    if n < 0:
        return f"menos {extenso(-n, fem)}"
    if n == 0:
        return "zero"
    grupos: list[tuple[int, str]] = []  # (valor do grupo, palavras)
    resto = n
    for valor, singular, plural in _ESCALAS:
        quantos, resto = divmod(resto, valor)
        if not quantos:
            continue
        if valor == 1000:
            grupos.append((quantos, "mil" if quantos == 1 else f"{extenso(quantos, fem)} mil"))
        else:
            grupos.append((quantos, f"{extenso(quantos)} {singular if quantos == 1 else plural}"))
    if resto:
        grupos.append((resto, _ate_mil(resto, fem)))
    texto = grupos[0][1]
    for i, (valor, palavras) in enumerate(grupos[1:], 1):
        # "mil e duzentos", "um milhão e quinhentos mil"; mas "mil duzentos e trinta".
        redondo = valor < 100 or valor % 100 == 0
        texto += f" e {palavras}" if i == len(grupos) - 1 and redondo else f" {palavras}"
    return texto


def ordinal(n: int, fem: bool = False) -> str:
    """1 → "primeiro", 25 → "vigésimo quinto"; acima de 999, o cardinal."""
    if not 0 < n < 1000:
        return extenso(n, fem)
    centena, resto = divmod(n, 100)
    dezena, unidade = divmod(resto, 10)
    partes = [p for p in (_ORD_CEN[centena], _ORD_DEZ[dezena], _ORD_UN[unidade]) if p != "_"]
    if fem:
        partes = [p[:-1] + "a" for p in partes]
    return " ".join(partes)


def _valor(texto: str) -> tuple[int, str]:
    """ "1.234,56" → (1234, "56"); "3.5" → (3, "5"); "1.000" → (1000, "")."""
    if "," in texto:
        inteiro, _, decimais = texto.partition(",")
        return int(inteiro.replace(".", "")), decimais
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", texto):
        return int(texto.replace(".", "")), ""
    inteiro, _, decimais = texto.partition(".")
    return int(inteiro), decimais


def _decimais(decimais: str) -> str:
    """Parte depois da vírgula: "5" → "cinco", "05" → "zero cinco", "14" → "catorze"."""
    zeros = len(decimais) - len(decimais.lstrip("0"))
    resto = decimais.lstrip("0")
    palavras = ["zero"] * zeros
    if resto:
        if len(resto) <= 3:
            palavras.append(extenso(int(resto)))
        else:
            palavras += [_UNIDADES[int(d)] for d in resto]
    return " ".join(palavras)


def numero(texto: str, fem: bool = False) -> str:
    """Um número escrito ("-1.234,5") por extenso."""
    negativo = texto.startswith("-")
    inteiro, decimais = _valor(texto.lstrip("-"))
    falado = extenso(inteiro, fem and not decimais)
    if decimais:
        falado += f" vírgula {_decimais(decimais)}"
    return f"menos {falado}" if negativo else falado


def _dinheiro(m: re.Match) -> str:
    singular, plural = _MOEDAS[m["moeda"]]
    escala = m["escala"]
    if escala:
        # "R$ 2 milhões" → "dois milhões de reais"; "R$ 1,5 bilhão" → "um bilhão e meio".
        inteiro, decimais = _valor(m["valor"])
        if decimais == "5":
            quantia = f"{extenso(inteiro)} {escala} e meio"
        else:
            quantia = f"{numero(m['valor'])} {escala}"
        return f"{quantia} de {plural}"
    inteiro, decimais = _valor(m["valor"])
    centavos = int((decimais + "00")[:2]) if decimais else 0
    partes = []
    if inteiro or not centavos:
        moeda = singular if inteiro == 1 else plural
        de = "de " if inteiro >= 10**6 and inteiro % 10**6 == 0 else ""
        partes.append(f"{extenso(inteiro)} {de}{moeda}")
    if centavos:
        partes.append(f"{extenso(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
    falado = " e ".join(partes)
    return f"menos {falado}" if m["sinal"] else falado


def _temperatura(m: re.Match) -> str:
    inteiro, decimais = _valor(m["valor"].lstrip("-"))
    unidade = "grau" if inteiro == 1 and not decimais else "graus"
    escala = m["escala"] or m["escala2"]
    if escala and escala.upper() == "F":
        unidade += " Fahrenheit"
    return f"{numero(m['valor'])} {unidade}"


def _horas(m: re.Match) -> str:
    hora, minutos = int(m["hora"]), int(m["min"] or m["min2"] or 0)
    if minutos:
        return f"{extenso(hora, fem=True)} e {extenso(minutos)}"
    return f"{extenso(hora, fem=True)} {'hora' if hora == 1 else 'horas'}"


def _data(m: re.Match) -> str:
    dia, mes, ano = int(m["dia"]), int(m["mes"]), m["ano"]
    if not (1 <= dia <= 31 and 1 <= mes <= 12):
        return m[0]
    falado = f"{'primeiro' if dia == 1 else extenso(dia)} de {_MESES[mes - 1]}"
    if ano:
        ano_n = int(ano)
        if len(ano) == 2:
            ano_n += 2000
        falado += f" de {extenso(ano_n)}"
    return falado


_FRACOES = {(1, 2): "meio", (1, 3): "um terço", (2, 3): "dois terços", (1, 4): "um quarto"}
_FRACOES[(3, 4)] = "três quartos"


def _numero_solto(m: re.Match) -> str:
    seguinte = m["seguinte"] or ""
    fem = seguinte.strip().casefold() in _FEMININOS
    return numero(m["valor"], fem) + seguinte


_SUBSTITUICOES: list[tuple[re.Pattern, Callable[[re.Match], str]]] = [
    # 13/11/2026, 13/11/26 (dia e mês sozinhos podem ser fração: ficam).
    (re.compile(r"\b(?P<dia>\d{1,2})/(?P<mes>\d{1,2})/(?P<ano>\d{4}|\d{2})\b"), _data),
    (
        re.compile(
            rf"(?P<sinal>(?<![\w.,])-)?(?P<moeda>R\$|US\$|U\$|€|\$)\s?(?P<valor>{_NUM})"
            r"(?:\s(?P<escala>mil|milhão|milhões|bilhão|bilhões|trilhão|trilhões)\b)?"
        ),
        _dinheiro,
    ),
    (
        re.compile(rf"(?P<valor>{_SINAL}(?:{_NUM}))\s?%"),
        lambda m: f"{numero(m['valor'])} por cento",
    ),
    # 25°C, 25 °C, 25ºC, 25° (o ° sozinho é grau; o º sozinho é ordinal).
    (
        re.compile(
            rf"(?P<valor>{_SINAL}(?:{_NUM}))\s?(?:°\s?(?P<escala>[CcFf])?|º\s?(?P<escala2>[CcFf]))"
            r"(?![^\W\d_])"
        ),
        _temperatura,
    ),
    # 14h30, 14h30min, 14:30, 8h, 14 h.
    (
        re.compile(
            r"\b(?P<hora>[01]?\d|2[0-3])(?:\s?h(?P<min>[0-5]\d)?(?:min)?|:(?P<min2>[0-5]\d))"
            r"(?![^\W\d_])"
        ),
        _horas,
    ),
    # 1º, 2ª, 25.º
    (
        re.compile(r"\b(?P<valor>\d{1,3})\.?(?P<marca>[ºª])"),
        lambda m: ordinal(int(m["valor"]), fem=m["marca"] == "ª"),
    ),
    (re.compile(r"\b([123])/([234])\b"), lambda m: _FRACOES.get((int(m[1]), int(m[2])), m[0])),
    # Intervalo: 10-15 → 10 a 15.
    (re.compile(r"(?<=\d)\s?[-–]\s?(?=\d)"), lambda m: " a "),
    (
        re.compile(rf"(?P<valor>{_SINAL}(?:{_NUM}))(?P<seguinte>\s+[^\W\d_]+)?"),
        _numero_solto,
    ),
]


# O espeak lê "Pegasus" como oxítona (/pega'zus/), com o "pega" átono; o acento põe
# a tônica na primeira sílaba, como se diz em português.
_PEGASUS = re.compile(r"\bPegasus\b", re.IGNORECASE)


def para_voz(texto: str) -> str:
    """O texto como deve ser falado."""
    texto = _PEGASUS.sub("Pégasus", texto)
    for padrao, troca in _SUBSTITUICOES:
        texto = padrao.sub(troca, texto)
    return texto
