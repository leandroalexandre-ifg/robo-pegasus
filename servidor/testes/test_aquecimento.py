import asyncio
import json

import httpx

from app import aquecimento
from app.config import carregar_config


def _servidor(pedidos):
    def responder(pedido: httpx.Request) -> httpx.Response:
        corpo = json.loads(pedido.content or b"{}")
        pedidos.append((pedido.url.path, corpo))
        if pedido.url.path == "/tokenize":
            # Começo fixo [1, 2, 3] + um token por letra da fala.
            fala = corpo["messages"][-1]["content"]
            return httpx.Response(200, json={"tokens": [1, 2, 3, *map(ord, fala)]})
        if pedido.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "m"}]})
        return httpx.Response(200, json={"choices": [{"text": "x"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(responder))


def _rodar(ambiente):
    pedidos = []
    config = carregar_config(ambiente)
    a = aquecimento.Aquecedor(config, _servidor(pedidos))
    total = asyncio.run(a.aquecer())
    return total, pedidos


def test_envia_so_o_comeco_comum_de_cada_prefixo():
    total, pedidos = _rodar({"PEGASUS_EMOCAO_MODO": "paralelo", "PEGASUS_FERRAMENTAS": "clima"})
    completions = [c for p, c in pedidos if p == "/v1/completions"]
    # Fala com ferramentas, segunda rodada sem ferramentas e emoção em paralelo.
    assert [c["prompt"] for c in completions] == [[1, 2, 3]] * 3
    assert all(c["max_tokens"] == 1 and c["model"] == "m" for c in completions)
    assert total == 9
    tokenizados = [c for p, c in pedidos if p == "/tokenize"]
    assert tokenizados[0]["tools"][0]["function"]["name"] == "clima"
    assert "tools" not in tokenizados[2]
    assert tokenizados[4]["tools"][0]["function"]["name"] == "definir_emocao"


def test_sem_ferramentas_no_modo_antes_um_prefixo_so():
    _, pedidos = _rodar({"PEGASUS_EMOCAO_MODO": "antes"})
    # No modo antes a fala oferece definir_emocao: fala + segunda rodada.
    assert len([p for p, _ in pedidos if p == "/v1/completions"]) == 2


def test_falha_nao_derruba():
    def erro(pedido):
        return httpx.Response(500)

    a = aquecimento.Aquecedor(
        carregar_config({}), httpx.AsyncClient(transport=httpx.MockTransport(erro))
    )
    asyncio.run(a.tentar())  # só vai para o log


def test_comum():
    assert aquecimento._comum([1, 2, 3, 4], [1, 2, 5]) == [1, 2]
    assert aquecimento._comum([], [1]) == []
