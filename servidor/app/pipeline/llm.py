"""Texto → resposta com o LLM servido pelo vLLM (API compatível com OpenAI)."""

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing

from openai import AsyncOpenAI

from app.config import Config
from app.persona import PROMPT_SISTEMA
from app.pipeline.emocao import FERRAMENTA, Emocao, cortar_marcacoes, emocao_da_chamada

log = logging.getLogger("pegasus.llm")

_cliente: AsyncOpenAI | None = None
_modelo: str | None = None

# Sem modo de raciocínio (<think>), por latência.
_SEM_RACIOCINIO = {"chat_template_kwargs": {"enable_thinking": False}}


async def _preparar(config: Config) -> tuple[AsyncOpenAI, str]:
    global _cliente, _modelo
    if _cliente is None:
        _cliente = AsyncOpenAI(base_url=config.llm_url, api_key=config.llm_chave)
    if _modelo is None:
        _modelo = config.llm_modelo or (await _cliente.models.list()).data[0].id
    return _cliente, _modelo


def _mensagens(texto_usuario: str) -> list[dict]:
    return [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": texto_usuario},
    ]


async def _texto(cliente: AsyncOpenAI, modelo: str, texto: str, config: Config):
    fluxo = await cliente.chat.completions.create(
        model=modelo,
        messages=_mensagens(texto),
        max_tokens=config.llm_max_tokens,
        temperature=config.llm_temperatura,
        stream=True,
        extra_body=_SEM_RACIOCINIO,
    )
    # O async with fecha a conexão se o consumidor parar antes do fim.
    async with fluxo:
        async for pedaco in fluxo:
            if pedaco.choices and (delta := pedaco.choices[0].delta.content):
                yield delta


async def gerar(texto_usuario: str, config: Config) -> AsyncIterator[str]:
    """Devolve a fala em pedaços de texto, à medida que o LLM gera.

    A requisição vai sem ferramentas, para o primeiro token sair rápido; a emoção
    é escolhida à parte, por escolher_emocao. Se o modelo imitar uma chamada de
    ferramenta no texto, a fala termina ali e a geração é interrompida."""
    cliente, modelo = await _preparar(config)
    async with aclosing(_texto(cliente, modelo, texto_usuario, config)) as pedacos:
        async for pedaco in cortar_marcacoes(pedacos):
            yield pedaco


async def escolher_emocao(texto_usuario: str, config: Config) -> Emocao | None:
    """Pede ao LLM a chamada da ferramenta definir_emocao para a fala do usuário.

    Roda em paralelo com gerar. tool_choice nomeado obriga a chamada; devolve None se
    a resposta não trouxer uma emoção válida."""
    cliente, modelo = await _preparar(config)
    resposta = await cliente.chat.completions.create(
        model=modelo,
        messages=_mensagens(texto_usuario),
        tools=[FERRAMENTA],
        tool_choice={"type": "function", "function": {"name": FERRAMENTA["function"]["name"]}},
        # O Qwen3.8 escreve a chamada no formato XML: ~32 tokens.
        max_tokens=64,
        temperature=0.3,
        extra_body=_SEM_RACIOCINIO,
    )
    for chamada in resposta.choices[0].message.tool_calls or []:
        if emocao := emocao_da_chamada(chamada.function.name, chamada.function.arguments):
            return emocao
        log.warning(
            "chamada de ferramenta ignorada: %s(%s)",
            chamada.function.name,
            chamada.function.arguments,
        )
    return None
