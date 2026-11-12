"""Texto → resposta com o LLM servido pelo vLLM (API compatível com OpenAI)."""

import logging
import re
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import Config
from app.persona import PROMPT_SISTEMA
from app.pipeline.emocao import FERRAMENTA, Emocao, emocao_da_chamada, separar_marcacoes

log = logging.getLogger("pegasus.llm")

_cliente: AsyncOpenAI | None = None
_modelo: str | None = None
_TEM_TEXTO = re.compile(r"\w")


async def _preparar(config: Config) -> tuple[AsyncOpenAI, str]:
    global _cliente, _modelo
    if _cliente is None:
        _cliente = AsyncOpenAI(base_url=config.llm_url, api_key=config.llm_chave)
    if _modelo is None:
        _modelo = config.llm_modelo or (await _cliente.models.list()).data[0].id
    return _cliente, _modelo


async def _rodada(
    cliente: AsyncOpenAI,
    modelo: str,
    mensagens: list[dict],
    config: Config,
    chamadas: dict[int, dict],
    com_ferramenta: bool,
) -> AsyncIterator[str]:
    """Uma requisição em fluxo: devolve o texto e acumula as chamadas de ferramenta."""
    # Sem a lista de ferramentas o modelo não tem como chamá-las. Com tool_choice
    # "none" ele ainda gera a chamada e o vLLM só a descarta, devolvendo texto vazio.
    ferramentas = {"tools": [FERRAMENTA], "tool_choice": "auto"} if com_ferramenta else {}
    fluxo = await cliente.chat.completions.create(
        model=modelo,
        messages=mensagens,
        **ferramentas,
        max_tokens=config.llm_max_tokens,
        temperature=config.llm_temperatura,
        stream=True,
        # Sem modo de raciocínio (<think>), por latência.
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    # O async with fecha a conexão se o consumidor parar antes do fim (interrupção).
    async with fluxo:
        async for pedaco in fluxo:
            if not pedaco.choices:
                continue
            delta = pedaco.choices[0].delta
            if delta.content:
                yield delta.content
            for tc in delta.tool_calls or []:
                chamada = chamadas.setdefault(tc.index, {"id": None, "nome": "", "args": ""})
                chamada["id"] = tc.id or chamada["id"]
                if tc.function:
                    chamada["nome"] += tc.function.name or ""
                    chamada["args"] += tc.function.arguments or ""


def _emocoes(chamadas: dict[int, dict]) -> list[Emocao]:
    emocoes = []
    for chamada in chamadas.values():
        if emocao := emocao_da_chamada(chamada["nome"], chamada["args"]):
            emocoes.append(emocao)
        else:
            log.warning("chamada de ferramenta ignorada: %s(%s)", chamada["nome"], chamada["args"])
    return emocoes


async def gerar(texto_usuario: str, config: Config) -> AsyncIterator[str | Emocao]:
    """Devolve a resposta em pedaços de texto, à medida que o LLM gera, e as
    emoções pedidas pela ferramenta definir_emocao. O texto já vem sem marcações
    de ferramenta."""
    cliente, modelo = await _preparar(config)
    mensagens = [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": texto_usuario},
    ]
    chamadas: dict[int, dict] = {}
    falou = False
    rodada = _rodada(cliente, modelo, mensagens, config, chamadas, com_ferramenta=True)
    async for item in separar_marcacoes(rodada):
        falou = falou or (isinstance(item, str) and bool(_TEM_TEXTO.search(item)))
        yield item
    for emocao in _emocoes(chamadas):
        yield emocao

    if chamadas and not falou:
        # O modelo chamou a ferramenta e encerrou o turno sem falar: devolve o
        # resultado da ferramenta e pede a fala, agora sem a ferramenta disponível.
        mensagens.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": c["id"] or f"chamada-{i}",
                        "type": "function",
                        "function": {"name": c["nome"], "arguments": c["args"]},
                    }
                    for i, c in chamadas.items()
                ],
            }
        )
        mensagens.extend(
            {"role": "tool", "tool_call_id": c["id"] or f"chamada-{i}", "content": "ok"}
            for i, c in chamadas.items()
        )
        rodada = _rodada(cliente, modelo, mensagens, config, {}, com_ferramenta=False)
        async for item in separar_marcacoes(rodada):
            yield item
