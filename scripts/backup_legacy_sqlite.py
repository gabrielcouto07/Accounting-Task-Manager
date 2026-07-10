from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT_DIR / "backups" / "legacy_sqlite"
LEGACY_NAMES = ("controle.db", "controle.db-shm", "controle.db-wal")


def find_source_dir() -> Path:
    for directory in (ROOT_DIR, ROOT_DIR / "app"):
        if (directory / "controle.db").exists():
            return directory
    raise FileNotFoundError("controle.db not found at repository root or app/controle.db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up legacy SQLite db, shm and wal files.")
    parser.add_argument("--source-dir", type=Path, default=None, help="Directory containing controle.db files.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Backup output directory.")
    args = parser.parse_args()

    source_dir = args.source_dir or find_source_dir()
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for name in LEGACY_NAMES:
        source = source_dir / name
        if not source.exists():
            print(f"missing={source}")
            continue
        destination = out_dir / f"{timestamp}.{name}"
        shutil.copy2(source, destination)
        print(f"backup={destination} bytes={destination.stat().st_size}")


if __name__ == "__main__":
    main()
