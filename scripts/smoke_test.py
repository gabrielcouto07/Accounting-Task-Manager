from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gc-smoke-") as tmp_dir:
        db_path = Path(tmp_dir) / "smoke.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.resolve().as_posix()}"
        os.environ["SESSION_SECRET_KEY"] = "smoke-test-secret"

        from fastapi.testclient import TestClient

        from app import models, security
        from app.database import SessionLocal, engine
        from app.main import app

        try:
            with TestClient(app) as client:
                login = client.post(
                    "/login",
                    data={"user_id": "gerente", "senha": "gerente123"},
                    follow_redirects=False,
                )
                assert login.status_code == 303
                assert login.headers.get("location") == "/dashboard"

                dashboard = client.get("/dashboard")
                assert dashboard.status_code == 200
                assert "Dashboard" in dashboard.text

                created = client.post(
                    "/api/tasks",
                    json={
                        "titulo": "Smoke test",
                        "categoria": "fiscal",
                        "tipo": "rotina",
                        "prioridade": "normal",
                        "status": "pendente",
                        "competencia": "Jul/26",
                        "liberacao": None,
                        "vencimento": None,
                        "data_conclusao": None,
                        "cliente": "Cliente Teste",
                        "responsavel": "Equipe Teste",
                        "obs": "Validacao automatica",
                        "subtarefas": [
                            {
                                "titulo": "Subtarefa smoke",
                                "responsavel": "Ana",
                                "concluida": False,
                                "liberacao": "",
                                "vencimento": None,
                                "data_conclusao": "",
                            }
                        ],
                    },
                )
                assert created.status_code == 200
                task_id = created.json()["id"]

                updated = client.put(
                    f"/api/tasks/{task_id}",
                    json={
                        "titulo": "Smoke test atualizado",
                        "categoria": "fiscal",
                        "tipo": "extraordinaria",
                        "prioridade": "alta",
                        "status": "em_andamento",
                        "competencia": "Ago/26",
                        "liberacao": None,
                        "vencimento": None,
                        "data_conclusao": None,
                        "cliente": "Cliente Teste",
                        "responsavel": "Equipe Teste",
                        "obs": "Atualizado",
                        "subtarefas": [],
                    },
                )
                assert updated.status_code == 200

                replicated = client.post(
                    f"/api/tasks/{task_id}/replicate",
                    json={"nova_competencia": "Set/26"},
                )
                assert replicated.status_code == 200

                created_user = client.post(
                    "/api/users",
                    json={
                        "id": "smoke.user",
                        "nome": "Smoke User",
                        "senha": "123456",
                        "perfil": "equipe",
                        "categoria": "cliente",
                    },
                )
                assert created_user.status_code == 200

                deleted = client.delete(f"/api/tasks/{task_id}")
                assert deleted.status_code == 200

            db = SessionLocal()
            try:
                gerente = db.get(models.User, "gerente")
                assert gerente is not None
                assert security.is_hashed_password(gerente.senha)
            finally:
                db.close()
        finally:
            engine.dispose()

    print("smoke_test=ok")


if __name__ == "__main__":
    main()
