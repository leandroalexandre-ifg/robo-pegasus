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
