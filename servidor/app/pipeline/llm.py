"""Texto → resposta com o LLM servido pelo vLLM (API compatível com OpenAI)."""

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import Config
from app.persona import PROMPT_SISTEMA

_cliente: AsyncOpenAI | None = None
_modelo: str | None = None


async def _preparar(config: Config) -> tuple[AsyncOpenAI, str]:
    global _cliente, _modelo
    if _cliente is None:
        _cliente = AsyncOpenAI(base_url=config.llm_url, api_key=config.llm_chave)
    if _modelo is None:
        _modelo = config.llm_modelo or (await _cliente.models.list()).data[0].id
    return _cliente, _modelo


async def gerar(texto_usuario: str, config: Config) -> AsyncIterator[str]:
    """Devolve a resposta em pedaços de texto, à medida que o LLM gera."""
    cliente, modelo = await _preparar(config)
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
    # O async with fecha a conexão se o consumidor parar antes do fim (interrupção).
    async with fluxo:
        async for pedaco in fluxo:
            if pedaco.choices and (delta := pedaco.choices[0].delta.content):
                yield delta
