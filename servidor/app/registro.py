"""Registro dos tempos de cada turno, em arquivo rotacionado, sem texto nem áudio.

Cada linha de `turnos.jsonl` é um objeto JSON. Só entram os campos de CAMPOS:
medidas, contagens e identificadores. Nada do que o usuário disse ou o robô
respondeu chega aqui, nem a duração de falas descartadas na escuta contínua.
"""

import collections
import json
import logging
import logging.handlers
import statistics
import time
from pathlib import Path

ARQUIVO = "turnos.jsonl"
CAMPOS = frozenset(
    {
        "sessao",
        "tablet",
        "audio_s",
        "fim_escuta",
        "frases",
        "memoria",
        "emocoes",
        "ms",
        "etapa",
        "erro",
    }
)
TIPOS = frozenset({"turno", "sem_fala", "ativacao", "despedida", "falha", "interrompido"})

# Resumo em memória para o /status: contagem por tipo e latências recentes.
contagem: collections.Counter[str] = collections.Counter()
_latencias: collections.deque[int] = collections.deque(maxlen=100)

log = logging.getLogger("pegasus.turnos")
_arquivo = logging.getLogger("pegasus.turnos.arquivo")
_arquivo.propagate = False  # o arquivo recebe só o JSON; o log geral recebe a linha resumida


def configurar(pasta: Path, dias: int) -> Path:
    """Grava os turnos em `pasta/turnos.jsonl`, trocando de arquivo à meia-noite e
    guardando `dias` arquivos antigos."""
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    caminho = pasta / ARQUIVO
    for antigo in list(_arquivo.handlers):
        _arquivo.removeHandler(antigo)
        antigo.close()
    destino = logging.handlers.TimedRotatingFileHandler(
        caminho, when="midnight", backupCount=dias, encoding="utf-8"
    )
    destino.setFormatter(logging.Formatter("%(message)s"))
    _arquivo.addHandler(destino)
    _arquivo.setLevel(logging.INFO)
    return caminho


def registrar(tipo: str, **dados) -> dict:
    """Registra um turno. Campos fora de CAMPOS são recusados, para que nenhum
    texto da conversa entre no registro por engano."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo de registro desconhecido: {tipo}")
    if extras := set(dados) - CAMPOS:
        raise ValueError(f"campos não permitidos no registro: {sorted(extras)}")
    registro = {"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tipo": tipo, **dados}
    contagem[tipo] += 1
    # Só turnos com resposta: o "Oi?" da ativação é bem mais rápido e distorceria a conta.
    if tipo == "turno" and "fala_ate_primeiro_audio" in (ms := dados.get("ms") or {}):
        _latencias.append(ms["fala_ate_primeiro_audio"])
    linha = json.dumps(registro, ensure_ascii=False)
    _arquivo.info(linha)
    log.info("%s %s", tipo, json.dumps(dados, ensure_ascii=False))
    return registro


def resumo() -> dict:
    """Turnos desde a subida e a latência (fim da fala → primeiro áudio) dos últimos 100
    turnos com resposta."""
    resultado: dict = {"por_tipo": dict(contagem)}
    if _latencias:
        ordenadas = sorted(_latencias)
        resultado["fala_ate_primeiro_audio_ms"] = {
            "amostras": len(ordenadas),
            "mediana": round(statistics.median(ordenadas)),
            "p90": ordenadas[min(len(ordenadas) - 1, int(0.9 * len(ordenadas)))],
            "max": ordenadas[-1],
        }
    return resultado
