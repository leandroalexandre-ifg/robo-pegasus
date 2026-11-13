"""Detecta, no servidor, perguntas sobre fatos recentes, para obrigar a busca_web.

O prompt já pede a busca nesses casos, mas o modelo às vezes responde de memória
(1 em 30 no teste). Quando a fala tem um termo de tempo ou de atualidade, a
requisição vai com tool_choice nomeado e o modelo não tem como pular a busca.

Termos fortes (atual, placar, resultado, preço, notícia) bastam. Os fracos (último,
hoje, agora, "quem é o/a") também aparecem em conversa ("como você está hoje?",
"me conta uma piada agora") e não valem quando a fala é sobre o robô ou o usuário
ou é um pedido de conversa. Nenhum vale para hora, data, clima ou contas, que têm
caminho próprio."""

import re
import unicodedata

_FORTES = re.compile(r"\b(atua(l|is|lmente)|placar(es)?|resultados?|precos?|noticias?)\b")
_FRACOS = re.compile(r"\b(ultim[oa]s?|hoje|agora|quem e (o|a)s?)\b")
# A fala é sobre o robô ou sobre quem fala: "o que você fez hoje?", "meu último pedido".
_PESSOAL = re.compile(
    r"\b(voce|voces|vc|tu|te|contigo|seu|sua|seus|suas|eu|me|mim|meu|minha|meus|minhas|"
    r"comigo|nosso|nossa)\b"
)
_CONVERSA = re.compile(r"\b(piadas?|historias?|historinhas?|charadas?|adivinhas?|cant[ae]r?)\b")
# Caminhos próprios: "[agora: …]" na fala e a ferramenta clima.
_HORA_DATA = re.compile(
    r"\bque (horas?|dia|mes|ano|data)\b|\bhoras? (sao|e)\b|\b(dia|data) (e|de) hoje\b|"
    r"\bhoje e (que|qual)\b"
)
_CLIMA = re.compile(
    r"\b(tempo|clima|chuva|chover|chovendo|temperatura|frio|calor|previsao|graus?|"
    r"umidade|vento|ventando|nublado|ensolarado|sol)\b"
)
_CONTA = re.compile(r"\d\s*[-+x*/÷]\s*\d|\b(vezes|dividido|multiplicado|somado|raiz)\b")


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


def pede_busca(texto: str) -> bool:
    """A fala pergunta por algo que muda com o tempo e pede a busca_web."""
    t = _normalizar(texto)
    if _HORA_DATA.search(t) or _CLIMA.search(t) or _CONTA.search(t):
        return False
    if _FORTES.search(t):
        return True
    return bool(_FRACOS.search(t)) and not (_PESSOAL.search(t) or _CONVERSA.search(t))
