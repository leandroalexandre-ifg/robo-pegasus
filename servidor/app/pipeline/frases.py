"""Corte do fluxo de texto do LLM em frases, para sintetizar a voz frase por frase."""

import re
from collections.abc import AsyncIterable, AsyncIterator

# Fim de frase: pontuação final (com aspas ou parênteses de fechamento) seguida de
# espaço, ou quebra de linha. Exigir o espaço evita cortar números como "3.5".
_FIM = re.compile(r"[.!?…]+[\"')\]»]*\s+|\n+")
# Na primeira frase vale também a vírgula seguida de espaço ("3,5" não corta):
# o primeiro trecho chega mais cedo ao Piper e o primeiro áudio sai antes.
_FIM_OU_VIRGULA = re.compile(r"[.!?…]+[\"')\]»]*\s+|\n+|,\s+")
_TEM_TEXTO = re.compile(r"\w")


async def cortar_frases[T](
    pedacos: AsyncIterable[str | T], primeira_na_virgula: bool = False
) -> AsyncIterator[str | T]:
    """Recebe pedaços de texto em fluxo e devolve cada frase assim que ela termina.
    Itens que não são texto (emoções) passam adiante na hora, sem esperar a frase.
    Com `primeira_na_virgula`, o primeiro trecho termina também na primeira vírgula."""
    pendente = ""
    corte = _FIM_OU_VIRGULA if primeira_na_virgula else _FIM
    async for pedaco in pedacos:
        if not isinstance(pedaco, str):
            yield pedaco
            continue
        pendente += pedaco
        while m := corte.search(pendente):
            frase, pendente = pendente[: m.end()].strip(), pendente[m.end() :]
            if _TEM_TEXTO.search(frase):
                corte = _FIM
                yield frase
    frase = pendente.strip()
    if _TEM_TEXTO.search(frase):
        yield frase
