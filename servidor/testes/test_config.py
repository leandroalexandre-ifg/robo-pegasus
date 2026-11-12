from pathlib import Path

from app.config import MODELOS, carregar_config


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
