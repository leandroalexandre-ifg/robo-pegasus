"""Personalidade do robô, lida de um arquivo TOML editável (servidor/persona.toml)."""

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.config import Config

log = logging.getLogger("pegasus.persona")

_PASTA = Path(__file__).parent

# Acrescentada ao prompt de sistema quando a emoção vem da mesma requisição da fala
# (PEGASUS_EMOCAO_MODO=antes).
PROMPT_EMOCAO = (_PASTA / "emocao.md").read_text(encoding="utf-8").strip()

# Regras de saída para voz: valem para qualquer persona e não ficam no arquivo
# editável, para uma edição não quebrar o TTS.
_REGRAS_DE_VOZ = (
    "Sua resposta será lida em voz alta: não use emojis, listas, markdown nem símbolos; "
    "escreva números e siglas como se fala.\n"
    "Escreva só o que será dito: nunca escreva nomes de emoções, marcações, chamadas de "
    "função nem ferramentas no texto."
)

_CAMPOS_TEXTO = ("nome", "descricao", "tom", "publico")
_FRASES_MAX = range(1, 6)


class PersonaInvalida(ValueError):
    pass


@dataclass(frozen=True)
class Persona:
    nome: str
    descricao: str
    tom: str
    publico: str
    frases_max: int
    instrucoes: str = ""

    def prompt(self) -> str:
        frases = "1 frase curta" if self.frases_max == 1 else f"{self.frases_max} frases curtas"
        linhas = [
            f"Você é o {self.nome}, {self.descricao}.",
            f"Responda sempre em português do Brasil, com no máximo {frases}.",
            f"Use linguagem {self.tom}, adequada a {self.publico}.",
            _REGRAS_DE_VOZ,
        ]
        if self.instrucoes:
            linhas.append(self.instrucoes)
        return "\n".join(linhas)


def ler(caminho: Path) -> Persona:
    """Lê e valida o arquivo da persona; erros dizem o arquivo e o campo."""
    try:
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PersonaInvalida(f"{caminho}: arquivo da persona não encontrado") from None
    except tomllib.TOMLDecodeError as e:
        raise PersonaInvalida(f"{caminho}: TOML inválido: {e}") from None

    for campo in _CAMPOS_TEXTO:
        valor = dados.get(campo)
        if not isinstance(valor, str) or not valor.strip():
            raise PersonaInvalida(f"{caminho}: o campo {campo!r} é obrigatório e deve ser texto")
    frases_max = dados.get("frases_max", 2)
    if not isinstance(frases_max, int) or frases_max not in _FRASES_MAX:
        raise PersonaInvalida(f"{caminho}: frases_max deve ser um número de 1 a 5")
    instrucoes = dados.get("instrucoes", "")
    if not isinstance(instrucoes, str):
        raise PersonaInvalida(f"{caminho}: instrucoes deve ser texto")
    desconhecidos = set(dados) - {*_CAMPOS_TEXTO, "frases_max", "instrucoes"}
    if desconhecidos:
        log.warning("%s: campos ignorados: %s", caminho, ", ".join(sorted(desconhecidos)))

    return Persona(
        **{campo: dados[campo].strip() for campo in _CAMPOS_TEXTO},
        frases_max=frases_max,
        instrucoes=instrucoes.strip(),
    )


_carregadas: dict[Path, Persona] = {}


def carregar(caminho: Path) -> Persona:
    """Lê a persona do disco (na subida do servidor) e a guarda para os turnos."""
    persona = ler(caminho)
    _carregadas[caminho] = persona
    return persona


def prompt_sistema(config: Config) -> str:
    """Prompt de sistema da persona configurada; lê o arquivo só na primeira vez."""
    persona = _carregadas.get(config.persona_arquivo) or carregar(config.persona_arquivo)
    return persona.prompt()
