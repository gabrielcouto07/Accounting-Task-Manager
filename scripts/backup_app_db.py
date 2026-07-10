from __future__ import annotations

import argparse
import os
import shutil
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the active FastAPI SQLite database and its WAL sidecars.")
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
    args = parser.parse_args()

    db_path = resolve_sqlite_path(args.db_url)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    copy_if_exists(db_path, out_dir / f"{timestamp}.{db_path.name}")
    copy_if_exists(db_path.with_name(f"{db_path.name}-shm"), out_dir / f"{timestamp}.{db_path.name}-shm")
    copy_if_exists(db_path.with_name(f"{db_path.name}-wal"), out_dir / f"{timestamp}.{db_path.name}-wal")


if __name__ == "__main__":
    main()
