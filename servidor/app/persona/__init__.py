"""Personalidade do robô."""

from pathlib import Path

PROMPT_SISTEMA = (Path(__file__).parent / "sistema.md").read_text(encoding="utf-8").strip()
