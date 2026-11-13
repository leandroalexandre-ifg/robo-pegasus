"""Configuração do servidor, lida de variáveis de ambiente."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.ferramentas import NOMES as NOMES_FERRAMENTAS
from app.seguranca import carregar_tablets

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[2]
SERVIDOR = RAIZ_REPOSITORIO / "servidor"
MODELOS = RAIZ_REPOSITORIO / "modelos"
_PASTA_ESTADO = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")


@dataclass(frozen=True)
class Config:
    # LLM (vLLM, API compatível com OpenAI)
    llm_url: str
    llm_chave: str = field(repr=False)
    llm_modelo: str | None  # None: usa o primeiro modelo de /v1/models
    llm_max_tokens: int
    llm_temperatura: float
    emocao_modo: str  # "antes": a fala chama a ferramenta; "paralelo": requisição própria
    memoria_turnos: int  # turnos anteriores da sessão enviados ao LLM
    memoria_s: float  # a memória é zerada depois disso sem conversa; 0: só ao desconectar
    emocao_espera_s: float  # prazo da emoção depois do primeiro áudio (paralelo); depois, neutro

    # Whisper (faster-whisper)
    whisper_modelo: str
    whisper_dispositivo: str  # "cuda" ou "cpu"
    whisper_gpu: str  # índice físico da GPU; nunca a GPU0 (SciTech Ear)
    whisper_precisao: str  # compute_type do CTranslate2
    whisper_cache: Path
    whisper_idioma: str
    whisper_beam: int
    whisper_prompt: str | None  # vocabulário que o Whisper deve esperar

    # Piper
    piper_voz: Path

    # Persona (arquivo TOML editável, lido na subida)
    persona_arquivo: Path

    # Ferramentas do LLM (PEGASUS_FERRAMENTAS); vazio: nenhuma
    ferramentas: tuple[str, ...]
    fuso: str  # fuso horário do "[agora: …]" e do clima
    cidade: str  # cidade do clima quando a pessoa não diz qual

    # Silero VAD: fim da fala sem listen_stop
    vad_limiar: float
    vad_silencio_s: float  # silêncio que encerra a fala
    vad_previa_s: float  # silêncio com que o turno já começa, sem enviar nada; 0 desliga
    vad_sem_fala_s: float  # escuta sem nenhuma fala que volta a ocioso
    conversa_s: float  # modo palavra: escuta aberta depois de cada resposta; 0 desliga

    # Limites de tempo de cada etapa. A etapa que passa do limite encerra o turno com erro.
    stt_limite_s: float  # transcrição de uma fala
    llm_limite_s: float  # espera por cada pedaço do fluxo do LLM (inclui o primeiro)
    tts_limite_s: float  # síntese de uma frase
    turno_limite_s: float  # turno inteiro, do fim da fala ao último áudio

    # Registro dos turnos (só tempos e contagens), em arquivo rotacionado diariamente
    log_pasta: Path
    log_dias: int  # arquivos antigos guardados

    # Como a escuta começa: "toque" (listen_start) ou "palavra" ("Pegasus", em escuta contínua)
    ativacao: str

    # Servidor WebSocket
    api_host: str
    api_porta: int
    max_sessoes: int  # tablets conectados ao mesmo tempo (uma sessão por token)
    # Proxies confiáveis (o Caddy): só deles vale o X-Forwarded-For
    proxies: frozenset[str]
    # (nome, token) de cada tablet, de PEGASUS_TABLETS; vazio recusa todos
    tablets: tuple[tuple[str, str], ...] = field(repr=False)


MODOS_EMOCAO = ("antes", "paralelo")


def _modo_emocao(valor: str) -> str:
    if valor not in MODOS_EMOCAO:
        raise ValueError(f"PEGASUS_EMOCAO_MODO deve ser um de {MODOS_EMOCAO}, não {valor!r}")
    return valor


def _ferramentas(valor: str) -> tuple[str, ...]:
    nomes = tuple(dict.fromkeys(n.strip() for n in valor.split(",") if n.strip()))
    if desconhecidas := [n for n in nomes if n not in NOMES_FERRAMENTAS]:
        raise ValueError(
            f"PEGASUS_FERRAMENTAS: desconhecidas {desconhecidas}; válidas: {NOMES_FERRAMENTAS}"
        )
    return nomes


def _fuso(valor: str) -> str:
    try:
        ZoneInfo(valor)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"PEGASUS_FUSO: fuso horário desconhecido: {valor!r}") from None
    return valor


MODOS_ATIVACAO = ("toque", "palavra")


def _modo_ativacao(valor: str) -> str:
    if valor not in MODOS_ATIVACAO:
        raise ValueError(f"PEGASUS_ATIVACAO deve ser um de {MODOS_ATIVACAO}, não {valor!r}")
    return valor


def carregar_config(ambiente: dict[str, str] | None = None) -> Config:
    env = os.environ if ambiente is None else ambiente
    return Config(
        llm_url=env.get("PEGASUS_LLM_URL", "http://127.0.0.1:8101/v1"),
        llm_chave=env.get("PEGASUS_LLM_CHAVE", "EMPTY"),
        llm_modelo=env.get("PEGASUS_MODELO") or None,
        llm_max_tokens=int(env.get("PEGASUS_LLM_MAX_TOKENS", "150")),
        llm_temperatura=float(env.get("PEGASUS_LLM_TEMPERATURA", "0.7")),
        memoria_turnos=int(env.get("PEGASUS_MEMORIA_TURNOS", "6")),
        memoria_s=float(env.get("PEGASUS_MEMORIA_S", "180")),
        emocao_modo=_modo_emocao(env.get("PEGASUS_EMOCAO_MODO", "antes")),
        emocao_espera_s=int(env.get("PEGASUS_EMOCAO_ESPERA_MS", "1000")) / 1000,
        whisper_modelo=env.get("PEGASUS_WHISPER_MODELO", "large-v3-turbo"),
        whisper_dispositivo=env.get("PEGASUS_WHISPER_DISPOSITIVO", "cuda"),
        whisper_gpu=env.get("PEGASUS_WHISPER_GPU", "1"),
        whisper_precisao=env.get("PEGASUS_WHISPER_PRECISAO", "float16"),
        whisper_cache=Path(env.get("PEGASUS_WHISPER_CACHE", str(MODELOS / "hub"))),
        whisper_idioma=env.get("PEGASUS_WHISPER_IDIOMA", "pt"),
        whisper_beam=int(env.get("PEGASUS_WHISPER_BEAM", "1")),
        whisper_prompt=env.get("PEGASUS_WHISPER_PROMPT", "robô, Pegasus") or None,
        piper_voz=Path(
            env.get("PEGASUS_PIPER_VOZ", str(MODELOS / "piper" / "pt_BR-faber-medium.onnx"))
        ),
        persona_arquivo=Path(env.get("PEGASUS_PERSONA", str(SERVIDOR / "persona.toml"))),
        ferramentas=_ferramentas(env.get("PEGASUS_FERRAMENTAS", "")),
        fuso=_fuso(env.get("PEGASUS_FUSO", "America/Sao_Paulo")),
        cidade=env.get("PEGASUS_CIDADE", "Goiânia").strip() or "Goiânia",
        vad_limiar=float(env.get("PEGASUS_VAD_LIMIAR", "0.5")),
        vad_silencio_s=int(env.get("PEGASUS_VAD_SILENCIO_MS", "600")) / 1000,
        vad_previa_s=int(env.get("PEGASUS_VAD_PREVIA_MS", "300")) / 1000,
        vad_sem_fala_s=int(env.get("PEGASUS_VAD_SEM_FALA_MS", "8000")) / 1000,
        conversa_s=float(env.get("PEGASUS_CONVERSA_S", "8")),
        stt_limite_s=int(env.get("PEGASUS_STT_LIMITE_MS", "5000")) / 1000,
        llm_limite_s=int(env.get("PEGASUS_LLM_LIMITE_MS", "10000")) / 1000,
        tts_limite_s=int(env.get("PEGASUS_TTS_LIMITE_MS", "5000")) / 1000,
        turno_limite_s=int(env.get("PEGASUS_TURNO_LIMITE_MS", "60000")) / 1000,
        log_pasta=Path(env.get("PEGASUS_LOG_PASTA", str(_PASTA_ESTADO / "robo-pegasus"))),
        log_dias=int(env.get("PEGASUS_LOG_DIAS", "30")),
        ativacao=_modo_ativacao(env.get("PEGASUS_ATIVACAO", "toque")),
        api_host=env.get("PEGASUS_HOST", "127.0.0.1"),
        api_porta=int(env.get("PEGASUS_PORTA_API", "8100")),
        max_sessoes=int(env.get("PEGASUS_MAX_SESSOES", "4")),
        proxies=frozenset(
            p.strip() for p in env.get("PEGASUS_PROXIES", "127.0.0.1,::1").split(",") if p.strip()
        ),
        tablets=carregar_tablets(env.get("PEGASUS_TABLETS", "")),
    )


def resumo_publico(config: Config) -> dict[str, object]:
    """Configuração que pode ir para o log: sem tokens nem chaves."""
    whisper = config.whisper_dispositivo
    if whisper == "cuda":
        whisper = f"cuda (GPU{config.whisper_gpu})"
    resumo: dict[str, object] = {
        "ativacao": config.ativacao,
        "tablets": [nome for nome, _ in config.tablets],
        "max_sessoes": config.max_sessoes,
        "conversa_s": config.conversa_s,
        "emocao_modo": config.emocao_modo,
        "llm_modelo": config.llm_modelo or "(primeiro de /v1/models)",
        "api": f"{config.api_host}:{config.api_porta}",
        "voz": config.piper_voz.stem,
        "persona": str(config.persona_arquivo),
        "ferramentas": list(config.ferramentas) or "nenhuma",
        "fuso": config.fuso,
        "cidade": config.cidade,
        "vad_silencio_ms": round(config.vad_silencio_s * 1000),
        "vad_previa_ms": round(config.vad_previa_s * 1000),
        "memoria_turnos": config.memoria_turnos,
        "memoria_s": config.memoria_s,
        "log_turnos": f"{config.log_pasta} ({config.log_dias} dias)",
        "whisper": f"{config.whisper_modelo}, {whisper}, {config.whisper_precisao}",
    }
    if config.emocao_modo == "paralelo":
        resumo["emocao_espera_ms"] = round(config.emocao_espera_s * 1000)
    return resumo
