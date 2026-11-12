import threading
from types import SimpleNamespace as NS

from app.pipeline import tts


class _VozFalsa:
    def __init__(self, parar_no_bloco, evento):
        self._parar_no_bloco = parar_no_bloco
        self._evento = evento

    def synthesize(self, texto):
        for i in range(5):
            if i == self._parar_no_bloco:
                self._evento.set()  # o abort chega enquanto o Piper sintetiza
            yield NS(audio_int16_bytes=bytes([i]))


def test_piper_para_antes_do_proximo_bloco_quando_avisado():
    parar = threading.Event()
    assert tts._sintetizar(_VozFalsa(2, parar), "texto", parar) == bytes([0, 1])


def test_piper_sem_aviso_sintetiza_tudo():
    parar = threading.Event()
    assert tts._sintetizar(_VozFalsa(99, parar), "texto", parar) == bytes(range(5))
