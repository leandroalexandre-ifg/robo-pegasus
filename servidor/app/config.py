"""Configuração do servidor, lida de variáveis de ambiente."""

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[2]
SERVIDOR = RAIZ_REPOSITORIO / "servidor"
MODELOS = RAIZ_REPOSITORIO / "modelos"


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
    emocao_espera_s: float  # quanto o primeiro áudio pode esperar pela emoção (paralelo)

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

    # Silero VAD: fim da fala sem listen_stop
    vad_limiar: float
    vad_silencio_s: float  # silêncio que encerra a fala
    vad_sem_fala_s: float  # escuta sem nenhuma fala que volta a ocioso

    # Como a escuta começa: "toque" (listen_start) ou "palavra" ("Pegasus", em escuta contínua)
    ativacao: str

    # Servidor WebSocket
    api_host: str
    api_porta: int
    tokens: frozenset[str] = field(repr=False)  # aceitos no hello; vazio recusa todos


MODOS_EMOCAO = ("antes", "paralelo")


def _modo_emocao(valor: str) -> str:
    if valor not in MODOS_EMOCAO:
        raise ValueError(f"PEGASUS_EMOCAO_MODO deve ser um de {MODOS_EMOCAO}, não {valor!r}")
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
        vad_limiar=float(env.get("PEGASUS_VAD_LIMIAR", "0.5")),
        vad_silencio_s=int(env.get("PEGASUS_VAD_SILENCIO_MS", "600")) / 1000,
        vad_sem_fala_s=int(env.get("PEGASUS_VAD_SEM_FALA_MS", "8000")) / 1000,
        ativacao=_modo_ativacao(env.get("PEGASUS_ATIVACAO", "toque")),
        api_host=env.get("PEGASUS_HOST", "127.0.0.1"),
        api_porta=int(env.get("PEGASUS_PORTA_API", "8100")),
        tokens=frozenset(t.strip() for t in env.get("PEGASUS_TOKENS", "").split(",") if t.strip()),
    )


def resumo_publico(config: Config) -> dict[str, object]:
    """Configuração que pode ir para o log: sem tokens nem chaves."""
    whisper = config.whisper_dispositivo
    if whisper == "cuda":
        whisper = f"cuda (GPU{config.whisper_gpu})"
    resumo: dict[str, object] = {
        "ativacao": config.ativacao,
        "emocao_modo": config.emocao_modo,
        "llm_modelo": config.llm_modelo or "(primeiro de /v1/models)",
        "api": f"{config.api_host}:{config.api_porta}",
        "voz": config.piper_voz.stem,
        "persona": str(config.persona_arquivo),
        "vad_silencio_ms": round(config.vad_silencio_s * 1000),
        "memoria_turnos": config.memoria_turnos,
        "whisper": f"{config.whisper_modelo}, {whisper}, {config.whisper_precisao}",
    }
    if config.emocao_modo == "paralelo":
        resumo["emocao_espera_ms"] = round(config.emocao_espera_s * 1000)
    return resumo
