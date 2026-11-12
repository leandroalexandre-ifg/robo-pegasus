import pytest

from app import persona
from app.config import SERVIDOR, carregar_config

VALIDA = """
nome = "Ana"
descricao = "uma robô que conta histórias"
tom = "divertida"
publico = "crianças de 6 a 10 anos"
frases_max = 1
instrucoes = "Termine com uma pergunta."
"""


def _arquivo(tmp_path, conteudo):
    caminho = tmp_path / "persona.toml"
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


def test_persona_do_repositorio_e_valida():
    p = persona.ler(SERVIDOR / "persona.toml")
    assert p.nome == "Pegasus"
    assert p.frases_max == 2
    texto = p.prompt()
    assert texto.startswith("Você é o Pegasus, um robô simpático")
    assert "no máximo 2 frases curtas" in texto
    assert "não use emojis" in texto


def test_prompt_usa_os_campos_e_as_regras_de_voz(tmp_path):
    p = persona.ler(_arquivo(tmp_path, VALIDA))
    texto = p.prompt()
    assert "Você é o Ana, uma robô que conta histórias." in texto
    assert "no máximo 1 frase curta." in texto
    assert "Use linguagem divertida, adequada a crianças de 6 a 10 anos." in texto
    assert "nunca escreva nomes de emoções" in texto  # regras fixas, fora do arquivo
    assert texto.endswith("Termine com uma pergunta.")


@pytest.mark.parametrize(
    ("conteudo", "mensagem"),
    [
        (VALIDA.replace('nome = "Ana"', ""), "'nome' é obrigatório"),
        (VALIDA.replace('tom = "divertida"', 'tom = ""'), "'tom' é obrigatório"),
        (VALIDA.replace("frases_max = 1", "frases_max = 9"), "frases_max"),
        (VALIDA.replace("frases_max = 1", 'frases_max = "2"'), "frases_max"),
        ("nome = ", "TOML inválido"),
    ],
)
def test_persona_invalida_explica_o_problema(tmp_path, conteudo, mensagem):
    with pytest.raises(persona.PersonaInvalida, match=mensagem):
        persona.ler(_arquivo(tmp_path, conteudo))


def test_arquivo_ausente(tmp_path):
    with pytest.raises(persona.PersonaInvalida, match="não encontrado"):
        persona.ler(tmp_path / "nao_existe.toml")


def test_prompt_sistema_le_o_arquivo_configurado_uma_vez(tmp_path):
    caminho = _arquivo(tmp_path, VALIDA)
    config = carregar_config({"PEGASUS_PERSONA": str(caminho)})
    assert "Ana" in persona.prompt_sistema(config)
    caminho.write_text(VALIDA.replace("Ana", "Bia"), encoding="utf-8")
    assert "Ana" in persona.prompt_sistema(config)  # só muda ao recarregar (na subida)
    persona.carregar(caminho)
    assert "Bia" in persona.prompt_sistema(config)
