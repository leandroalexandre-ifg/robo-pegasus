"""Ferramenta wikipedia: começo do verbete mais relevante da Wikipédia em português.

Um pedido só: busca (generator=search) e introdução em texto puro (TextExtracts)."""

import re

from app.ferramentas.rede import Cache, Resultado, obter_json

API = "https://pt.wikipedia.org/w/api.php"
FONTE = "a Wikipédia"
LIMITE_CARACTERES = 600

DEFINICAO = {
    "type": "function",
    "function": {
        "name": "wikipedia",
        "description": "Resumo de um verbete da Wikipédia.",
        "parameters": {
            "type": "object",
            "properties": {"assunto": {"type": "string"}},
            "required": ["assunto"],
        },
    },
}

_verbetes = Cache(validade_s=3600)


def cortar(texto: str, limite: int) -> str:
    """Corta no fim da última frase que cabe no limite (ou na última palavra)."""
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) <= limite:
        return texto
    trecho = texto[:limite]
    if (fim := max(trecho.rfind(". "), trecho.rfind("! "), trecho.rfind("? "))) > limite // 3:
        return trecho[: fim + 1]
    return trecho.rsplit(" ", 1)[0] + "…"


async def wikipedia(assunto: str) -> Resultado:
    assunto = (assunto or "").strip()[:100]
    if not assunto:
        return Resultado("Nenhum assunto informado.")
    chave = assunto.casefold()
    if (guardado := _verbetes.obter(chave)) is not None:
        return guardado
    dados = await obter_json(
        API,
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": assunto,
            "gsrlimit": "1",
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "exchars": "1200",
            "redirects": "1",
        },
    )
    consulta = (dados.get("query") if isinstance(dados, dict) else None) or {}
    paginas = consulta.get("pages") or []
    pagina = paginas[0] if paginas else {}
    extrato = cortar(pagina.get("extract") or "", LIMITE_CARACTERES)
    if not extrato:
        resultado = Resultado(f"Nada encontrado na Wikipédia sobre: {assunto}.")
    else:
        resultado = Resultado(f"Verbete {pagina.get('title', assunto)}: {extrato}", FONTE)
    _verbetes.guardar(chave, resultado)
    return resultado


def limpar_cache() -> None:
    _verbetes.limpar()
