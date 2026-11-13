import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import carregar_config
from app.ferramentas.agora import agora, por_extenso
from app.pipeline import llm

SP = ZoneInfo("America/Sao_Paulo")


@pytest.mark.parametrize(
    ("quando", "texto"),
    [
        (
            datetime(2026, 11, 13, 14, 5),
            "sexta-feira, 13 de novembro de 2026, 14 horas e 5 minutos",
        ),
        (datetime(2026, 3, 1, 1, 1), "domingo, 1º de março de 2026, 1 hora e 1 minuto"),
        (datetime(2026, 12, 7, 0, 0), "segunda-feira, 7 de dezembro de 2026, 0 horas"),
    ],
)
def test_por_extenso(quando, texto):
    assert por_extenso(quando) == texto


def test_agora_converte_para_o_fuso():
    meio_dia_utc = datetime(2026, 11, 13, 15, 0, tzinfo=ZoneInfo("UTC"))
    assert agora("America/Sao_Paulo", meio_dia_utc).endswith("12 horas")


def test_fuso_invalido_recusado():
    with pytest.raises(ValueError, match="PEGASUS_FUSO"):
        carregar_config({"PEGASUS_FUSO": "Marte/Olimpo"})


def test_ferramenta_desconhecida_recusada():
    with pytest.raises(ValueError, match="PEGASUS_FERRAMENTAS"):
        carregar_config({"PEGASUS_FERRAMENTAS": "clima,horoscopo"})


def _pedido(monkeypatch, ambiente, historico=()):
    pedidos = []

    class _Fluxo:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def __aiter__(self):
            return
            yield

    async def create(**kwargs):
        pedidos.append(kwargs)
        return _Fluxo()

    from types import SimpleNamespace as NS

    async def preparar(config):
        return NS(chat=NS(completions=NS(create=create))), "m"

    monkeypatch.setattr(llm, "_preparar", preparar)
    config = carregar_config({"PEGASUS_EMOCAO_MODO": "paralelo"} | ambiente)

    async def coletar():
        return [x async for x in llm.gerar("Que dia é hoje?", config, historico)]

    asyncio.run(coletar())
    return pedidos[0]["messages"]


def test_data_hora_vai_na_fala_atual_e_nao_no_historico(monkeypatch):
    historico = [("Oi.", "Olá!")]
    mensagens = _pedido(monkeypatch, {"PEGASUS_FERRAMENTAS": "data_hora"}, historico)
    assert mensagens[1]["content"] == "Oi."
    assert mensagens[-1]["content"].startswith("[agora: ")
    assert mensagens[-1]["content"].endswith("]\nQue dia é hoje?")
    assert "[agora: …]" in mensagens[0]["content"]


def test_sem_data_hora_a_fala_vai_como_veio(monkeypatch):
    mensagens = _pedido(monkeypatch, {})
    assert mensagens[-1]["content"] == "Que dia é hoje?"
    assert "agora" not in mensagens[0]["content"]
