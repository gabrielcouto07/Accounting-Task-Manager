from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app import models, security


ROOT_DIR = Path(__file__).resolve().parent.parent
LEGACY_DB_CANDIDATES = (
    ROOT_DIR / "controle.db",
    ROOT_DIR / "app" / "controle.db",
)
LEGACY_EXPORT_JSON = ROOT_DIR / "backups" / "legacy_sqlite" / "export" / "all_tables.json"


def find_legacy_db() -> Path | None:
    for path in LEGACY_DB_CANDIDATES:
        if path.exists():
            return path
    return None


def parse_date(value: Any) -> date | None:
    if not value or value == "NA":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def read_legacy_sqlite(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        table_rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        tables: dict[str, list[dict[str, Any]]] = {}
        for table_row in table_rows:
            table = table_row["name"]
            rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            tables[table] = [dict(row) for row in rows]
        return tables
    finally:
        conn.close()


def load_legacy_tables(source: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    source = source or LEGACY_EXPORT_JSON
    if source.exists():
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if "tables" in payload:
            return payload["tables"]
        return payload

    legacy_db = find_legacy_db()
    if not legacy_db:
        return {}
    return read_legacy_sqlite(legacy_db)


def legacy_counts(tables: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    task_rows = tables.get("tasks", [])
    subtask_count = 0
    for row in task_rows:
        try:
            data = json.loads(row.get("data") or "{}")
        except json.JSONDecodeError:
            data = {}
        subtask_count += len(data.get("subtarefas") or [])
    return {
        "users": len(tables.get("users", [])),
        "tasks": len(task_rows),
        "subtasks": subtask_count,
    }


def _task_payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(row.get("data") or "{}")
    except json.JSONDecodeError:
        data = {}
    data.setdefault("id", row.get("id"))
    return data


def _set_task_fields(task: models.Task, data: dict[str, Any], raw_data: str) -> None:
    task.legacy_id = str(data.get("id") or "")
    task.titulo = data.get("titulo") or "Sem titulo"
    task.categoria = data.get("categoria") or "fiscal"
    task.tipo = data.get("tipo") or "rotina"
    task.prioridade = data.get("prioridade") or "normal"
    task.status = data.get("status") or "pendente"
    task.competencia = data.get("competencia") or "Jun/26"
    task.liberacao = parse_date(data.get("liberacao"))
    task.vencimento = parse_date(data.get("vencimento"))
    task.data_conclusao = parse_date(data.get("dataConclusao"))
    task.cliente = data.get("cliente") or ""
    task.responsavel = data.get("responsavel") or ""
    task.obs = data.get("obs") or ""
    task.created_at = parse_date(data.get("createdAt")) or date.today()
    task.legacy_data = raw_data or "{}"
    task.legacy_raw = raw_data


def import_legacy_tables(
    db: Session,
    tables: dict[str, list[dict[str, Any]]],
    *,
    reset: bool = False,
) -> dict[str, int]:
    if reset:
        db.query(models.Subtask).delete()
        db.query(models.Task).delete()
        db.query(models.User).delete()
        db.query(models.AppMetadata).delete()
        db.flush()

    imported_users = 0
    for row in tables.get("users", []):
        password = row.get("senha") or ""
        user = db.get(models.User, row["id"]) or models.User(id=row["id"])
        user.nome = row.get("nome") or row["id"]
        user.senha = (
            password
            if security.is_hashed_password(password)
            else security.hash_password(password)
        )
        user.perfil = row.get("perfil") or "equipe"
        user.categoria = row.get("categoria")
        user.cor = row.get("cor") or "#1e3a5f"
        db.add(user)
        imported_users += 1

    imported_tasks = 0
    imported_subtasks = 0
    for row in tables.get("tasks", []):
        raw_data = row.get("data") or "{}"
        data = _task_payload(row)
        task_id = int(row.get("id") or data.get("id"))
        task = db.get(models.Task, task_id) or models.Task(id=task_id)
        _set_task_fields(task, data, raw_data)
        db.add(task)
        db.flush()

        db.query(models.Subtask).filter(models.Subtask.task_id == task.id).delete()
        for subtask_data in data.get("subtarefas") or []:
            subtask = models.Subtask(
                task_id=task.id,
                legacy_id=str(subtask_data.get("id") or ""),
                titulo=subtask_data.get("titulo") or "Sem titulo",
                responsavel=subtask_data.get("responsavel") or "",
                concluida=bool(subtask_data.get("concluida")),
                liberacao=subtask_data.get("liberacao") or "",
                vencimento=parse_date(subtask_data.get("vencimento")),
                data_conclusao=subtask_data.get("dataConclusao") or "",
            )
            db.add(subtask)
            imported_subtasks += 1
        imported_tasks += 1

    meta = db.get(models.AppMetadata, "legacy_imported_at") or models.AppMetadata(
        key="legacy_imported_at"
    )
    meta.value = datetime.now().isoformat(timespec="seconds")
    db.add(meta)
    db.flush()

    return {
        "users": imported_users,
        "tasks": imported_tasks,
        "subtasks": imported_subtasks,
    }
