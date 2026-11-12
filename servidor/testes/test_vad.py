import numpy as np
import pytest

from app.config import carregar_config
from app.pipeline.vad import BLOCO, DetectorFala

CONFIG = carregar_config({"PEGASUS_VAD_SILENCIO_MS": "320"})  # 10 blocos de 32 ms


class _Roteiro:
    """Probabilidade falsa: um valor por bloco, na ordem."""

    def __init__(self, probs):
        self._probs = iter(probs)

    def __call__(self, bloco):
        return next(self._probs)


def _pcm(blocos, tamanho_quadro=640):
    """Áudio de `blocos` blocos do Silero, cortado em quadros de 20 ms do tablet."""
    dados = np.zeros(blocos * BLOCO, dtype=np.int16).tobytes()
    return [dados[i : i + tamanho_quadro] for i in range(0, len(dados), tamanho_quadro)]


def _rodar(probs, config=CONFIG):
    detector = DetectorFala(config, _Roteiro(probs))
    eventos = [e for q in _pcm(len(probs)) if (e := detector.processar(q))]
    return detector, eventos


def test_fala_e_silencio_geram_inicio_e_fim():
    probs = [0.0] * 5 + [0.9] * 20 + [0.05] * 10
    detector, eventos = _rodar(probs)
    assert eventos == ["inicio", "fim"]
    assert detector.inicio == 5 * BLOCO
    assert detector.fim == 25 * BLOCO
    assert detector.terminou


def test_pausa_curta_nao_encerra_a_fala():
    probs = [0.9] * 10 + [0.05] * 9 + [0.9] * 10 + [0.05] * 10
    detector, eventos = _rodar(probs)
    assert eventos == ["inicio", "fim"]
    assert detector.fim == 29 * BLOCO  # o silêncio que conta é o último


def test_estalo_curto_nao_vale_como_fala():
    detector, eventos = _rodar([0.0] * 5 + [0.9] * 2 + [0.0] * 20)
    assert eventos == []
    assert not detector.falou


def test_histerese_entre_os_limiares_nao_conta_como_silencio():
    # 0,4 fica entre o limiar de fala (0,5) e o de silêncio (0,35)
    detector, eventos = _rodar([0.9] * 5 + [0.4] * 30)
    assert eventos == ["inicio"]


def test_depois_do_fim_ignora_o_resto():
    detector, eventos = _rodar([0.9] * 5 + [0.0] * 10 + [0.9] * 10)
    assert eventos == ["inicio", "fim"]


@pytest.mark.parametrize("ms", ["600", "1000"])
def test_silencio_configuravel(ms):
    config = carregar_config({"PEGASUS_VAD_SILENCIO_MS": ms})
    blocos = round(int(ms) / 32)
    _, eventos = _rodar([0.9] * 5 + [0.0] * (blocos - 1), config)
    assert eventos == ["inicio"]
    _, eventos = _rodar([0.9] * 5 + [0.0] * blocos, config)
    assert eventos == ["inicio", "fim"]


def test_silero_de_verdade_nao_ve_fala_no_silencio():
    detector = DetectorFala(CONFIG)
    for quadro in _pcm(50):
        assert detector.processar(quadro) is None
    assert not detector.falou
