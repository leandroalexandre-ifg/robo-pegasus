"""Texto → resposta com o LLM servido pelo vLLM (API compatível com OpenAI)."""

import logging
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing

from openai import AsyncOpenAI

from app import persona
from app.config import Config
from app.pipeline.emocao import FERRAMENTA, Emocao, cortar_marcacoes, emocao_da_chamada

log = logging.getLogger("pegasus.llm")

_cliente: AsyncOpenAI | None = None
_modelo: str | None = None

# Sem modo de raciocínio (<think>), por latência.
_SEM_RACIOCINIO = {"chat_template_kwargs": {"enable_thinking": False}}
_TEM_TEXTO = re.compile(r"\w")


async def _preparar(config: Config) -> tuple[AsyncOpenAI, str]:
    global _cliente, _modelo
    if _cliente is None:
        _cliente = AsyncOpenAI(base_url=config.llm_url, api_key=config.llm_chave)
    if _modelo is None:
        _modelo = config.llm_modelo or (await _cliente.models.list()).data[0].id
    return _cliente, _modelo


Historico = Sequence[tuple[str, str]]  # (fala do usuário, resposta do robô), do mais antigo


def _mensagens(texto_usuario: str, sistema: str, historico: Historico = ()) -> list[dict]:
    mensagens = [{"role": "system", "content": sistema}]
    for usuario, robo in historico:
        mensagens += [{"role": "user", "content": usuario}, {"role": "assistant", "content": robo}]
    return mensagens + [{"role": "user", "content": texto_usuario}]


async def _fluxo(
    cliente: AsyncOpenAI,
    modelo: str,
    mensagens: list[dict],
    config: Config,
    chamadas: dict[int, dict] | None = None,
) -> AsyncIterator[str]:
    """Uma requisição em fluxo: devolve o texto e, se `chamadas` for dado, oferece a
    ferramenta definir_emocao e acumula ali as chamadas que o modelo fizer."""
    ferramentas = {} if chamadas is None else {"tools": [FERRAMENTA], "tool_choice": "auto"}
    fluxo = await cliente.chat.completions.create(
        model=modelo,
        messages=mensagens,
        **ferramentas,
        max_tokens=config.llm_max_tokens,
        temperature=config.llm_temperatura,
        stream=True,
        extra_body=_SEM_RACIOCINIO,
    )
    # O async with fecha a conexão se o consumidor parar antes do fim.
    async with fluxo:
        async for pedaco in fluxo:
            if not pedaco.choices:
                continue
            delta = pedaco.choices[0].delta
            if delta.content:
                yield delta.content
            for tc in getattr(delta, "tool_calls", None) or []:
                chamada = chamadas.setdefault(tc.index, {"id": None, "nome": "", "args": ""})
                chamada["id"] = tc.id or chamada["id"]
                if tc.function:
                    chamada["nome"] += tc.function.name or ""
                    chamada["args"] += tc.function.arguments or ""


async def _texto_limpo(fluxo: AsyncIterator[str]) -> AsyncIterator[str]:
    # Se o modelo imitar uma chamada de ferramenta no texto, a fala termina ali e
    # o aclosing interrompe a geração.
    async with aclosing(fluxo) as pedacos:
        async for pedaco in cortar_marcacoes(pedacos):
            yield pedaco


def _resultado_das_chamadas(chamadas: dict[int, dict]) -> list[dict]:
    """Mensagens que devolvem ao modelo as chamadas que ele fez, com resultado "ok"."""
    ids = {i: c["id"] or f"chamada-{i}" for i, c in chamadas.items()}
    assistente = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": ids[i],
                "type": "function",
                "function": {"name": c["nome"], "arguments": c["args"]},
            }
            for i, c in chamadas.items()
        ],
    }
    return [assistente] + [{"role": "tool", "tool_call_id": ids[i], "content": "ok"} for i in ids]


def _emocoes(chamadas: dict[int, dict]) -> list[Emocao]:
    emocoes = []
    for c in chamadas.values():
        if emocao := emocao_da_chamada(c["nome"], c["args"]):
            emocoes.append(emocao)
        else:
            # Os argumentos são texto livre do modelo: não vão para o log.
            log.warning("chamada de ferramenta ignorada: %s", c["nome"][:40])
    return emocoes


async def gerar(
    texto_usuario: str, config: Config, historico: Historico = ()
) -> AsyncIterator[str | Emocao]:
    """Devolve a fala em pedaços de texto, à medida que o LLM gera.

    No modo de emoção "antes", a requisição oferece a ferramenta definir_emocao e o
    prompt pede que ela seja chamada antes da resposta; a Emocao sai no fluxo assim
    que a chamada termina. No modo "paralelo", o fluxo é só texto, sem ferramentas,
    e a emoção vem de escolher_emocao. `historico` são os turnos anteriores da sessão."""
    cliente, modelo = await _preparar(config)
    if config.emocao_modo == "paralelo":
        async for pedaco in _texto_limpo(
            _fluxo(
                cliente,
                modelo,
                _mensagens(texto_usuario, persona.prompt_sistema(config), historico),
                config,
            )
        ):
            yield pedaco
        return

    sistema = f"{persona.prompt_sistema(config)}\n{persona.PROMPT_EMOCAO}"
    mensagens = _mensagens(texto_usuario, sistema, historico)
    chamadas: dict[int, dict] = {}
    falou = False
    async for pedaco in _texto_limpo(_fluxo(cliente, modelo, mensagens, config, chamadas)):
        falou = falou or bool(_TEM_TEXTO.search(pedaco))
        yield pedaco
    for emocao in _emocoes(chamadas):
        yield emocao

    if chamadas and not falou:
        # O Qwen3.8 encerra o turno logo após a chamada: devolve o resultado e pede
        # a fala numa segunda requisição. Ela vai sem a lista de ferramentas, porque
        # com tool_choice "none" o modelo ainda gera a chamada e o vLLM a descarta,
        # devolvendo texto vazio.
        mensagens += _resultado_das_chamadas(chamadas)
        async for pedaco in _texto_limpo(_fluxo(cliente, modelo, mensagens, config)):
            yield pedaco


async def escolher_emocao(
    texto_usuario: str, config: Config, historico: Historico = ()
) -> Emocao | None:
    """Modo "paralelo": pede ao LLM a chamada de definir_emocao para a fala do usuário.

    tool_choice nomeado obriga a chamada; devolve None se a resposta não trouxer uma
    emoção válida."""
    cliente, modelo = await _preparar(config)
    resposta = await cliente.chat.completions.create(
        model=modelo,
        messages=_mensagens(texto_usuario, persona.prompt_sistema(config), historico),
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
        log.warning("chamada de ferramenta ignorada: %s", chamada.function.name[:40])
    return None
