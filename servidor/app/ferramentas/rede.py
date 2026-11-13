"""Cliente HTTP das ferramentas: um só por processo, com conexões reaproveitadas."""

import time
from collections import OrderedDict
from dataclasses import dataclass

import httpx

USER_AGENT = "RoboPegasus/0.1 (+https://github.com/leandroalexandre-ifg/robo-pegasus)"
_LIMITE_PADRAO = httpx.Timeout(3.0, connect=1.5)

_cliente: httpx.AsyncClient | None = None
_transporte: httpx.AsyncBaseTransport | None = None  # testes trocam por um MockTransport


def cliente() -> httpx.AsyncClient:
    global _cliente
    if _cliente is None:
        _cliente = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=_LIMITE_PADRAO,
            follow_redirects=False,  # os destinos são fixos; um redirecionamento é recusado
            transport=_transporte,
            limits=httpx.Limits(max_connections=16, keepalive_expiry=300),
        )
    return _cliente


def usar_transporte(transporte: httpx.AsyncBaseTransport | None) -> None:
    """Para os testes: o próximo cliente usa este transporte."""
    global _cliente, _transporte
    _cliente, _transporte = None, transporte


async def fechar() -> None:
    global _cliente
    if _cliente is not None:
        await _cliente.aclose()
        _cliente = None


async def obter_json(url: str, params: dict) -> object:
    resposta = await cliente().get(url, params=params)
    resposta.raise_for_status()
    return resposta.json()


@dataclass(frozen=True)
class Resultado:
    """O que a ferramenta devolve ao LLM. `fonte` é o nome citado em voz ("a
    Wikipédia"); None quando não há o que citar (nada encontrado)."""

    texto: str
    fonte: str | None = None


class Cache:
    """Cache em memória com validade e tamanho máximo (o mais antigo sai primeiro)."""

    def __init__(self, validade_s: float, maximo: int = 256):
        self.validade_s = validade_s
        self.maximo = maximo
        self._itens: OrderedDict[object, tuple[float, object]] = OrderedDict()

    def obter(self, chave: object) -> object | None:
        item = self._itens.get(chave)
        if item is None:
            return None
        if time.monotonic() - item[0] > self.validade_s:
            del self._itens[chave]
            return None
        return item[1]

    def guardar(self, chave: object, valor: object) -> None:
        self._itens[chave] = (time.monotonic(), valor)
        self._itens.move_to_end(chave)
        while len(self._itens) > self.maximo:
            self._itens.popitem(last=False)

    def limpar(self) -> None:
        self._itens.clear()
