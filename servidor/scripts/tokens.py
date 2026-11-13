"""Tokens dos tablets no pegasus.env (PEGASUS_TABLETS="nome:token,nome:token").

Uso, a partir de servidor/:

    ../.venv/bin/python -m scripts.tokens listar               # só os nomes
    ../.venv/bin/python -m scripts.tokens adicionar sala-02    # mostra o token novo uma vez
    ../.venv/bin/python -m scripts.tokens adicionar teste-1 --sem-mostrar
    ../.venv/bin/python -m scripts.tokens remover sala-02
    ../.venv/bin/python -m scripts.tokens migrar tablet-01     # PEGASUS_TOKENS antigo → tablet-01

O arquivo continua com modo 600 e os tokens dos outros tablets nunca são mostrados.
Depois de mudar, reinicie a API (systemctl --user restart pegasus-api).
"""

import argparse
import os
import secrets
import sys
import tempfile
from pathlib import Path

from app.seguranca import carregar_tablets

ARQUIVO = Path.home() / ".config" / "robo-pegasus" / "pegasus.env"
CHAVE = "PEGASUS_TABLETS"


def de_teste() -> list[str]:
    """Tokens dos tablets "teste-*" do ambiente (pegasus.env carregado), para os
    clientes de teste: assim eles nunca tomam a vaga de um tablet de verdade."""
    tablets = carregar_tablets(os.environ.get(CHAVE, ""))
    return [t for n, t in sorted(tablets) if n.startswith("teste-")]


def _ler(arquivo: Path) -> list[str]:
    return arquivo.read_text().splitlines() if arquivo.exists() else []


def _valor(linhas: list[str], chave: str) -> str | None:
    for linha in reversed(linhas):
        if linha.startswith(f"{chave}="):
            return linha.partition("=")[2].strip().strip("\"'")
    return None


def _gravar(arquivo: Path, linhas: list[str]) -> None:
    """Grava por troca atômica, com modo 600 desde a criação."""
    arquivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporario = tempfile.mkstemp(dir=arquivo.parent, prefix=".pegasus.env.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(linhas) + "\n")
        os.chmod(temporario, 0o600)
        os.replace(temporario, arquivo)
    except BaseException:
        os.unlink(temporario)
        raise


def _com_tablets(linhas: list[str], tablets: list[tuple[str, str]]) -> list[str]:
    nova = f"{CHAVE}=" + ",".join(f"{n}:{t}" for n, t in tablets)
    carregar_tablets(nova.partition("=")[2])  # valida antes de gravar
    sem = [linha for linha in linhas if not linha.startswith(f"{CHAVE}=")]
    return [*sem, nova]


def main(argv: list[str] | None = None, arquivo: Path = ARQUIVO) -> int:
    parser = argparse.ArgumentParser(description="Tokens dos tablets no pegasus.env.")
    sub = parser.add_subparsers(dest="acao", required=True)
    sub.add_parser("listar")
    adicionar = sub.add_parser("adicionar")
    adicionar.add_argument("nome")
    adicionar.add_argument("--sem-mostrar", action="store_true", help="não mostra o token gerado")
    sub.add_parser("remover").add_argument("nome")
    sub.add_parser("migrar").add_argument("nome", help="dono do token de PEGASUS_TOKENS")
    args = parser.parse_args(argv)

    linhas = _ler(arquivo)
    tablets = list(carregar_tablets(_valor(linhas, CHAVE) or ""))
    nomes = [n for n, _ in tablets]

    if args.acao == "listar":
        print("\n".join(nomes) if nomes else "nenhum tablet")
        return 0
    if args.acao in ("adicionar", "migrar") and args.nome in nomes:
        sys.exit(f"{args.nome} já tem token; remova antes para trocar.")
    if args.acao == "adicionar":
        token = secrets.token_urlsafe(32)
        _gravar(arquivo, _com_tablets(linhas, [*tablets, (args.nome, token)]))
        if args.sem_mostrar:
            print(f"{args.nome}: token gerado e gravado (não mostrado).")
        else:
            print(f"{args.nome}: {token}")
            print(
                "Configure o tablet com esse token (PEGASUS_TOKEN no app); "
                "ele não será mostrado de novo."
            )
    elif args.acao == "remover":
        if args.nome not in nomes:
            sys.exit(f"{args.nome} não tem token.")
        _gravar(arquivo, _com_tablets(linhas, [t for t in tablets if t[0] != args.nome]))
        print(f"{args.nome}: token removido.")
    elif args.acao == "migrar":
        antigos = [
            t.strip() for t in (_valor(linhas, "PEGASUS_TOKENS") or "").split(",") if t.strip()
        ]
        if len(antigos) != 1:
            sys.exit(f"PEGASUS_TOKENS deve ter exatamente um token (tem {len(antigos)}).")
        novas = _com_tablets(linhas, [*tablets, (args.nome, antigos[0])])
        _gravar(arquivo, [linha for linha in novas if not linha.startswith("PEGASUS_TOKENS=")])
        print(f"PEGASUS_TOKENS migrado para {args.nome} em {CHAVE}.")
    print("Reinicie a API para valer: systemctl --user restart pegasus-api")
    return 0


if __name__ == "__main__":
    sys.exit(main())
