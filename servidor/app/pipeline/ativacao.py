"""Palavra de ativação: reconhece "Pegasus" (ou "Ei, Pegasus") no começo de uma fala transcrita."""

import re
import unicodedata

PALAVRA = "pegasus"
# Grafias que o Whisper costuma produzir para "Pegasus" em português, já sem acento.
# Além delas, vale qualquer grafia a uma letra de distância (ver `e_ativacao`).
VARIANTES = frozenset({"pegasus", "pegaso", "pegasos", "pegasso", "pegazus", "pegazo", "pegassus"})
# Chamamentos aceitos antes da palavra: "Ei, Pegasus", "Oi, Pegasus". "Hey" e "E aí"
# são como o Whisper às vezes escreve o "Ei" (o "E aí" em 5 de 100 falas sintéticas).
CHAMAMENTOS = frozenset({"ei", "oi", "hey", "eai"})
_E_AI = re.compile(r"^[\W\d_]*e\s+a[íi](?![^\W\d_])", re.IGNORECASE)
_TAMANHO_MIN_APROXIMADO = 6  # abaixo disso, uma letra de diferença pega palavras comuns

# Primeira palavra (só letras) e o resto, aceitando pontuação antes dela.
_PRIMEIRA_PALAVRA = re.compile(r"^[\W\d_]*([^\W\d_]+)(.*)$", re.DOTALL)
_PONTUACAO = " \t\n,.;:!?¿¡-–—…\"'«»()"


def _normalizar(palavra: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", palavra.casefold())
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


def _distancia(a: str, b: str) -> int:
    """Distância de edição (Levenshtein)."""
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (ca != cb)))
        anterior = atual
    return anterior[-1]


def e_ativacao(palavra: str) -> bool:
    """A palavra é "Pegasus" ou uma variação próxima dela."""
    n = _normalizar(palavra)
    if n in VARIANTES:
        return True
    return len(n) >= _TAMANHO_MIN_APROXIMADO and _distancia(n, PALAVRA) <= 1


def pergunta(texto: str) -> str | None:
    """O que vem depois da palavra de ativação no começo do texto.

    None: o texto não começa com a palavra (a fala deve ser descartada).
    "": a fala era só a palavra, sem pergunta.
    A palavra pode vir depois de um chamamento: "Ei, Pegasus", "Oi, Pegasus",
    "E aí, Pegasus"."""
    texto = _E_AI.sub("eai", texto, count=1)
    m = _PRIMEIRA_PALAVRA.match(texto)
    if m is not None and _normalizar(m[1]) in CHAMAMENTOS:
        m = _PRIMEIRA_PALAVRA.match(m[2])
    if m is None or not e_ativacao(m[1]):
        return None
    return m[2].lstrip(_PONTUACAO).rstrip()


# Encerramento da conversa: a fala inteira tem de ser uma despedida, para que
# "tchau, mas antes me diz uma coisa" ainda vire pergunta. Valem, em volta do
# núcleo, palavras de cortesia ("ok, obrigado, tchau") e o nome ("tchau, Pegasus").
_DESPEDIDAS = frozenset(
    {
        "tchau",
        "tchau tchau",
        "ate logo",
        "ate mais",
        "ate depois",
        "ate a proxima",
        "ate amanha",
        "e so isso",
        "era so isso",
        "so isso",
        "por hoje e so",
        "pode parar",
        "pode descansar",
        "chega por hoje",
        "encerrar",
        "encerrar a conversa",
        "fim da conversa",
    }
)
# Só agradecer ("obrigado") não encerra: a pessoa pode seguir perguntando.
_CORTESIA = frozenset(
    {"ok", "ta", "bom", "entao", "beleza", "certo", "obrigado", "obrigada", "muito", "valeu"}
)
_CORTESIA_FINAL = _CORTESIA | {"tchau"}  # "é só isso, tchau"
_PALAVRAS = re.compile(r"[^\W\d_]+")


def encerra(texto: str) -> bool:
    """A fala inteira é uma despedida ("tchau, Pegasus", "obrigado, é só isso")."""
    palavras = [_normalizar(p) for p in _PALAVRAS.findall(texto)]
    palavras = [p for p in palavras if not e_ativacao(p)]
    while palavras:
        if " ".join(palavras) in _DESPEDIDAS:
            return True
        if palavras[0] in _CORTESIA:
            palavras = palavras[1:]
        elif palavras[-1] in _CORTESIA_FINAL:
            palavras = palavras[:-1]
        else:
            return False
    return False
