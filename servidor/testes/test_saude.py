import asyncio

import pytest

from app import saude


class _Roteiro:
    def __init__(self, *respostas):
        self.respostas = list(respostas)

    async def __call__(self):
        return self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]


@pytest.fixture(autouse=True)
def rapido(monkeypatch):
    monkeypatch.setattr(saude, "INTERVALO_S", 0.001)
    monkeypatch.setattr(saude, "INTERVALO_FORA_S", 0.001)


async def _rodar(verificar, ciclos=20):
    avisos = []

    async def avisar(ok):
        avisos.append(ok)

    monitor = saude.MonitorLLM(verificar, avisar)
    await monitor.iniciar()
    for _ in range(ciclos):
        await asyncio.sleep(0.005)
    await monitor.parar()
    return monitor, avisos


def test_uma_falha_isolada_nao_derruba():
    monitor, avisos = asyncio.run(_rodar(_Roteiro(True, False, True)))
    assert avisos == []
    assert monitor.disponivel


def test_duas_falhas_seguidas_derrubam_e_a_volta_libera():
    monitor, avisos = asyncio.run(_rodar(_Roteiro(True, False, False, False, True)))
    assert avisos == [False, True]
    assert monitor.disponivel
    assert monitor.quedas == 1


def test_fora_do_ar_na_subida():
    monitor, avisos = asyncio.run(_rodar(_Roteiro(False), ciclos=3))
    assert avisos == [False]
    assert not monitor.disponivel


def test_suspeitar_derruba_na_hora():
    async def cenario():
        verificar = _Roteiro(True)
        avisos = []

        async def avisar(ok):
            avisos.append(ok)

        monitor = saude.MonitorLLM(verificar, avisar)
        await monitor.iniciar()
        verificar.respostas = [False]
        assert await monitor.suspeitar() is False
        await asyncio.sleep(0)
        await monitor.parar()
        return avisos

    assert asyncio.run(cenario()) == [False]


def test_verificador_http_sem_servidor_responde_falso():
    from app.config import carregar_config

    config = carregar_config({"PEGASUS_LLM_URL": "http://127.0.0.1:9/v1"})
    assert asyncio.run(saude.verificador_http(config)()) is False
