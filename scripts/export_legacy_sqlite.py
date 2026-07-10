from __future__ import annotations

import argparse
import base64
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_DIR = ROOT_DIR / "backups" / "legacy_sqlite"


def find_latest_backup_db(backup_dir: Path) -> Path | None:
    candidates = sorted(backup_dir.glob("*.controle.db"))
    return candidates[-1] if candidates else None


def find_legacy_db() -> Path:
    for path in (ROOT_DIR / "controle.db", ROOT_DIR / "app" / "controle.db"):
        if path.exists():
            return path
    raise FileNotFoundError("controle.db not found at repository root or app/controle.db")


def sqlite_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__blob_base64__": base64.b64encode(value).decode("ascii")}
    return value


def rows_as_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [{key: json_safe(row[key]) for key in row.keys()} for row in rows]


def inspect_database(db_path: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        objects = conn.execute(
            """
            SELECT name, type, sql
            FROM sqlite_master
            WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()

        report: dict[str, Any] = {
            "source_db": str(db_path),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "journal_mode": journal_mode,
            "tables": {},
        }
        exports: dict[str, list[dict[str, Any]]] = {}

        for obj in objects:
            table = obj["name"]
            ident = sqlite_identifier(table)
            columns = rows_as_dicts(conn.execute(f"PRAGMA table_info({ident})").fetchall())
            foreign_keys = rows_as_dicts(conn.execute(f"PRAGMA foreign_key_list({ident})").fetchall())
            indexes = []
            for index_row in conn.execute(f"PRAGMA index_list({ident})").fetchall():
                index = dict(index_row)
                index_ident = sqlite_identifier(index["name"])
                index["columns"] = rows_as_dicts(
                    conn.execute(f"PRAGMA index_info({index_ident})").fetchall()
                )
                indexes.append(index)

            row_count = conn.execute(f"SELECT COUNT(*) FROM {ident}").fetchone()[0]
            report["tables"][table] = {
                "type": obj["type"],
                "sql": obj["sql"],
                "row_count": row_count,
                "columns": columns,
                "primary_keys": [col["name"] for col in columns if col["pk"]],
                "foreign_keys": foreign_keys,
                "indexes": indexes,
            }

            if obj["type"] == "table":
                rows = conn.execute(f"SELECT * FROM {ident}").fetchall()
                exports[table] = rows_as_dicts(rows)

        return report, exports
    finally:
        conn.close()


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Legacy SQLite Schema Report",
        "",
        f"- Source DB: `{report['source_db']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Journal mode: `{report['journal_mode']}`",
        "",
    ]
    for table, info in report["tables"].items():
        lines.extend(
            [
                f"## `{table}`",
                "",
                f"- Type: `{info['type']}`",
                f"- Row count: `{info['row_count']}`",
                f"- Primary keys: `{', '.join(info['primary_keys']) or 'none'}`",
                "",
                "### Columns",
                "",
                "| Name | Type | Not Null | Default | PK |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for column in info["columns"]:
            lines.append(
                f"| `{column['name']}` | `{column['type']}` | `{column['notnull']}` | "
                f"`{column['dflt_value']}` | `{column['pk']}` |"
            )
        lines.extend(["", "### Foreign Keys", ""])
        if info["foreign_keys"]:
            lines.extend(["| From | To Table | To Column | On Update | On Delete |", "| --- | --- | --- | --- | --- |"])
            for fk in info["foreign_keys"]:
                lines.append(
                    f"| `{fk['from']}` | `{fk['table']}` | `{fk['to']}` | "
                    f"`{fk['on_update']}` | `{fk['on_delete']}` |"
                )
        else:
            lines.append("None.")
        lines.extend(["", "### Indexes", ""])
        if info["indexes"]:
            for index in info["indexes"]:
                cols = ", ".join(col["name"] for col in index["columns"])
                lines.append(f"- `{index['name']}` unique={index['unique']} origin=`{index['origin']}` columns=`{cols}`")
        else:
            lines.append("None.")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export legacy controle.db schema and data.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite database path to inspect.")
    parser.add_argument("--out", type=Path, default=DEFAULT_BACKUP_DIR, help="Output directory.")
    args = parser.parse_args()

    output_dir = args.out
    export_dir = output_dir / "export"
    export_dir.mkdir(parents=True, exist_ok=True)

    db_path = args.db or find_latest_backup_db(output_dir) or find_legacy_db()
    report, exports = inspect_database(db_path)

    (output_dir / "schema_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_markdown(report, output_dir / "schema_report.md")

    combined = {
        "source_db": str(db_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "row_counts": {table: len(rows) for table, rows in exports.items()},
        "tables": exports,
    }
    (export_dir / "all_tables.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for table, rows in exports.items():
        (export_dir / f"{table}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"schema_report_json={output_dir / 'schema_report.json'}")
    print(f"schema_report_md={output_dir / 'schema_report.md'}")
    print(f"combined_export={export_dir / 'all_tables.json'}")
    for table, rows in exports.items():
        print(f"exported {table}: {len(rows)} rows")


if __name__ == "__main__":
    main()
