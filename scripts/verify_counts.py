from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app import legacy_import, models
from app.database import SessionLocal

DEFAULT_SOURCE = ROOT_DIR / "backups" / "legacy_sqlite" / "export" / "all_tables.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare legacy export counts with the FastAPI SQLite database. Use this only right after migration."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="all_tables.json export path.")
    args = parser.parse_args()

    tables = legacy_import.load_legacy_tables(args.source)
    legacy = legacy_import.legacy_counts(tables)

    db = SessionLocal()
    try:
        app_counts = {
            "users": db.query(models.User).count(),
            "tasks": db.query(models.Task).count(),
            "subtasks": db.query(models.Subtask).count(),
        }
        users = [user.id for user in db.query(models.User).order_by(models.User.id).all()]
    finally:
        db.close()

    print("legacy_counts", legacy)
    print("app_counts", app_counts)
    print("users", users)
    print("extra_user_present", "rafael.pinheiro" in users)

    if legacy != app_counts:
        raise SystemExit("Count mismatch between legacy export and app database.")


if __name__ == "__main__":
    main()
