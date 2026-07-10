from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def run_step(label: str, args: list[str]) -> None:
    print(f"[check] {label}", flush=True)
    subprocess.run(
        [sys.executable, *args],
        cwd=ROOT_DIR,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local project checks used before shipping updates.")
    parser.add_argument(
        "--verify-migration",
        action="store_true",
        help="Also compare the live app database with the legacy export counts.",
    )
    args = parser.parse_args()

    run_step("compileall", ["-m", "compileall", "app", "scripts"])
    run_step("smoke-test", ["scripts/smoke_test.py"])

    if args.verify_migration:
        run_step("verify-migration", ["scripts/verify_counts.py"])

    print("[check] all-good", flush=True)


if __name__ == "__main__":
    main()
