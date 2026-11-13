"""Data e hora atuais, por extenso, para o LLM.

Não é uma ferramenta chamada pelo modelo: o texto vai no começo da mensagem do
usuário ("[agora: …]"), sem rodada extra do LLM."""

from datetime import datetime
from zoneinfo import ZoneInfo

_DIAS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira")
_DIAS += ("sábado", "domingo")
_MESES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def _hora(h: int, m: int) -> str:
    horas = "1 hora" if h == 1 else f"{h} horas"
    if m == 0:
        return horas
    return f"{horas} e {'1 minuto' if m == 1 else f'{m} minutos'}"


def por_extenso(quando: datetime) -> str:
    """ "quinta-feira, 13 de novembro de 2026, 14 horas e 5 minutos"."""
    dia = "1º" if quando.day == 1 else str(quando.day)
    return (
        f"{_DIAS[quando.weekday()]}, {dia} de {_MESES[quando.month - 1]} de {quando.year}, "
        f"{_hora(quando.hour, quando.minute)}"
    )


def agora(fuso: str, quando: datetime | None = None) -> str:
    """Data e hora no fuso configurado (America/Sao_Paulo por padrão)."""
    return por_extenso((quando or datetime.now(ZoneInfo(fuso))).astimezone(ZoneInfo(fuso)))
