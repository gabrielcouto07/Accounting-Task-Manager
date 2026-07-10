from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


LEGACY_TASK_JSON = """
{
  "id": 1,
  "titulo": "Tarefa legada",
  "categoria": "fiscal",
  "tipo": "rotina",
  "prioridade": "normal",
  "status": "pendente",
  "competencia": "Jun/26",
  "cliente": "Cliente legado",
  "responsavel": "Equipe Fiscal",
  "obs": "",
  "subtarefas": []
}
""".strip()


def create_legacy_database(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE users (
                id VARCHAR PRIMARY KEY,
                nome VARCHAR NOT NULL,
                senha VARCHAR NOT NULL,
                perfil VARCHAR NOT NULL,
                categoria VARCHAR,
                cor VARCHAR NOT NULL DEFAULT '#1e3a5f'
            );

            INSERT INTO users (id, nome, senha, perfil, categoria, cor)
            VALUES ('gerente', 'Gerente', 'gerente123', 'gerente', NULL, '#1e3a5f');

            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            );
            """
        )
        conn.execute("INSERT INTO tasks (id, data) VALUES (?, ?)", (1, LEGACY_TASK_JSON))
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gc-legacy-schema-") as tmp_dir:
        db_path = Path(tmp_dir) / "legacy-schema.db"
        create_legacy_database(db_path)

        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.resolve().as_posix()}"
        os.environ["SESSION_SECRET_KEY"] = "legacy-schema-test-secret"

        from fastapi.testclient import TestClient

        from app.database import engine
        from app.main import app

        try:
            with TestClient(app) as client:
                login = client.post(
                    "/login",
                    data={"user_id": "gerente", "senha": "gerente123"},
                    follow_redirects=False,
                )
                assert login.status_code == 303

                created = client.post(
                    "/api/tasks",
                    json={
                        "titulo": "Nova tarefa em banco legado",
                        "categoria": "fiscal",
                        "tipo": "rotina",
                        "prioridade": "normal",
                        "status": "pendente",
                        "competencia": "Jul/26",
                        "liberacao": None,
                        "vencimento": None,
                        "data_conclusao": None,
                        "cliente": "Cliente Teste",
                        "responsavel": "Equipe Fiscal",
                        "obs": "Garante compatibilidade com tasks.data NOT NULL.",
                        "subtarefas": [],
                    },
                )
                assert created.status_code == 200, created.text

            conn = sqlite3.connect(db_path)
            try:
                legacy_data = conn.execute(
                    "SELECT data FROM tasks WHERE titulo = ?",
                    ("Nova tarefa em banco legado",),
                ).fetchone()
                assert legacy_data == ("{}",)
            finally:
                conn.close()
        finally:
            engine.dispose()

    print("legacy_schema_smoke_test=ok")


if __name__ == "__main__":
    main()
