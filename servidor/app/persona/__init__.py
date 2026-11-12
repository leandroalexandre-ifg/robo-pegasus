"""Personalidade do robô."""

from pathlib import Path

_PASTA = Path(__file__).parent

PROMPT_SISTEMA = (_PASTA / "sistema.md").read_text(encoding="utf-8").strip()

# Acrescentada ao prompt de sistema quando a emoção vem da mesma requisição da fala
# (PEGASUS_EMOCAO_MODO=antes).
PROMPT_EMOCAO = (_PASTA / "emocao.md").read_text(encoding="utf-8").strip()
