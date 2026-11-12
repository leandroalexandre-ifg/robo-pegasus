"""Texto → resposta com o LLM servido pelo vLLM (API compatível com OpenAI)."""

import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import Config
from app.persona import PROMPT_SISTEMA

_cliente: AsyncOpenAI | None = None
_modelo: str | None = None


@dataclass
class RespostaLLM:
    texto: str
    primeiro_token_s: float | None


async def _preparar(config: Config) -> tuple[AsyncOpenAI, str]:
    global _cliente, _modelo
    if _cliente is None:
        _cliente = AsyncOpenAI(base_url=config.llm_url, api_key=config.llm_chave)
    if _modelo is None:
        _modelo = config.llm_modelo or (await _cliente.models.list()).data[0].id
    return _cliente, _modelo


async def responder(texto_usuario: str, config: Config) -> RespostaLLM:
    """Gera a resposta em fluxo e mede o tempo até o primeiro token."""
    cliente, modelo = await _preparar(config)
    inicio = time.perf_counter()
    fluxo = await cliente.chat.completions.create(
        model=modelo,
        messages=[
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": texto_usuario},
        ],
        max_tokens=config.llm_max_tokens,
        temperature=config.llm_temperatura,
        stream=True,
        # Sem modo de raciocínio (<think>), por latência.
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    partes: list[str] = []
    primeiro_token_s = None
    async for pedaco in fluxo:
        if not pedaco.choices:
            continue
        delta = pedaco.choices[0].delta.content
        if delta:
            if primeiro_token_s is None:
                primeiro_token_s = time.perf_counter() - inicio
            partes.append(delta)
    return RespostaLLM("".join(partes).strip(), primeiro_token_s)
