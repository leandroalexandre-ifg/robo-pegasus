"""Segurança da API: tokens por tablet."""

import hashlib
import hmac
import re

TOKEN_MIN = 32  # caracteres; `python -m scripts.tokens adicionar` gera 43
_TOKEN = re.compile(r"[A-Za-z0-9_-]+")  # base64 para URL, como secrets.token_urlsafe
_DISTINTOS_MIN = 16  # um token aleatório de 43 caracteres tem ~31 caracteres distintos
_NOME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


def carregar_tablets(valor: str) -> tuple[tuple[str, str], ...]:
    """Lê PEGASUS_TABLETS ("nome:token,nome:token"). Recusa (ValueError) nomes ou
    tokens repetidos e tokens curtos ou com cara de não aleatórios. A mensagem de
    erro cita o nome do tablet, nunca o token."""
    tablets: list[tuple[str, str]] = []
    for item in (i.strip() for i in valor.split(",")):
        if not item:
            continue
        nome, sep, token = (p.strip() for p in item.partition(":"))
        if not sep or not _NOME.fullmatch(nome):
            raise ValueError(
                "PEGASUS_TABLETS: cada item deve ser nome:token, com nome de até 32 letras "
                "minúsculas, dígitos, - ou _"
            )
        if (
            len(token) < TOKEN_MIN
            or not _TOKEN.fullmatch(token)
            or len(set(token)) < _DISTINTOS_MIN
        ):
            raise ValueError(
                f"PEGASUS_TABLETS: o token de {nome} deve ser aleatório, com pelo menos "
                f"{TOKEN_MIN} caracteres de base64 para URL (gere com scripts.tokens)"
            )
        tablets.append((nome, token))
    nomes = [n for n, _ in tablets]
    if len(set(nomes)) != len(nomes):
        raise ValueError("PEGASUS_TABLETS: nome de tablet repetido")
    if len({t for _, t in tablets}) != len(tablets):
        raise ValueError("PEGASUS_TABLETS: dois tablets com o mesmo token")
    return tuple(tablets)


def _resumo(texto: str) -> bytes:
    return hashlib.sha256(texto.encode()).digest()


def identificar(token: object, tablets: tuple[tuple[str, str], ...]) -> str | None:
    """O nome do tablet dono do token, ou None.

    Compara os resumos SHA-256 (sempre do mesmo tamanho) com todos os tokens, sem
    parar no primeiro que bate: o tempo não revela quanto do token estava certo,
    nem qual tablet é."""
    if not isinstance(token, str):
        return None
    recebido = _resumo(token)
    dono = None
    for nome, esperado in tablets:
        if hmac.compare_digest(recebido, _resumo(esperado)):
            dono = nome
    return dono
