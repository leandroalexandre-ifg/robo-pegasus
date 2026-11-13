"""Aquecimento do cache de prefixo do vLLM.

Com o Qwen3.8 (híbrido, com camadas Gated DeltaNet), o vLLM só reaproveita um
prefixo se tiver guardado o estado dessas camadas exatamente onde o prefixo
termina, e ele só guarda esse estado no fim de cada pedido. Os pedidos do robô
nunca terminam no fim do trecho fixo (prompt de sistema e ferramentas), então
o cache não acertava nunca (taxa 0%) e o trecho fixo (~700 tokens) era processado
de novo em todo turno.

Aqui o servidor manda, de tempos em tempos, um pedido com só esse trecho fixo
(1 token de resposta). Depois dele, o 1º token dos turnos caiu de ~220 para ~50
ms (medido em 2026-11-13). Exige o vLLM com --prefix-match-unit (16), para o
acerto valer fora das fronteiras de bloco (832 tokens neste modelo).

O trecho fixo é achado sem depender do template do modelo: o começo comum da
tokenização de dois pedidos que só diferem na fala do usuário.
"""

import asyncio
import logging
import time

import httpx

from app.config import Config
from app.pipeline import llm

log = logging.getLogger("pegasus.aquecimento")

INTERVALO_S = 60.0
LIMITE_S = 10.0


def _comum(a: list[int], b: list[int]) -> list[int]:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return a[:n]


class Aquecedor:
    def __init__(self, config: Config, cliente: httpx.AsyncClient | None = None):
        self.config = config
        self._base = config.llm_url.rstrip("/").removesuffix("/v1")
        self._cabecalhos = {"Authorization": f"Bearer {config.llm_chave}"}
        self._cliente = cliente or httpx.AsyncClient(timeout=LIMITE_S)
        self._modelo: str | None = config.llm_modelo
        self._falhou = False

    async def _post(self, caminho: str, corpo: dict) -> dict:
        r = await self._cliente.post(self._base + caminho, json=corpo, headers=self._cabecalhos)
        r.raise_for_status()
        return r.json()

    async def _tokens(self, sistema: str, ferramentas: list[dict], fala: str) -> list[int]:
        corpo = {
            "model": self._modelo,
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": fala}],
            "add_generation_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if ferramentas:
            corpo["tools"] = ferramentas
        return (await self._post("/tokenize", corpo))["tokens"]

    async def aquecer(self) -> int:
        """Aquece cada prefixo fixo; devolve o total de tokens enviados."""
        if self._modelo is None:
            r = await self._cliente.get(self._base + "/v1/models", headers=self._cabecalhos)
            r.raise_for_status()
            self._modelo = r.json()["data"][0]["id"]
        total = 0
        for sistema, ferramentas in llm.prefixos_fixos(self.config):
            a = await self._tokens(sistema, ferramentas, "a")
            b = await self._tokens(sistema, ferramentas, "Qual é o seu nome?")
            prefixo = _comum(a, b)
            if not prefixo:
                continue
            await self._post(
                "/v1/completions", {"model": self._modelo, "prompt": prefixo, "max_tokens": 1}
            )
            total += len(prefixo)
        return total

    async def tentar(self) -> None:
        """Uma rodada; falhas só vão para o log (uma vez até voltar a funcionar)."""
        t = time.perf_counter()
        try:
            total = await self.aquecer()
        except (httpx.HTTPError, KeyError, ValueError) as e:
            if not self._falhou:
                log.warning("aquecimento do cache do LLM falhou: %s", type(e).__name__)
            self._falhou = True
            return
        ms = round((time.perf_counter() - t) * 1000)
        if self._falhou:
            log.info("aquecimento do cache do LLM voltou: %d tokens em %d ms", total, ms)
        else:
            log.debug("cache do LLM aquecido: %d tokens em %d ms", total, ms)
        self._falhou = False

    async def rodar(self, disponivel) -> None:
        """Aquece agora e a cada INTERVALO_S, enquanto `disponivel()` disser que o LLM está
        no ar (depois de uma reinicialização do vLLM, o cache recomeça vazio)."""
        primeira = True
        while True:
            if disponivel():
                await self.tentar()
                if primeira:
                    log.info("aquecimento do cache do LLM ativo (a cada %.0f s)", INTERVALO_S)
                    primeira = False
            await asyncio.sleep(INTERVALO_S)

    async def fechar(self) -> None:
        await self._cliente.aclose()
