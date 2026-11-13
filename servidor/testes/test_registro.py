import json
import logging.handlers

import pytest

from app import registro


def test_grava_jsonl_e_rotaciona_por_dia(tmp_path):
    caminho = registro.configurar(tmp_path / "logs", dias=7)
    registro.registrar("turno", sessao="abc", ms={"stt": 45})
    [linha] = caminho.read_text().splitlines()
    dados = json.loads(linha)
    assert dados["tipo"] == "turno"
    assert dados["ms"] == {"stt": 45}
    assert "t" in dados
    [destino] = registro._arquivo.handlers
    assert isinstance(destino, logging.handlers.TimedRotatingFileHandler)
    assert (destino.when, destino.backupCount) == ("MIDNIGHT", 7)
    assert (tmp_path / "logs").stat().st_mode & 0o077 == 0


def test_recusa_campos_fora_da_lista(tmp_path):
    registro.configurar(tmp_path, dias=1)
    with pytest.raises(ValueError, match="texto"):
        registro.registrar("turno", texto="o que o usuário disse")
    with pytest.raises(ValueError, match="tipo"):
        registro.registrar("conversa")
    assert (tmp_path / registro.ARQUIVO).read_text() == ""


def test_reconfigurar_nao_duplica_linhas(tmp_path):
    registro.configurar(tmp_path, dias=1)
    caminho = registro.configurar(tmp_path, dias=1)
    registro.registrar("sem_fala", sessao="x")
    assert len(caminho.read_text().splitlines()) == 1
