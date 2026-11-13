"""Texto → resposta com o LLM servido pelo vLLM (API compatível com OpenAI)."""

import logging
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing

import httpx
from openai import AsyncOpenAI

from app import ferramentas as ferramentas_rede
from app import persona
from app.config import Config
from app.ferramentas import Consulta, Espera
from app.ferramentas.agora import agora
from app.pipeline.emocao import FERRAMENTA, Emocao, cortar_marcacoes, emocao_da_chamada

log = logging.getLogger("pegasus.llm")

_cliente: AsyncOpenAI | None = None
_modelo: str | None = None

# Sem modo de raciocínio (<think>), por latência.
_SEM_RACIOCINIO = {"chat_template_kwargs": {"enable_thinking": False}}
_TEM_TEXTO = re.compile(r"\w")
LIMITE_CONEXAO_S = 2.0
_INDISPONIVEL = '{"erro": "ferramenta indisponível"}'


async def _preparar(config: Config) -> tuple[AsyncOpenAI, str]:
    global _cliente, _modelo
    if _cliente is None:
        _cliente = AsyncOpenAI(
            base_url=config.llm_url,
            api_key=config.llm_chave,
            # read vale para cada pedaço do fluxo, inclusive o primeiro token.
            timeout=httpx.Timeout(config.llm_limite_s, connect=LIMITE_CONEXAO_S),
            # Sem novas tentativas: com o vLLM fora, o turno falha na hora e o
            # monitor de saúde avisa os tablets.
            max_retries=0,
        )
    if _modelo is None:
        _modelo = config.llm_modelo or (await _cliente.models.list()).data[0].id
    return _cliente, _modelo


Historico = Sequence[tuple[str, str]]  # (fala do usuário, resposta do robô), do mais antigo

PROMPT_AGORA = (
    "A mensagem do usuário começa com a data e a hora atuais entre colchetes, como "
    "[agora: …]. Use-as só quando a pergunta precisar delas e não fale da data nem da hora "
    "sem que perguntem."
)


def _sistema(config: Config) -> str:
    sistema = persona.prompt_sistema(config)
    if "data_hora" in config.ferramentas:
        sistema += f"\n{PROMPT_AGORA}"
    return sistema


def _fala_atual(texto_usuario: str, config: Config) -> str:
    """A fala do usuário, com a data e a hora na frente se data_hora estiver ligada.
    Só a fala atual: o histórico vai sem elas, e o começo do prompt não muda."""
    if "data_hora" not in config.ferramentas:
        return texto_usuario
    return f"[agora: {agora(config.fuso)}]\n{texto_usuario}"


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
    oferecidas: Sequence[dict] = (),
    continuar: bool = False,
) -> AsyncIterator[str | Espera]:
    """Uma requisição em fluxo: devolve o texto e acumula em `chamadas` as chamadas
    das ferramentas `oferecidas`. Ao começar uma chamada de ferramenta de rede, devolve
    Espera (antes dos argumentos). Com `continuar`, a última mensagem (do assistente)
    é continuada em vez de começar uma resposta nova."""
    ferramentas = {"tools": list(oferecidas), "tool_choice": "auto"} if oferecidas else {}
    extra = _SEM_RACIOCINIO
    if continuar:
        extra = extra | {"continue_final_message": True, "add_generation_prompt": False}
    fluxo = await cliente.chat.completions.create(
        model=modelo,
        messages=mensagens,
        **ferramentas,
        max_tokens=config.llm_max_tokens,
        temperature=config.llm_temperatura,
        stream=True,
        extra_body=extra,
    )
    de_rede = {f["function"]["name"] for f in oferecidas} & set(ferramentas_rede.DE_REDE)
    avisadas: set[int] = set()
    # O async with fecha a conexão se o consumidor parar antes do fim.
    async with fluxo:
        async for pedaco in fluxo:
            if not pedaco.choices:
                continue
            delta = pedaco.choices[0].delta
            if delta.content:
                yield delta.content
            for tc in getattr(delta, "tool_calls", None) or []:
                if chamadas is None:
                    continue
                chamada = chamadas.setdefault(tc.index, {"id": None, "nome": "", "args": ""})
                chamada["id"] = tc.id or chamada["id"]
                if tc.function:
                    chamada["nome"] += tc.function.name or ""
                    chamada["args"] += tc.function.arguments or ""
                if tc.index not in avisadas and chamada["nome"] in de_rede:
                    avisadas.add(tc.index)
                    yield Espera(chamada["nome"])


async def _texto_limpo[T](fluxo: AsyncIterator[str | T]) -> AsyncIterator[str | T]:
    # Se o modelo imitar uma chamada de ferramenta no texto, a fala termina ali e
    # o aclosing interrompe a geração.
    async with aclosing(fluxo) as pedacos:
        async for pedaco in cortar_marcacoes(pedacos):
            yield pedaco


def _resultado_das_chamadas(
    chamadas: dict[int, dict], resultados: dict[int, str], dito: str = ""
) -> list[dict]:
    """Mensagens que devolvem ao modelo as chamadas que ele fez e os resultados
    ("ok" para definir_emocao; erro para uma ferramenta que não está ligada)."""
    ids = {i: c["id"] or f"chamada-{i}" for i, c in chamadas.items()}
    assistente = {
        "role": "assistant",
        "content": dito or None,
        "tool_calls": [
            {
                "id": ids[i],
                "type": "function",
                "function": {"name": c["nome"], "arguments": c["args"]},
            }
            for i, c in chamadas.items()
        ],
    }

    def resultado(i: int) -> str:
        if i in resultados:
            return resultados[i]
        return "ok" if chamadas[i]["nome"] == FERRAMENTA["function"]["name"] else _INDISPONIVEL

    return [assistente] + [
        {"role": "tool", "tool_call_id": ids[i], "content": resultado(i)} for i in ids
    ]


def _emocoes(chamadas: dict[int, dict], rede: Sequence[str]) -> list[Emocao]:
    emocoes = []
    for c in chamadas.values():
        if c["nome"] in rede:
            continue
        if emocao := emocao_da_chamada(c["nome"], c["args"]):
            emocoes.append(emocao)
        else:
            # Os argumentos são texto livre do modelo: não vão para o log.
            log.warning("chamada de ferramenta ignorada: %s", c["nome"][:40])
    return emocoes


async def _depois_das_consultas(
    cliente: AsyncOpenAI,
    modelo: str,
    mensagens: list[dict],
    config: Config,
    consultas: list[Consulta],
) -> AsyncIterator[str]:
    """Segunda requisição, sem ferramentas, com os resultados. Se alguma fonte deu
    resultado, a fala começa citando-a ("Segundo a Wikipédia,"): o texto vai na
    mensagem do assistente e o LLM continua a frase. A citação só sai junto com o
    primeiro pedaço do LLM; se a continuação vier vazia, repete sem a citação."""
    if citacao := ferramentas_rede.citacao(consultas):
        com_citacao = mensagens + [{"role": "assistant", "content": citacao}]
        citada = False
        async for pedaco in _texto_limpo(
            _fluxo(cliente, modelo, com_citacao, config, continuar=True)
        ):
            if not citada and _TEM_TEXTO.search(pedaco):
                citada = True
                # A continuação às vezes já vem com o espaço; outras, não.
                yield citacao if pedaco[:1].isspace() else f"{citacao} "
            if citada:
                yield pedaco
        if citada:
            return
        log.warning("o LLM não continuou a citação; repetindo sem ela")
    async for pedaco in _texto_limpo(_fluxo(cliente, modelo, mensagens, config)):
        yield pedaco


def _prompt_da_fala(config: Config) -> tuple[str, list[dict]]:
    """Prompt de sistema e ferramentas da requisição da fala: o começo fixo do prompt,
    igual em todo turno (o aquecimento do cache usa o mesmo)."""
    oferecidas = ferramentas_rede.definicoes(config)
    sistema = _sistema(config)
    if config.emocao_modo == "antes":
        oferecidas = [FERRAMENTA, *oferecidas]
        sistema += f"\n{persona.PROMPT_EMOCAO}"
    if ferramentas_rede.ativas_de_rede(config):
        sistema += f"\n{ferramentas_rede.PROMPT}"
    return sistema, oferecidas


def prefixos_fixos(config: Config) -> list[tuple[str, list[dict]]]:
    """(sistema, ferramentas) de cada tipo de requisição: a da fala, a segunda rodada
    depois de uma consulta (sem ferramentas) e a da emoção em paralelo."""
    sistema, oferecidas = _prompt_da_fala(config)
    prefixos = [(sistema, oferecidas)]
    if oferecidas:
        prefixos.append((sistema, []))
    if config.emocao_modo == "paralelo":
        prefixos.append((persona.prompt_sistema(config), [FERRAMENTA]))
    return prefixos


async def gerar(
    texto_usuario: str, config: Config, historico: Historico = ()
) -> AsyncIterator[str | Emocao | Espera | Consulta]:
    """Devolve a fala em pedaços de texto, à medida que o LLM gera.

    No modo de emoção "antes", a requisição oferece a ferramenta definir_emocao e o
    prompt pede que ela seja chamada antes da resposta; a Emocao sai no fluxo assim
    que a chamada termina. No modo "paralelo", a emoção vem de escolher_emocao.

    Com ferramentas de rede ligadas (PEGASUS_FERRAMENTAS), elas também são oferecidas.
    Se o LLM chamar uma, sai Espera (o robô pode dizer "Deixa eu ver…"), a consulta é
    feita, sai a Consulta (para o registro) e a fala vem numa segunda requisição, sem
    ferramentas: um texto de página não consegue disparar outra chamada.
    `historico` são os turnos anteriores da sessão."""
    cliente, modelo = await _preparar(config)
    rede = ferramentas_rede.ativas_de_rede(config)
    sistema, oferecidas = _prompt_da_fala(config)
    mensagens = _mensagens(_fala_atual(texto_usuario, config), sistema, historico)
    if not oferecidas:
        async for pedaco in _texto_limpo(_fluxo(cliente, modelo, mensagens, config)):
            yield pedaco
        return

    chamadas: dict[int, dict] = {}
    dito: list[str] = []
    async for pedaco in _texto_limpo(
        _fluxo(cliente, modelo, mensagens, config, chamadas, oferecidas)
    ):
        if isinstance(pedaco, str):
            dito.append(pedaco)
        yield pedaco
    falou = bool(_TEM_TEXTO.search("".join(dito)))
    for emocao in _emocoes(chamadas, rede):
        yield emocao

    consultar = {i: c for i, c in chamadas.items() if c["nome"] in rede}
    if consultar:
        consultas = await ferramentas_rede.executar(
            [(c["nome"], c["args"]) for c in consultar.values()], config
        )
        for consulta in consultas:
            yield consulta
        resultados = dict(zip(consultar, (c.texto for c in consultas), strict=False))
        for i in list(consultar)[len(consultas) :]:  # além do máximo por turno
            resultados[i] = '{"erro": "uma consulta por vez"}'
        # O que já foi dito antes da chamada ("Vou verificar.") volta ao modelo como
        # parte da mensagem dele, para a continuação não repetir nem contradizer.
        mensagens += _resultado_das_chamadas(chamadas, resultados, "".join(dito).strip())
        async for pedaco in _depois_das_consultas(cliente, modelo, mensagens, config, consultas):
            yield pedaco
    elif chamadas and not falou:
        # O Qwen3.8 encerra o turno logo após a chamada: devolve o resultado e pede
        # a fala numa segunda requisição. Ela vai sem a lista de ferramentas, porque
        # com tool_choice "none" o modelo ainda gera a chamada e o vLLM a descarta,
        # devolvendo texto vazio.
        mensagens += _resultado_das_chamadas(chamadas, {})
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
        # Sem o "[agora: …]": a emoção não depende dele, e o prompt menor pesa menos na
        # GPU enquanto a fala é gerada ao mesmo tempo.
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
