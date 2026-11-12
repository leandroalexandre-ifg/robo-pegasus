"""Configuração do servidor, lida de variáveis de ambiente."""

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[2]
MODELOS = RAIZ_REPOSITORIO / "modelos"


@dataclass(frozen=True)
class Config:
    # LLM (vLLM, API compatível com OpenAI)
    llm_url: str
    llm_chave: str = field(repr=False)
    llm_modelo: str | None  # None: usa o primeiro modelo de /v1/models
    llm_max_tokens: int
    llm_temperatura: float
    emocao_espera_s: float  # quanto o primeiro áudio pode esperar pela emoção

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

    # Servidor WebSocket
    api_host: str
    api_porta: int
    tokens: frozenset[str] = field(repr=False)  # aceitos no hello; vazio recusa todos


def carregar_config(ambiente: dict[str, str] | None = None) -> Config:
    env = os.environ if ambiente is None else ambiente
    return Config(
        llm_url=env.get("PEGASUS_LLM_URL", "http://127.0.0.1:8101/v1"),
        llm_chave=env.get("PEGASUS_LLM_CHAVE", "EMPTY"),
        llm_modelo=env.get("PEGASUS_MODELO") or None,
        llm_max_tokens=int(env.get("PEGASUS_LLM_MAX_TOKENS", "150")),
        llm_temperatura=float(env.get("PEGASUS_LLM_TEMPERATURA", "0.7")),
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
        api_host=env.get("PEGASUS_HOST", "127.0.0.1"),
        api_porta=int(env.get("PEGASUS_PORTA_API", "8100")),
        tokens=frozenset(t.strip() for t in env.get("PEGASUS_TOKENS", "").split(",") if t.strip()),
    )
