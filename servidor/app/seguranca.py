"""Segurança da API: tokens por tablet, IP real atrás do proxy e bloqueio de IP."""

import collections
import hashlib
import hmac
import ipaddress
import re
import time
from collections.abc import Callable

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


def ip_real(direto: str | None, encaminhado: str | None, proxies: frozenset[str]) -> str:
    """O IP do cliente. Se a conexão vem de um proxy confiável (o Caddy, no mesmo
    servidor), vale o X-Forwarded-For: percorrido da direita para a esquerda, o
    primeiro endereço que não é de proxy, porque só as entradas acrescentadas
    pelos proxies são confiáveis (as da esquerda vêm do próprio cliente)."""
    ip = direto or "desconhecido"
    if ip not in proxies or not encaminhado:
        return ip
    for item in reversed(encaminhado.split(",")):
        item = item.strip()
        if item in proxies:
            continue
        try:
            return str(ipaddress.ip_address(item))
        except ValueError:
            break  # cabeçalho estragado: fica com o proxy, que nunca é bloqueado
    return ip


def limpar_para_log(valor: object, tamanho: int = 32) -> str:
    """Texto vindo do cliente (device_id), seguro para uma linha de log."""
    return re.sub(r"[^A-Za-z0-9_.:-]", "?", str(valor))[:tamanho]


class Bloqueio:
    """Bloqueia por `bloqueio_s` o IP com `tentativas` hellos inválidos em `janela_s`.

    Os IPs de proxy nunca são bloqueados: atrás do Caddy, bloquear o proxy
    derrubaria todos os tablets."""

    MAX_IPS = 10_000  # acima disso, limpa o que já expirou

    def __init__(
        self,
        proxies: frozenset[str] = frozenset(),
        tentativas: int = 5,
        janela_s: float = 600,
        bloqueio_s: float = 900,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self._proxies = proxies
        self._tentativas = tentativas
        self._janela_s = janela_s
        self._bloqueio_s = bloqueio_s
        self._relogio = relogio
        self._falhas: dict[str, collections.deque[float]] = {}
        self._ate: dict[str, float] = {}  # IP bloqueado → até quando
        self._recusadas: collections.Counter[str] = collections.Counter()  # durante o bloqueio

    def bloqueado(self, ip: str) -> bool:
        ate = self._ate.get(ip)
        if ate is None:
            return False
        if self._relogio() >= ate:
            del self._ate[ip]
            self._recusadas.pop(ip, None)
            return False
        self._recusadas[ip] += 1
        return True

    def recusadas(self, ip: str) -> int:
        """Conexões recusadas desde o início do bloqueio do IP."""
        return self._recusadas[ip]

    def falhou(self, ip: str) -> bool:
        """Conta um hello inválido; devolve True se o IP acabou de ser bloqueado."""
        if ip in self._proxies:
            return False
        agora = self._relogio()
        if len(self._falhas) > self.MAX_IPS:
            self._limpar(agora)
        falhas = self._falhas.setdefault(ip, collections.deque())
        falhas.append(agora)
        while falhas and falhas[0] <= agora - self._janela_s:
            falhas.popleft()
        if len(falhas) < self._tentativas:
            return False
        del self._falhas[ip]
        self._ate[ip] = agora + self._bloqueio_s
        return True

    def _limpar(self, agora: float) -> None:
        for ip in [i for i, f in self._falhas.items() if not f or f[-1] <= agora - self._janela_s]:
            del self._falhas[ip]
        for ip in [i for i, ate in self._ate.items() if ate <= agora]:
            del self._ate[ip]
            self._recusadas.pop(ip, None)
