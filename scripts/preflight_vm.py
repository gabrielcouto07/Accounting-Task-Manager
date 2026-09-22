"""Diagnostico da VM ANTES de atualizar. Nao escreve nada em lugar nenhum.

Roda na VM, com o servico no ar ou parado, e responde:

- onde esta o banco de verdade, e se ele corre risco de ser apagado junto
  com a pasta do codigo;
- quantas linhas existem hoje (para conferir depois da atualizacao);
- quais colunas novas ainda faltam (ou seja, se a migracao ja rodou);
- se ainda ha senha em texto puro;
- se as variaveis de ambiente essenciais estao definidas;
- qual commit esta na pasta e se ha alteracao local nao commitada.

Uso:

    $env:DATABASE_URL = "sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
    python scripts\\preflight_vm.py

Saida termina com ATENCAO=... para cada ponto que merece cuidado.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Colunas/indices que esta versao espera encontrar depois da atualizacao.
COLUNAS_ESPERADAS = {
    "users": ["must_change_password"],
    "tasks": ["solicitante"],
}

VARIAVEIS = [
    ("DATABASE_URL", True),
    ("SESSION_SECRET_KEY", True),
    ("SMTP_USER", False),
    ("SMTP_PASSWORD", False),
]

avisos: list[str] = []


def secao(titulo: str) -> None:
    print()
    print(f"--- {titulo} ---")


def resolver_banco() -> Path:
    """Descobre o caminho do banco do mesmo jeito que a aplicacao descobre."""
    from sqlalchemy.engine import make_url

    url_txt = os.getenv(
        "DATABASE_URL", f"sqlite:///{(ROOT_DIR / 'controle_contabil.db').resolve().as_posix()}"
    )
    url = make_url(url_txt)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise SystemExit(f"Este diagnostico so cobre SQLite. DATABASE_URL={url_txt}")
    return Path(url.database).resolve()


def abrir_somente_leitura(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=10)


def colunas(conn: sqlite3.Connection, tabela: str) -> list[str]:
    return [linha[1] for linha in conn.execute(f'PRAGMA table_info("{tabela}")')]


def main() -> None:
    print("=" * 62)
    print(" PREFLIGHT - diagnostico da VM (somente leitura)")
    print("=" * 62)

    secao("Ambiente")
    print(f"python={sys.version.split()[0]}")
    print(f"executavel={sys.executable}")
    print(f"pasta_codigo={ROOT_DIR}")
    if sys.version_info < (3, 11):
        avisos.append("Python abaixo de 3.11; o codigo usa sintaxe 3.10+/3.11+.")

    try:
        import fastapi
        import sqlalchemy

        print(f"fastapi={fastapi.__version__} sqlalchemy={sqlalchemy.__version__}")
    except ImportError as exc:
        print(f"dependencias=FALTANDO ({exc})")
        avisos.append("Dependencias nao instaladas neste interpretador. Ative a .venv certa.")

    secao("Banco de dados")
    db = resolver_banco()
    print(f"caminho={db}")
    print(f"existe={db.exists()}")
    if not db.exists():
        avisos.append(f"Banco NAO encontrado em {db}. Confira o DATABASE_URL.")
        print("\n".join(f"ATENCAO={a}" for a in avisos))
        raise SystemExit(1)

    print(f"tamanho_bytes={db.stat().st_size}")
    for sufixo in ("-shm", "-wal"):
        lateral = db.with_name(db.name + sufixo)
        if lateral.exists():
            print(f"sidecar{sufixo}={lateral.stat().st_size} bytes")

    # O ponto mais importante do diagnostico: se o banco mora dentro da pasta
    # do codigo, substituir a pasta APAGA os dados de producao.
    try:
        relativo = db.relative_to(ROOT_DIR)
        print(f"banco_dentro_do_codigo=SIM ({relativo})")
        avisos.append(
            "PERIGO: o banco esta DENTRO da pasta do codigo. Substituir a pasta "
            "apaga os dados. Mova o banco para fora (ex.: C:/data/...) e aponte "
            "o DATABASE_URL para la ANTES de atualizar."
        )
    except ValueError:
        print("banco_dentro_do_codigo=nao (bom - codigo e dados separados)")

    livre = shutil.disk_usage(db.parent).free
    print(f"espaco_livre_mb={livre // (1024 * 1024)}")
    if livre < db.stat().st_size * 5:
        avisos.append("Pouco espaco em disco para backup com folga.")

    conn = abrir_somente_leitura(db)
    try:
        secao("Conteudo atual (anote estes numeros)")
        tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for tabela in ("users", "tasks", "subtasks", "chamados"):
            if tabela in tabelas:
                total = conn.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
                print(f"{tabela}={total}")
            else:
                print(f"{tabela}=<tabela nao existe ainda>")

        secao("Integridade")
        resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"integrity_check={resultado}")
        if resultado != "ok":
            avisos.append("O banco de producao acusa corrupcao. NAO atualize antes de resolver.")

        secao("Migracao desta versao")
        pendentes = 0
        for tabela, esperadas in COLUNAS_ESPERADAS.items():
            if tabela not in tabelas:
                continue
            existentes = colunas(conn, tabela)
            for coluna in esperadas:
                tem = coluna in existentes
                print(f"{tabela}.{coluna}={'ja existe' if tem else 'sera criada no 1o start'}")
                pendentes += 0 if tem else 1
        print(f"colunas_a_criar={pendentes}")

        if "users" in tabelas:
            secao("Senhas")
            texto_puro = conn.execute(
                "SELECT COUNT(*) FROM users WHERE senha NOT LIKE 'pbkdf2_sha256$%'"
            ).fetchone()[0]
            print(f"senhas_em_texto_puro={texto_puro}")
            print("(serao convertidas para hash no primeiro start; a senha da pessoa nao muda)")

            gerentes = conn.execute(
                "SELECT COUNT(*) FROM users WHERE perfil = 'gerente'"
            ).fetchone()[0]
            print(f"gerentes={gerentes}")
            if gerentes == 0:
                avisos.append("Nenhum gerente cadastrado: ninguem conseguira administrar o sistema.")

            ja_tem = conn.execute(
                "SELECT COUNT(*) FROM users WHERE id = 'sirlandia'"
            ).fetchone()[0]
            print(f"usuario_sirlandia_ja_existe={'sim' if ja_tem else 'nao'}")
    finally:
        conn.close()

    secao("Variaveis de ambiente deste shell")
    for nome, essencial in VARIAVEIS:
        valor = os.getenv(nome, "")
        if valor:
            mostra = valor if nome in {"DATABASE_URL", "SMTP_USER"} else "(definida)"
            print(f"{nome}={mostra}")
        else:
            print(f"{nome}=<vazia>")
            if essencial:
                avisos.append(
                    f"{nome} nao esta definida NESTE shell. Confirme que o servico "
                    "a define (Task Scheduler, .env ou variavel de maquina)."
                )

    secao("Codigo")
    try:
        commit = subprocess.run(
            ["git", "log", "-1", "--pretty=%h %s"],
            cwd=ROOT_DIR, capture_output=True, text=True, check=True,
        ).stdout.strip()
        sujo = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT_DIR, capture_output=True, text=True, check=True,
        ).stdout.strip()
        print(f"commit={commit}")
        print(f"alteracoes_locais={'SIM' if sujo else 'nenhuma'}")
        if sujo:
            print(sujo)
            avisos.append(
                "Ha alteracoes locais nao commitadas na pasta da VM. "
                "Um 'git pull' pode dar conflito ou sobrescrever ajustes feitos direto no servidor."
            )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("git=indisponivel (a pasta nao e um clone, ou o git nao esta no PATH)")

    secao("Resultado")
    if avisos:
        for aviso in avisos:
            print(f"ATENCAO={aviso}")
        print(f"\npreflight=COM_RESSALVAS ({len(avisos)})")
    else:
        print("preflight=OK - pode seguir para o backup e a atualizacao")


if __name__ == "__main__":
    main()
