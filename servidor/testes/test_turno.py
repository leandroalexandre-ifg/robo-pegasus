import asyncio

import numpy as np

from app.config import carregar_config
from app.pipeline import llm, stt, tts, turno


def _falsos(monkeypatch, transcricao, pedacos):
    sintetizadas = []

    async def transcrever(audio, config):
        return transcricao

    async def gerar(texto, config):
        for p in pedacos:
            yield p

    async def sintetizar(texto, config):
        sintetizadas.append(texto)
        return texto.encode(), 22_050

    monkeypatch.setattr(stt, "transcrever", transcrever)
    monkeypatch.setattr(llm, "gerar", gerar)
    monkeypatch.setattr(tts, "sintetizar", sintetizar)
    return sintetizadas


def _rodar(t):
    async def coletar():
        return [b async for b in turno.conversar(np.zeros(160, np.float32), carregar_config({}), t)]

    return asyncio.run(coletar())


def test_um_bloco_por_frase(monkeypatch):
    sintetizadas = _falsos(monkeypatch, "qual é o seu nome?", ["Olá! Meu ", "nome é Pegasus."])
    t = turno.Turno()
    blocos = _rodar(t)
    assert [b.frase for b in blocos] == ["Olá!", "Meu nome é Pegasus."]
    assert sintetizadas == ["Olá!", "Meu nome é Pegasus."]
    assert blocos[0].taxa == 22_050
    assert t.texto_usuario == "qual é o seu nome?"
    assert t.resposta == "Olá! Meu nome é Pegasus."


def test_tempos_em_ordem(monkeypatch):
    _falsos(monkeypatch, "oi", ["Oi! ", "Tudo bem?"])
    t = turno.Turno()
    _rodar(t)
    ordem = ["stt", "llm_primeiro_token", "llm_primeira_frase", "primeiro_audio", "llm_fim", "fim"]
    assert list(t.tempos) == ordem
    assert all(t.tempos[a] <= t.tempos[b] for a, b in zip(ordem, ordem[1:], strict=False))


def test_sem_fala_nao_responde(monkeypatch):
    sintetizadas = _falsos(monkeypatch, "", ["não deveria aparecer."])
    t = turno.Turno()
    assert _rodar(t) == []
    assert sintetizadas == []
    assert list(t.tempos) == ["stt"]
