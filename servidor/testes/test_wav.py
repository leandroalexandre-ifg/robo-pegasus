import numpy as np
import pytest

from app.wav import escrever_wav, ler_wav


def test_ida_e_volta(tmp_path):
    amostras = np.array([0, 16384, -16384, 32767], dtype=np.int16)
    caminho = tmp_path / "a.wav"
    escrever_wav(caminho, amostras.tobytes(), 16_000)
    audio = ler_wav(caminho)
    assert audio.dtype == np.float32
    np.testing.assert_allclose(audio, amostras / 32768.0)


def test_rejeita_taxa_errada(tmp_path):
    caminho = tmp_path / "b.wav"
    escrever_wav(caminho, b"\x00\x00" * 10, 22_050)
    with pytest.raises(ValueError, match="16 kHz"):
        ler_wav(caminho)
