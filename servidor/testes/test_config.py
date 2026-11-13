from pathlib import Path

import pytest

from app.config import MODELOS, SERVIDOR, carregar_config, resumo_publico


def test_padroes():
    c = carregar_config({})
    assert c.llm_url == "http://127.0.0.1:8101/v1"
    assert c.llm_modelo is None
    assert c.whisper_gpu == "1"
    assert c.whisper_idioma == "pt"
    assert c.whisper_prompt == "robô, Pegasus"
    assert c.piper_voz == MODELOS / "piper" / "pt_BR-faber-medium.onnx"


def test_sobrescreve_pelo_ambiente():
    c = carregar_config(
        {
            "PEGASUS_LLM_URL": "http://outro:9000/v1",
            "PEGASUS_MODELO": "qwen-teste",
            "PEGASUS_WHISPER_PRECISAO": "int8_float16",
            "PEGASUS_PIPER_VOZ": "/tmp/voz.onnx",
            "PEGASUS_LLM_MAX_TOKENS": "80",
            "PEGASUS_WHISPER_PROMPT": "",
        }
    )
    assert c.llm_url == "http://outro:9000/v1"
    assert c.llm_modelo == "qwen-teste"
    assert c.whisper_precisao == "int8_float16"
    assert c.piper_voz == Path("/tmp/voz.onnx")
    assert c.llm_max_tokens == 80
    assert c.whisper_prompt is None


def test_servidor_e_tokens():
    c = carregar_config({"PEGASUS_TOKENS": " abc , def,, "})
    assert (c.api_host, c.api_porta) == ("127.0.0.1", 8100)
    assert c.tokens == frozenset({"abc", "def"})
    assert carregar_config({}).tokens == frozenset()


def test_segredos_fora_do_repr():
    c = carregar_config({"PEGASUS_TOKENS": "segredo-tablet", "PEGASUS_LLM_CHAVE": "segredo-llm"})
    assert "segredo" not in repr(c)


def test_modo_da_emocao():
    assert carregar_config({}).emocao_modo == "antes"
    assert carregar_config({"PEGASUS_EMOCAO_MODO": "paralelo"}).emocao_modo == "paralelo"
    with pytest.raises(ValueError, match="PEGASUS_EMOCAO_MODO"):
        carregar_config({"PEGASUS_EMOCAO_MODO": "depois"})


def test_modo_da_ativacao():
    assert carregar_config({}).ativacao == "toque"
    assert carregar_config({"PEGASUS_ATIVACAO": "palavra"}).ativacao == "palavra"
    with pytest.raises(ValueError, match="PEGASUS_ATIVACAO"):
        carregar_config({"PEGASUS_ATIVACAO": "voz"})


def test_resumo_publico_sem_segredos():
    c = carregar_config(
        {
            "PEGASUS_TOKENS": "segredo-tablet",
            "PEGASUS_LLM_CHAVE": "segredo-llm",
            "PEGASUS_MODELO": "qwen-teste",
            "PEGASUS_EMOCAO_MODO": "paralelo",
        }
    )
    resumo = resumo_publico(c)
    assert resumo == {
        "ativacao": "toque",
        "emocao_modo": "paralelo",
        "llm_modelo": "qwen-teste",
        "api": "127.0.0.1:8100",
        "voz": "pt_BR-faber-medium",
        "persona": str(SERVIDOR / "persona.toml"),
        "vad_silencio_ms": 600,
        "vad_previa_ms": 300,
        "memoria_turnos": 6,
        "log_turnos": resumo["log_turnos"],
        "whisper": "large-v3-turbo, cuda (GPU1), float16",
        "emocao_espera_ms": 1000,
    }
    assert "segredo" not in repr(resumo)
    assert "emocao_espera_ms" not in resumo_publico(carregar_config({}))
