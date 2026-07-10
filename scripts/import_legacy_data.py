from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app import crud, legacy_import
from app.database import Base, engine, session_scope

DEFAULT_SOURCE = ROOT_DIR / "backups" / "legacy_sqlite" / "export" / "all_tables.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Import legacy controle.db data into the FastAPI SQLite database.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="all_tables.json export path.")
    parser.add_argument("--reset", action="store_true", help="Clear app users/tasks/subtasks before importing.")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    tables = legacy_import.load_legacy_tables(args.source)
    if not tables:
        raise SystemExit("No legacy data found to import.")

    with session_scope() as db:
        crud.ensure_schema(db)
        counts = legacy_import.import_legacy_tables(db, tables, reset=args.reset)

    print(f"imported_users={counts['users']}")
    print(f"imported_tasks={counts['tasks']}")
    print(f"imported_subtasks={counts['subtasks']}")


if __name__ == "__main__":
    main()
