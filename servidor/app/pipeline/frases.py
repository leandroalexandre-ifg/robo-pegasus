"""Corte do fluxo de texto do LLM em frases, para sintetizar a voz frase por frase."""

import re
from collections.abc import AsyncIterable, AsyncIterator

# Fim de frase: pontuação final (com aspas ou parênteses de fechamento) seguida de
# espaço, ou quebra de linha. Exigir o espaço evita cortar números como "3.5".
_FIM = re.compile(r"[.!?…]+[\"')\]»]*\s+|\n+")
_TEM_TEXTO = re.compile(r"\w")


async def cortar_frases(pedacos: AsyncIterable[str]) -> AsyncIterator[str]:
    """Recebe pedaços de texto em fluxo e devolve cada frase assim que ela termina."""
    pendente = ""
    async for pedaco in pedacos:
        pendente += pedaco
        while m := _FIM.search(pendente):
            frase, pendente = pendente[: m.end()].strip(), pendente[m.end() :]
            if _TEM_TEXTO.search(frase):
                yield frase
    frase = pendente.strip()
    if _TEM_TEXTO.search(frase):
        yield frase
