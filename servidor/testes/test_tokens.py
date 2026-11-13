import stat

import pytest

from app.seguranca import carregar_tablets
from scripts import tokens

ANTIGO = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc"


def _tablets(arquivo):
    return carregar_tablets(tokens._valor(tokens._ler(arquivo), tokens.CHAVE) or "")


def test_adicionar_listar_remover_sem_mostrar_os_outros(tmp_path, capsys):
    env = tmp_path / "pegasus.env"
    env.write_text("PEGASUS_ATIVACAO=palavra\n")
    tokens.main(["adicionar", "sala-01", "--sem-mostrar"], env)
    tokens.main(["adicionar", "sala-02"], env)
    saida = capsys.readouterr().out
    (_, t1), (_, t2) = _tablets(env)
    assert t1 not in saida and t2 in saida  # só o recém-criado, e só sem --sem-mostrar
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "PEGASUS_ATIVACAO=palavra" in env.read_text()
    tokens.main(["listar"], env)
    assert capsys.readouterr().out.split()[:2] == ["sala-01", "sala-02"]
    tokens.main(["remover", "sala-01"], env)
    assert [n for n, _ in _tablets(env)] == ["sala-02"]
    with pytest.raises(SystemExit):
        tokens.main(["adicionar", "sala-02"], env)


def test_migrar_o_token_antigo(tmp_path, capsys):
    env = tmp_path / "pegasus.env"
    env.write_text(f"PEGASUS_TOKENS={ANTIGO}\nPEGASUS_HOST=127.0.0.1\n")
    tokens.main(["migrar", "tablet-01"], env)
    assert _tablets(env) == (("tablet-01", ANTIGO),)
    assert "PEGASUS_TOKENS" not in env.read_text()
    assert ANTIGO not in capsys.readouterr().out
