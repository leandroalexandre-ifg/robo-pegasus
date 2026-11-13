"""Ferramenta busca_web: os 3 primeiros resultados do SearXNG local (SafeSearch estrito)."""

import collections
import time
from urllib.parse import urlsplit

from app.ferramentas.rede import Cache, Resultado, obter_json
from app.ferramentas.wikipedia import cortar

FONTE = "uma busca na internet"
RESULTADOS = 3
LIMITE_TRECHO = 200
LIMITE_TOTAL = 1000
LIMITE_CONSULTA = 100

DEFINICAO = {
    "type": "function",
    "function": {
        "name": "busca_web",
        "description": "Busca na internet notícias, resultados de jogos e fatos recentes.",
        "parameters": {
            "type": "object",
            "properties": {"consulta": {"type": "string"}},
            "required": ["consulta"],
        },
    },
}

_buscas = Cache(validade_s=300)  # 5 min: notícias mudam
_recentes: collections.deque[float] = collections.deque()


class LimiteDeBuscas(Exception):
    """Buscas demais no último minuto (todos os tablets juntos)."""


def _reservar(por_minuto: int) -> None:
    agora = time.monotonic()
    while _recentes and agora - _recentes[0] > 60:
        _recentes.popleft()
    if len(_recentes) >= por_minuto:
        raise LimiteDeBuscas
    _recentes.append(agora)


def _dominio(url: str) -> str:
    dominio = urlsplit(url).hostname or ""
    return dominio.removeprefix("www.")


def _resumir(dados: object) -> str:
    itens = (dados.get("results") if isinstance(dados, dict) else None) or []
    linhas, total = [], 0
    for item in itens:
        if not isinstance(item, dict):
            continue
        titulo = cortar(str(item.get("title") or ""), 100)
        trecho = cortar(str(item.get("content") or ""), LIMITE_TRECHO)
        if not (titulo or trecho):
            continue
        linha = f"{len(linhas) + 1}. {_dominio(str(item.get('url') or ''))} — {titulo}. {trecho}"
        if total + len(linha) > LIMITE_TOTAL:
            break
        linhas.append(linha)
        total += len(linha)
        if len(linhas) == RESULTADOS:
            break
    return "\n".join(linhas)


async def busca_web(consulta: str, url: str, por_minuto: int) -> Resultado:
    consulta = " ".join((consulta or "").split())[:LIMITE_CONSULTA]
    if not consulta:
        return Resultado("Nenhuma consulta informada.")
    chave = consulta.casefold()
    if (guardado := _buscas.obter(chave)) is not None:
        return guardado
    _reservar(por_minuto)
    dados = await obter_json(
        f"{url.rstrip('/')}/search",
        {
            "q": consulta,
            "format": "json",
            "safesearch": "2",
            "language": "pt-BR",
            "categories": "general",
        },
    )
    texto = _resumir(dados)
    resultado = Resultado(texto, FONTE) if texto else Resultado("A busca não achou resultados.")
    _buscas.guardar(chave, resultado)
    return resultado


def limpar() -> None:
    _buscas.limpar()
    _recentes.clear()
