from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{(ROOT_DIR / 'controle_contabil.db').resolve().as_posix()}",
)
DEFAULT_OUT = ROOT_DIR / "backups" / "app_sqlite"


def resolve_sqlite_path(db_url: str) -> Path:
    url = make_url(db_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise SystemExit("backup_app_db.py currently supports only file-based SQLite databases.")

    if url.database in {":memory:", ""}:
        raise SystemExit("In-memory SQLite databases cannot be backed up to disk.")

    return Path(url.database).resolve()


def copy_if_exists(source: Path, destination: Path) -> None:
    if not source.exists():
        print(f"missing={source}")
        return
    shutil.copy2(source, destination)
    print(f"backup={destination} bytes={destination.stat().st_size}")


def online_backup(source: Path, destination: Path) -> bool:
    """Copia o banco usando a API de backup online do SQLite.

    Diferente de um `copy` de arquivo, isto e SEGURO com o servico no ar:
    o SQLite tira um snapshot consistente mesmo que alguem esteja gravando,
    e ja incorpora o conteudo do arquivo -wal. O resultado e um unico .db
    autossuficiente, sem precisar dos arquivos -shm/-wal ao lado.
    """
    if not source.exists():
        print(f"missing={source}")
        return False

    origem = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30)
    destino = sqlite3.connect(destination)
    try:
        origem.backup(destino)
    finally:
        destino.close()
        origem.close()

    # O backup herda o modo WAL do banco de origem, o que deixa um par
    # -shm/-wal ao lado do arquivo. Passando para journal_mode=DELETE o
    # SQLite faz o checkpoint e remove os dois: o backup vira UM arquivo
    # so, autossuficiente e simples de restaurar.
    consolidar = sqlite3.connect(destination)
    try:
        consolidar.execute("PRAGMA journal_mode=DELETE")
        consolidar.commit()
    finally:
        consolidar.close()

    for sufixo in ("-shm", "-wal"):
        lateral = destination.with_name(destination.name + sufixo)
        if lateral.exists():
            lateral.unlink()

    print(f"backup={destination} bytes={destination.stat().st_size}")
    return True


def verificar(backup: Path) -> bool:
    """Confere que o backup abre e nao esta corrompido.

    Um backup que ninguem testou nao e um backup. Aqui roda-se
    `PRAGMA integrity_check` e conta-se as linhas das tabelas principais.
    """
    conn = sqlite3.connect(f"file:{backup.as_posix()}?mode=ro", uri=True)
    try:
        resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if resultado != "ok":
            print(f"integrity_check={resultado}")
            return False
        print("integrity_check=ok")

        tabelas = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for tabela in ("users", "tasks", "subtasks", "chamados"):
            if tabela in tabelas:
                total = conn.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
                print(f"{tabela}={total}")
        return True
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up the active FastAPI SQLite database (safe while the service is running)."
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help="Database URL for the active app database.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Directory where timestamped backups should be stored.",
    )
    parser.add_argument(
        "--raw-copy",
        action="store_true",
        help="Tambem copia os arquivos .db/-shm/-wal crus (so com o servico PARADO).",
    )
    args = parser.parse_args()

    db_path = resolve_sqlite_path(args.db_url)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    destino = out_dir / f"{timestamp}.{db_path.name}"
    if not online_backup(db_path, destino):
        raise SystemExit(f"Banco nao encontrado: {db_path}")

    if not verificar(destino):
        raise SystemExit("BACKUP INVALIDO - nao prossiga com a atualizacao.")

    if args.raw_copy:
        copy_if_exists(db_path, out_dir / f"{timestamp}.raw.{db_path.name}")
        copy_if_exists(
            db_path.with_name(f"{db_path.name}-shm"),
            out_dir / f"{timestamp}.raw.{db_path.name}-shm",
        )
        copy_if_exists(
            db_path.with_name(f"{db_path.name}-wal"),
            out_dir / f"{timestamp}.raw.{db_path.name}-wal",
        )

    print(f"backup_ok={destino}")


if __name__ == "__main__":
    main()
