"""Emoções do rosto: a ferramenta definir_emocao do LLM e a limpeza do texto para a voz."""

import json
import re
import unicodedata
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass

EMOCOES = ("neutro", "feliz", "triste", "surpreso", "pensativo", "bravo")

FERRAMENTA = {
    "type": "function",
    "function": {
        "name": "definir_emocao",
        "description": "Define a expressão do rosto do robô enquanto ele fala a resposta.",
        "parameters": {
            "type": "object",
            "properties": {"emocao": {"type": "string", "enum": list(EMOCOES)}},
            "required": ["emocao"],
        },
    },
}


@dataclass(frozen=True)
class Emocao:
    nome: str


def _validar(nome: object) -> Emocao | None:
    if isinstance(nome, str) and (nome := nome.strip().lower()) in EMOCOES:
        return Emocao(nome)
    return None


def emocao_da_chamada(nome_ferramenta: str, argumentos: str) -> Emocao | None:
    """Converte uma chamada de ferramenta do LLM em Emocao (None se inválida)."""
    if nome_ferramenta != FERRAMENTA["function"]["name"]:
        return None
    try:
        dados = json.loads(argumentos or "{}")
    except ValueError:
        return None
    return _validar(dados.get("emocao")) if isinstance(dados, dict) else None


# Imitações de chamada de ferramenta escritas no texto, em qualquer formato:
# <tool_call>, <tool_use>, <function=...>, {"name": ...}, definir_emocao(...).
_MARCADOR = re.compile(
    r"<\s*/?\s*(?:tool|function|parameter)|definir_?emo|\{\s*\"(?:name|emocao|arguments)\"",
    re.I,
)
_PREFIXOS = (
    "<tool",
    "</tool",
    "<function",
    "</function",
    "<parameter",
    '{"name"',
    '{"emocao"',
    '{"arguments"',
    "definir_emo",
)


def _pode_comecar_marcador(trecho: str) -> bool:
    t = re.sub(r"\s+", "", trecho).lower()
    return bool(t) and any(p.startswith(t) for p in _PREFIXOS)


def _corte_seguro(texto: str) -> int:
    """Até onde o texto pode seguir: o fim pode ser o começo de um marcador partido."""
    candidatos = [texto.rfind("<"), texto.rfind("{")]
    if m := re.search(r"\w+$", texto):
        candidatos.append(m.start())
    suspeitos = [i for i in candidatos if i >= 0 and _pode_comecar_marcador(texto[i:])]
    return min(suspeitos, default=len(texto))


async def cortar_marcacoes[T](pedacos: AsyncIterable[str | T]) -> AsyncIterator[str | T]:
    """Repassa o texto até a primeira imitação de chamada de ferramenta e descarta o
    resto. O LLM só escreve a chamada depois da fala, então nada a ser dito se perde."""
    pendente = ""
    async for pedaco in pedacos:
        if not isinstance(pedaco, str):  # avisos (Espera) passam na hora
            yield pedaco
            continue
        pendente += pedaco
        if m := _MARCADOR.search(pendente):
            if pendente[: m.start()]:
                yield pendente[: m.start()]
            return
        corte = _corte_seguro(pendente)
        if corte:
            yield pendente[:corte]
            pendente = pendente[corte:]
    if pendente:
        yield pendente


_NOMES = "|".join(EMOCOES)
_LIMPEZA = [
    re.compile(r"<tool_call>.*?(</tool_call>|$)", re.S),  # chamada de ferramenta no texto
    re.compile(r"definir_?emo\w*\s*(\([^)]*\))?", re.I),  # definir_emocao(feliz)
    re.compile(r"\{[^{}]*\}"),  # objetos JSON
    re.compile(r"</?[a-zA-Z_][^<>]*>"),  # outras marcações <...>
    re.compile(rf"[\[(]\s*(?:emo[cç][aã]o\s*:\s*)?(?:{_NOMES})\s*[\])]", re.I),  # [feliz] (triste)
    re.compile(r"\b(?:https?://|www\.)\S+", re.I),  # endereços vindos das buscas
    re.compile(r"\*[^*\n]{1,40}\*"),  # ações entre asteriscos: *sorri*
    re.compile(r"[*_`#~>|]+"),  # símbolos de markdown
    re.compile(r"^\s*[-•]\s+", re.M),  # marcadores de lista
]


def _sem_emoji(texto: str) -> str:
    return "".join(
        c
        for c in texto
        if unicodedata.category(c) != "So" and c not in "️‍" and not 0x1F3FB <= ord(c) <= 0x1F3FF
    )


_NEGRITO = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")


def limpar_para_voz(frase: str) -> str:
    """Remove do texto tudo o que não deve ser lido em voz alta."""
    # Negrito mantém o conteúdo; só depois *entre asteriscos simples* vira ação a remover.
    frase = _NEGRITO.sub(lambda m: m.group(1) or m.group(2), frase)
    for padrao in _LIMPEZA:
        frase = padrao.sub(" ", frase)
    frase = _sem_emoji(frase)
    frase = re.sub(r"\s+([,.!?…;:])", r"\1", frase)
    return re.sub(r"\s+", " ", frase).strip()
