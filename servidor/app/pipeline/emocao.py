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


# Chamada de ferramenta que vazou no texto, nos formatos XML (Qwen3) e JSON (Hermes).
_INICIO, _FIM = "<tool_call>", "</tool_call>"
_EMOCAO_XML = re.compile(r"<parameter=emocao>\s*(\w+)")
_EMOCAO_JSON = re.compile(r"\"emocao\"\s*:\s*\"(\w+)\"")


def _emocao_da_marcacao(bloco: str) -> Emocao | None:
    m = _EMOCAO_XML.search(bloco) or _EMOCAO_JSON.search(bloco)
    return _validar(m.group(1)) if m else None


async def separar_marcacoes(pedacos: AsyncIterable[str]) -> AsyncIterator[str | Emocao]:
    """Retira do fluxo de texto blocos <tool_call>…</tool_call> que o parser do vLLM
    não tenha capturado, convertendo-os em Emocao. O resto do texto passa adiante."""
    pendente = ""
    async for pedaco in pedacos:
        pendente += pedaco
        while True:
            inicio = pendente.find(_INICIO)
            if inicio < 0:
                # Segura um possível começo de "<tool_call>" partido entre pedaços.
                corte = pendente.rfind("<")
                if corte >= 0 and _INICIO.startswith(pendente[corte:]):
                    texto, pendente = pendente[:corte], pendente[corte:]
                else:
                    texto, pendente = pendente, ""
                if texto:
                    yield texto
                break
            fim = pendente.find(_FIM, inicio)
            if fim < 0:
                if inicio:
                    yield pendente[:inicio]
                    pendente = pendente[inicio:]
                break
            if inicio:
                yield pendente[:inicio]
            if emocao := _emocao_da_marcacao(pendente[inicio:fim]):
                yield emocao
            pendente = pendente[fim + len(_FIM) :]
    if pendente.startswith(_INICIO):
        if emocao := _emocao_da_marcacao(pendente):
            yield emocao
    elif pendente:
        yield pendente


_NOMES = "|".join(EMOCOES)
_LIMPEZA = [
    re.compile(r"<tool_call>.*?(</tool_call>|$)", re.S),  # chamada de ferramenta no texto
    re.compile(r"</?[a-zA-Z_][^<>]*>"),  # outras marcações <...>
    re.compile(rf"[\[(]\s*(?:emo[cç][aã]o\s*:\s*)?(?:{_NOMES})\s*[\])]", re.I),  # [feliz] (triste)
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
