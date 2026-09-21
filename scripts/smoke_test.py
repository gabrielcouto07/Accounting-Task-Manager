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

        from app import email_service
        from app import models, security
        from app.database import SessionLocal, engine
        from app.main import app

        try:
            os.environ["SMTP_USER"] = ""
            assert email_service.send_email("teste@example.com", "Smoke", "Teste") is False

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

                # --- filtros novos do dashboard --------------------------
                # A tarefa foi criada pelo usuario logado, entao o solicitante
                # gravado deve ser o nome dele.
                with_filter = client.get(
                    "/dashboard",
                    params={"responsavel": "Equipe Teste", "solicitante": "Gerente"},
                )
                assert with_filter.status_code == 200
                assert "Smoke test atualizado" in with_filter.text

                sem_resultado = client.get(
                    "/dashboard",
                    params={"responsavel": "nao-existe-ninguem-assim"},
                )
                assert sem_resultado.status_code == 200
                assert "Smoke test atualizado" not in sem_resultado.text

                sem_responsavel = client.get("/dashboard", params={"responsavel": "__sem__"})
                assert sem_responsavel.status_code == 200

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

            # --- troca de senha obrigatoria no primeiro acesso -------------
            with TestClient(app) as novo:
                login = novo.post(
                    "/login",
                    data={"user_id": "smoke.user", "senha": "123456"},
                    follow_redirects=False,
                )
                assert login.status_code == 303
                assert login.headers.get("location") == "/trocar-senha"

                # Enquanto nao trocar, qualquer tela leva de volta para la.
                bloqueado = novo.get("/dashboard", follow_redirects=False)
                assert bloqueado.status_code == 303
                assert bloqueado.headers.get("location") == "/trocar-senha"

                # A propria tela de troca precisa abrir.
                assert novo.get("/trocar-senha").status_code == 200

                # Senha atual errada nao passa.
                errada = novo.post(
                    "/trocar-senha",
                    data={
                        "senha_atual": "errada",
                        "senha": "novaSenha123",
                        "confirmar_senha": "novaSenha123",
                    },
                    follow_redirects=False,
                )
                assert errada.headers.get("location") == "/trocar-senha"
                assert novo.get("/dashboard", follow_redirects=False).status_code == 303

                trocada = novo.post(
                    "/trocar-senha",
                    data={
                        "senha_atual": "123456",
                        "senha": "novaSenha123",
                        "confirmar_senha": "novaSenha123",
                    },
                    follow_redirects=False,
                )
                assert trocada.status_code == 303
                assert trocada.headers.get("location") == "/dashboard"
                assert novo.get("/dashboard").status_code == 200

            with TestClient(app) as relogin:
                ok = relogin.post(
                    "/login",
                    data={"user_id": "smoke.user", "senha": "novaSenha123"},
                    follow_redirects=False,
                )
                assert ok.headers.get("location") == "/dashboard"

            db = SessionLocal()
            try:
                gerente = db.get(models.User, "gerente")
                assert gerente is not None
                assert security.is_hashed_password(gerente.senha)
                assert gerente.must_change_password is False

                smoke_user = db.get(models.User, "smoke.user")
                assert smoke_user is not None
                assert smoke_user.must_change_password is False  # ja trocou

                # Nenhuma senha pode ficar em texto puro no banco.
                for registro in db.query(models.User).all():
                    assert security.is_hashed_password(registro.senha), registro.id

                # Solicitante gravado na criacao.
                criadas = db.query(models.Task).filter(models.Task.solicitante.isnot(None)).count()
                assert criadas > 0
            finally:
                db.close()
        finally:
            engine.dispose()

    print("smoke_test=ok")


if __name__ == "__main__":
    main()
