import secrets

import pytest

from app import seguranca

A = secrets.token_urlsafe(32)
B = secrets.token_urlsafe(32)
TABLETS = (("sala-01", A), ("sala-02", B))


def test_le_nome_e_token_de_cada_tablet():
    assert seguranca.carregar_tablets(f"sala-01:{A}, sala-02:{B},") == TABLETS
    assert seguranca.carregar_tablets("") == ()


@pytest.mark.parametrize(
    "valor",
    [
        "sala-01:curto",
        "sala-01:" + "a" * 43,  # longo, mas não aleatório
        "sala-01:" + A[:31],
        "sala-01:" + A[:-1] + "!",  # fora do base64 para URL
        A,  # sem nome
        f"Sala 01:{A}",
        f"sala-01:{A},sala-01:{B}",
        f"sala-01:{A},sala-02:{A}",
    ],
)
def test_recusa_tablets_mal_configurados(valor):
    with pytest.raises(ValueError) as erro:
        seguranca.carregar_tablets(valor)
    assert A not in str(erro.value) and B not in str(erro.value)


def test_identifica_o_dono_do_token():
    assert seguranca.identificar(A, TABLETS) == "sala-01"
    assert seguranca.identificar(B, TABLETS) == "sala-02"
    assert seguranca.identificar(A[:-1], TABLETS) is None
    assert seguranca.identificar("", TABLETS) is None
    assert seguranca.identificar(None, TABLETS) is None
    assert seguranca.identificar(123, TABLETS) is None
    assert seguranca.identificar(A, ()) is None


PROXIES = frozenset({"127.0.0.1", "::1"})


@pytest.mark.parametrize(
    ("direto", "encaminhado", "esperado"),
    [
        ("203.0.113.7", None, "203.0.113.7"),  # sem proxy
        ("203.0.113.7", "198.51.100.1", "203.0.113.7"),  # cabeçalho de quem não é proxy
        ("127.0.0.1", None, "127.0.0.1"),  # local, sem proxy no meio
        ("127.0.0.1", "203.0.113.7", "203.0.113.7"),  # pelo Caddy
        ("127.0.0.1", "1.2.3.4, 203.0.113.7", "203.0.113.7"),  # o cliente forjou a esquerda
        ("127.0.0.1", "203.0.113.7, 127.0.0.1", "203.0.113.7"),
        ("127.0.0.1", "2001:db8::1", "2001:db8::1"),
        ("127.0.0.1", "lixo", "127.0.0.1"),
        (None, None, "desconhecido"),
    ],
)
def test_ip_real(direto, encaminhado, esperado):
    assert seguranca.ip_real(direto, encaminhado, PROXIES) == esperado


class _Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_bloqueia_depois_de_5_falhas_em_10_min_por_15_min():
    relogio = _Relogio()
    b = seguranca.Bloqueio(PROXIES, relogio=relogio)
    for _ in range(4):
        assert not b.falhou("203.0.113.7")
        relogio.t += 60
    assert not b.bloqueado("203.0.113.7")
    assert b.falhou("203.0.113.7")  # a 5ª, 4 min depois da 1ª
    assert b.bloqueado("203.0.113.7") and b.bloqueado("203.0.113.7")
    assert b.recusadas("203.0.113.7") == 2
    assert not b.bloqueado("198.51.100.1")  # os outros IPs seguem livres
    relogio.t += 899
    assert b.bloqueado("203.0.113.7")
    relogio.t += 1
    assert not b.bloqueado("203.0.113.7")
    assert not b.falhou("203.0.113.7")  # depois do bloqueio, a conta recomeça


def test_falhas_antigas_saem_da_janela():
    relogio = _Relogio()
    b = seguranca.Bloqueio(PROXIES, relogio=relogio)
    for _ in range(10):
        assert not b.falhou("203.0.113.7")
        relogio.t += 151  # 5 falhas sempre ocupam mais de 10 min
    assert not b.bloqueado("203.0.113.7")


def test_proxy_nunca_e_bloqueado():
    b = seguranca.Bloqueio(PROXIES)
    assert not any(b.falhou("127.0.0.1") for _ in range(20))
    assert not b.bloqueado("127.0.0.1")


def test_device_id_limpo_para_o_log():
    assert seguranca.limpar_para_log("tablet-01\nFALSO: linha") == "tablet-01?FALSO:?linha"
    assert len(seguranca.limpar_para_log("x" * 100)) == 32
