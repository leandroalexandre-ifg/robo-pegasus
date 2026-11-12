"""Palavra de ativação: reconhece "Pegasus" (ou "Ei, Pegasus") no começo de uma fala transcrita."""

import re
import unicodedata

PALAVRA = "pegasus"
# Grafias que o Whisper costuma produzir para "Pegasus" em português, já sem acento.
# Além delas, vale qualquer grafia a uma letra de distância (ver `e_ativacao`).
VARIANTES = frozenset({"pegasus", "pegaso", "pegasos", "pegasso", "pegazus", "pegazo", "pegassus"})
# Chamamentos aceitos antes da palavra: "Ei, Pegasus", "Oi, Pegasus". "Hey" é como o
# Whisper às vezes escreve o "Ei".
CHAMAMENTOS = frozenset({"ei", "oi", "hey"})
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
    A palavra pode vir depois de um chamamento: "Ei, Pegasus", "Oi, Pegasus"."""
    m = _PRIMEIRA_PALAVRA.match(texto)
    if m is not None and _normalizar(m[1]) in CHAMAMENTOS:
        m = _PRIMEIRA_PALAVRA.match(m[2])
    if m is None or not e_ativacao(m[1]):
        return None
    return m[2].lstrip(_PONTUACAO).rstrip()
