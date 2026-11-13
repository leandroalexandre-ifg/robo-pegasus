import asyncio

import numpy as np

from app.config import carregar_config
from app.pipeline import llm, stt, tts, turno
from app.pipeline.emocao import Emocao

FELIZ = Emocao("feliz")


def _falsos(monkeypatch, transcricao, pedacos, emocao=FELIZ, atraso_emocao=0.0):
    sintetizadas = []
    pedidos_emocao = []

    async def transcrever(audio, config):
        return transcricao

    async def gerar(texto, config, historico=()):
        for p in pedacos:
            yield p

    async def escolher_emocao(texto, config, historico=()):
        pedidos_emocao.append(texto)
        await asyncio.sleep(atraso_emocao)
        if isinstance(emocao, Exception):
            raise emocao
        return emocao

    async def sintetizar(texto, config):
        sintetizadas.append(texto)
        return texto.encode(), 22_050

    monkeypatch.setattr(stt, "transcrever", transcrever)
    monkeypatch.setattr(llm, "gerar", gerar)
    monkeypatch.setattr(llm, "escolher_emocao", escolher_emocao)
    monkeypatch.setattr(tts, "sintetizar", sintetizar)
    return sintetizadas, pedidos_emocao


def _rodar(t, **ambiente):
    config = carregar_config({"PEGASUS_EMOCAO_MODO": "paralelo"} | ambiente)

    async def coletar():
        return [b async for b in turno.conversar(np.zeros(160, np.float32), config, t)]

    return asyncio.run(coletar())


def _frases(itens):
    return [i.frase for i in itens if isinstance(i, turno.BlocoAudio)]


def _emocoes(itens):
    return [i for i in itens if isinstance(i, Emocao)]


def test_uma_emocao_e_um_bloco_por_frase(monkeypatch):
    sintetizadas, pedidos = _falsos(
        monkeypatch, "qual é o seu nome?", ["Olá! Meu ", "nome é Pegasus."]
    )
    t = turno.Turno()
    itens = _rodar(t)
    assert _emocoes(itens) == [Emocao("feliz")]
    assert _frases(itens) == ["Olá!", "Meu nome é Pegasus."]
    assert sintetizadas == ["Olá!", "Meu nome é Pegasus."]
    assert {b.taxa for b in itens if isinstance(b, turno.BlocoAudio)} == {22_050}
    assert pedidos == ["qual é o seu nome?"]
    assert t.texto_usuario == "qual é o seu nome?"
    assert t.resposta == "Olá! Meu nome é Pegasus."
    assert t.emocoes == ["feliz"]


def test_primeira_frase_corta_na_virgula(monkeypatch):
    _falsos(monkeypatch, "o que é o sol?", ["Olha, o sol é ", "uma estrela, bem grande. Fim."])
    t = turno.Turno()
    assert _frases(_rodar(t)) == ["Olha,", "o sol é uma estrela, bem grande.", "Fim."]
    assert t.resposta == "Olha, o sol é uma estrela, bem grande. Fim."


def test_tempos_em_ordem(monkeypatch):
    _falsos(monkeypatch, "oi", ["Oi! ", "Tudo bem?"])
    t = turno.Turno()
    _rodar(t)
    assert t.tempos["stt"] <= t.tempos["llm_primeira_frase"] <= t.tempos["primeiro_audio"]
    assert t.tempos["emocao_llm"] <= t.tempos["emocao"]
    assert t.tempos["primeiro_audio"] <= t.tempos["llm_fim"] <= t.tempos["fim"]


def test_sem_fala_nao_responde(monkeypatch):
    sintetizadas, pedidos = _falsos(monkeypatch, "", ["não deveria aparecer."])
    t = turno.Turno()
    assert _rodar(t) == []
    assert sintetizadas == pedidos == []
    assert list(t.tempos) == ["stt"]


def test_sem_emocao_valida_usa_neutro(monkeypatch):
    _falsos(monkeypatch, "oi", ["Oi."], emocao=None)
    t = turno.Turno()
    assert _emocoes(_rodar(t)) == [Emocao("neutro")]
    assert t.emocoes == ["neutro"]


def test_falha_na_emocao_usa_neutro(monkeypatch):
    _falsos(monkeypatch, "oi", ["Oi."], emocao=RuntimeError("vLLM caiu"))
    t = turno.Turno()
    itens = _rodar(t)
    assert _emocoes(itens) == [Emocao("neutro")]
    assert _frases(itens) == ["Oi."]


def test_primeiro_audio_nao_espera_a_emocao(monkeypatch):
    _falsos(monkeypatch, "oi", ["Oi.", " Tchau."], emocao=Emocao("triste"), atraso_emocao=0.2)
    t = turno.Turno()
    itens = _rodar(t)
    # O áudio sai na hora; a emoção chega depois, dentro do prazo, e vai assim mesmo.
    assert isinstance(itens[0], turno.BlocoAudio)
    assert _emocoes(itens) == [Emocao("triste")]
    assert t.tempos["primeiro_audio"] < 0.1 < t.tempos["emocao"]
    assert t.emocoes == ["triste"]


def test_emocao_fora_do_prazo_vira_neutro(monkeypatch):
    _falsos(monkeypatch, "oi", ["Oi.", " Tchau."], emocao=Emocao("triste"), atraso_emocao=5)
    t = turno.Turno()
    itens = _rodar(t, PEGASUS_EMOCAO_ESPERA_MS="50")
    assert _emocoes(itens) == [Emocao("neutro")]  # a atrasada não vem
    assert _frases(itens) == ["Oi.", "Tchau."]
    assert t.tempos["fim"] < 1
    assert "emocao_llm" not in t.tempos


def test_marcacoes_nao_chegam_a_voz(monkeypatch):
    sintetizadas, _ = _falsos(
        monkeypatch, "ganhei!", ["[feliz] Que *pula* legal! ", "😄\n", "Parabéns."]
    )
    t = turno.Turno()
    itens = _rodar(t)
    assert _frases(itens) == ["Que legal!", "Parabéns."]
    assert sintetizadas == ["Que legal!", "Parabéns."]


def _rodar_antes(t):
    return _rodar(t, PEGASUS_EMOCAO_MODO="antes")


def test_antes_emocao_do_fluxo_sai_primeiro_sem_requisicao_paralela(monkeypatch):
    _, pedidos = _falsos(monkeypatch, "ganhei!", [Emocao("surpreso"), "Uau! ", "Parabéns."])
    t = turno.Turno()
    itens = _rodar_antes(t)
    assert itens[0] == Emocao("surpreso")
    assert [b.frase for b in itens[1:]] == ["Uau!", "Parabéns."]
    assert pedidos == []  # sem requisição paralela
    assert t.emocoes == ["surpreso"]
    assert t.tempos["emocao_llm"] <= t.tempos["primeiro_audio"]


def test_antes_sem_chamada_usa_neutro_antes_do_audio(monkeypatch):
    _, pedidos = _falsos(monkeypatch, "oi", ["Oi! ", "Tudo bem?"])
    t = turno.Turno()
    itens = _rodar_antes(t)
    assert itens[0] == Emocao("neutro")
    assert [i for i in itens if isinstance(i, Emocao)] == [Emocao("neutro")]
    assert pedidos == []


def test_antes_emocao_depois_do_primeiro_audio_e_descartada(monkeypatch):
    _falsos(monkeypatch, "oi", ["Oi! ", Emocao("feliz"), "Tudo bem?"])
    t = turno.Turno()
    itens = _rodar_antes(t)
    assert [i for i in itens if isinstance(i, Emocao)] == [Emocao("neutro")]
    assert itens[0] == Emocao("neutro")
    assert t.emocoes == ["neutro"]
