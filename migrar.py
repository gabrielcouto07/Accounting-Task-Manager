from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT_DIR / "app" / "controle.db"
DEFAULT_TARGET = ROOT_DIR / "controle_contabil.db"
BACKUP_DIR = ROOT_DIR / "backups" / "app_db"


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def backup_database(path: Path) -> Path | None:
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"{stamp}.{path.stem}.before-migration.db"
    shutil.copy2(path, backup_path)
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upgrade controle_contabil.db and import legacy controle.db data."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Legacy SQLite database. Default: app/controle.db",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="App SQLite database. Default: controle_contabil.db",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear users, tasks and subtasks before importing from source.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the automatic target database backup.",
    )
    args = parser.parse_args()

    target = args.target.resolve()
    source = args.source.resolve()
    os.environ["DATABASE_URL"] = sqlite_url(target)
    sys.path.insert(0, str(ROOT_DIR))

    from app import crud, legacy_import, models
    from app.database import Base, engine, session_scope

    if not args.no_backup:
        backup_path = backup_database(target)
        if backup_path:
            print(f"backup={backup_path}")

    Base.metadata.create_all(bind=engine)

    with session_scope() as db:
        crud.ensure_schema(db)

        imported = {"users": 0, "tasks": 0, "subtasks": 0}
        if source.exists() and source != target:
            tables = legacy_import.read_legacy_sqlite(source)
            imported = legacy_import.import_legacy_tables(db, tables, reset=args.reset)
        elif source.exists():
            print("source_is_target=true")
        else:
            print(f"source_missing={source}")

        counts = {
            "users": db.query(models.User).count(),
            "tasks": db.query(models.Task).count(),
            "subtasks": db.query(models.Subtask).count(),
        }

    print(f"imported_users={imported['users']}")
    print(f"imported_tasks={imported['tasks']}")
    print(f"imported_subtasks={imported['subtasks']}")
    print(f"app_users={counts['users']}")
    print(f"app_tasks={counts['tasks']}")
    print(f"app_subtasks={counts['subtasks']}")
    print(f"database={target}")


if __name__ == "__main__":
    main()
