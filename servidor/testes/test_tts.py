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


def test_sintetizar_le_o_texto_normalizado(monkeypatch):
    import asyncio

    from app.config import carregar_config

    lidos = []

    class _Voz:
        config = NS(sample_rate=22050)

        def synthesize(self, texto):
            lidos.append(texto)
            yield NS(audio_int16_bytes=b"\x00\x00")

    async def carregar(config):
        return _Voz()

    monkeypatch.setattr(tts, "carregar", carregar)
    asyncio.run(tts.sintetizar("Custa R$ 5,32.", carregar_config({})))
    assert lidos == ["Custa cinco reais e trinta e dois centavos."]
