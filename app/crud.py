from datetime import date
from typing import Iterable

from sqlalchemy import or_, text
from sqlalchemy.orm import Session, selectinload

from app import legacy_import, logic, models, schemas, security


def _table_exists(db: Session, table: str) -> bool:
    result = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table"),
        {"table": table},
    ).first()
    return result is not None


def _column_names(db: Session, table: str) -> set[str]:
    if not _table_exists(db, table):
        return set()
    rows = db.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
    return {row[1] for row in rows}


def _ensure_column(db: Session, table: str, columns: set[str], name: str, ddl: str) -> None:
    if name in columns:
        return
    db.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {ddl}'))
    columns.add(name)


def ensure_schema(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS chamados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                solicitante TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Aberto',
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    chamado_columns = _column_names(db, "chamados")
    if chamado_columns:
        for name, ddl in [
            ("titulo", "titulo TEXT NOT NULL DEFAULT ''"),
            ("descricao", "descricao TEXT NOT NULL DEFAULT ''"),
            ("solicitante", "solicitante TEXT NOT NULL DEFAULT ''"),
            ("status", "status TEXT NOT NULL DEFAULT 'Aberto'"),
            ("criado_em", "criado_em DATETIME DEFAULT CURRENT_TIMESTAMP"),
            ("atualizado_em", "atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP"),
        ]:
            _ensure_column(db, "chamados", chamado_columns, name, ddl)

    task_columns = _column_names(db, "tasks")
    if task_columns:
        for name, ddl in [
            ("data", "data TEXT NOT NULL DEFAULT '{}'"),
            ("legacy_id", "legacy_id TEXT"),
            ("titulo", "titulo VARCHAR"),
            ("categoria", "categoria VARCHAR"),
            ("tipo", "tipo VARCHAR"),
            ("prioridade", "prioridade VARCHAR"),
            ("status", "status VARCHAR"),
            ("competencia", "competencia VARCHAR"),
            ("liberacao", "liberacao DATE"),
            ("vencimento", "vencimento DATE"),
            ("data_conclusao", "data_conclusao DATE"),
            ("cliente", "cliente VARCHAR"),
            ("responsavel", "responsavel VARCHAR"),
            ("obs", "obs VARCHAR"),
            ("created_at", "created_at DATE"),
            ("legacy_raw", "legacy_raw TEXT"),
        ]:
            _ensure_column(db, "tasks", task_columns, name, ddl)

        db.execute(text("UPDATE tasks SET data = '{}' WHERE data IS NULL OR data = ''"))

        if "data" in task_columns:
            rows = db.execute(
                text(
                    """
                    SELECT id, data
                    FROM tasks
                    WHERE data IS NOT NULL
                      AND (titulo IS NULL OR titulo = '')
                    """
                )
            ).mappings().all()
            if rows:
                legacy_import.import_legacy_tables(
                    db,
                    {"users": [], "tasks": [dict(row) for row in rows]},
                    reset=False,
                )

    subtask_columns = _column_names(db, "subtasks")
    if subtask_columns and "legacy_id" not in subtask_columns:
        db.execute(text("ALTER TABLE subtasks ADD COLUMN legacy_id TEXT"))
    db.flush()


def get_users(db: Session) -> list[models.User]:
    users = db.query(models.User).all()
    return sorted(users, key=lambda user: (0 if user.perfil == "gerente" else 1, user.nome.lower()))


def get_user(db: Session, user_id: str) -> models.User | None:
    return db.query(models.User).filter(models.User.id == user_id).first()


def authenticate_user(db: Session, user_id: str, senha: str) -> models.User | None:
    user = get_user(db, user_id)
    if not user or not security.verify_password(senha, user.senha):
        return None
    if security.should_upgrade_password(user.senha):
        user.senha = security.hash_password(senha)
        db.commit()
        db.refresh(user)
    return user


def create_user(db: Session, data: schemas.UserCreate, cor: str) -> models.User:
    user = models.User(
        id=data.id.strip(),
        nome=data.nome.strip(),
        senha=security.hash_password(data.senha),
        perfil=data.perfil,
        categoria=None if data.perfil == "gerente" else data.categoria,
        cor=cor,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def change_user_password(db: Session, user_id: str, senha: str) -> bool:
    user = get_user(db, user_id)
    if not user:
        return False
    user.senha = security.hash_password(senha)
    db.commit()
    return True


def delete_user(db: Session, user_id: str) -> bool:
    user = get_user(db, user_id)
    if not user:
        return False
    db.delete(user)
    db.commit()
    return True


def get_chamados(db: Session, status: str | None = None) -> list[models.Chamado]:
    query = db.query(models.Chamado)
    if status:
        query = query.filter(models.Chamado.status == status)
    return query.order_by(models.Chamado.id.desc()).all()


def get_chamado(db: Session, chamado_id: int) -> models.Chamado | None:
    return db.query(models.Chamado).filter(models.Chamado.id == chamado_id).first()


def create_chamado(
    db: Session,
    *,
    titulo: str,
    descricao: str,
    solicitante: str,
) -> models.Chamado:
    chamado = models.Chamado(
        titulo=titulo.strip(),
        descricao=descricao.strip(),
        solicitante=solicitante,
    )
    db.add(chamado)
    db.commit()
    db.refresh(chamado)
    return chamado


def update_chamado_status(db: Session, chamado_id: int, status: str) -> models.Chamado | None:
    chamado = get_chamado(db, chamado_id)
    if not chamado:
        return None
    chamado.status = status
    db.execute(
        text("UPDATE chamados SET atualizado_em = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": chamado_id},
    )
    db.commit()
    db.refresh(chamado)
    return chamado


def _tasks_query(db: Session):
    return db.query(models.Task).options(selectinload(models.Task.subtarefas))


def scoped_tasks_query(
    db: Session,
    current_user: models.User,
    categoria_tab: str = "todas",
):
    query = _tasks_query(db)
    if current_user.perfil == "gerente":
        if categoria_tab != "todas":
            query = query.filter(models.Task.categoria == categoria_tab)
        return query
    return query.filter(models.Task.categoria == current_user.categoria)


def get_filtered_tasks(
    db: Session,
    current_user: models.User,
    categoria_tab: str = "todas",
    status: str = "todos",
    categoria: str = "todas",
    tipo: str = "todos",
    prioridade: str = "todas",
    busca: str = "",
) -> list[models.Task]:
    query = scoped_tasks_query(db, current_user, categoria_tab)

    if status != "todos":
        query = query.filter(models.Task.status == status)
    if categoria != "todas":
        query = query.filter(models.Task.categoria == categoria)
    if tipo != "todos":
        query = query.filter(models.Task.tipo == tipo)
    if prioridade != "todas":
        query = query.filter(models.Task.prioridade == prioridade)
    if busca:
        like = f"%{busca.strip()}%"
        query = query.filter(
            or_(
                models.Task.titulo.ilike(like),
                models.Task.cliente.ilike(like),
                models.Task.responsavel.ilike(like),
            )
        )

    return query.all()


def get_task(db: Session, task_id: int) -> models.Task | None:
    return (
        _tasks_query(db)
        .filter(models.Task.id == task_id)
        .first()
    )


def _apply_task_fields(task: models.Task, data: schemas.TaskCreate | schemas.TaskUpdate) -> None:
    task.titulo = data.titulo.strip()
    task.categoria = data.categoria
    task.tipo = data.tipo
    task.prioridade = data.prioridade
    task.status = data.status
    task.competencia = data.competencia
    task.liberacao = data.liberacao
    task.vencimento = data.vencimento
    task.cliente = data.cliente or ""
    task.responsavel = data.responsavel or ""
    task.obs = data.obs or ""
    task.data_conclusao = data.data_conclusao

    if task.status == "concluida" and not task.data_conclusao:
        task.data_conclusao = date.today()
    if task.status != "concluida":
        task.data_conclusao = None


def _replace_subtasks(
    db: Session,
    task: models.Task,
    subtasks: Iterable[schemas.SubtaskCreate],
) -> None:
    task.subtarefas.clear()
    db.flush()
    for subtask in subtasks:
        db.add(
            models.Subtask(
                task_id=task.id,
                titulo=subtask.titulo.strip(),
                responsavel=subtask.responsavel or "",
                concluida=subtask.concluida,
                liberacao=subtask.liberacao or "",
                vencimento=subtask.vencimento,
                data_conclusao=subtask.data_conclusao or "",
            )
        )


def create_task(db: Session, task_data: schemas.TaskCreate) -> models.Task:
    task = models.Task(created_at=date.today(), legacy_data="{}")
    _apply_task_fields(task, task_data)
    db.add(task)
    db.flush()
    _replace_subtasks(db, task, task_data.subtarefas)
    db.flush()
    logic.sync_task_status_from_subtasks(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(
    db: Session,
    task_id: int,
    data: schemas.TaskUpdate,
) -> models.Task | None:
    task = get_task(db, task_id)
    if not task:
        return None
    _apply_task_fields(task, data)
    _replace_subtasks(db, task, data.subtarefas)
    db.flush()
    logic.sync_task_status_from_subtasks(task)
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task_id: int) -> bool:
    task = get_task(db, task_id)
    if not task:
        return False
    db.delete(task)
    db.commit()
    return True


def change_status(db: Session, task_id: int, status: str) -> models.Task | None:
    task = get_task(db, task_id)
    if not task:
        return None
    task.status = status
    if status == "concluida" and not task.data_conclusao:
        task.data_conclusao = date.today()
    elif status != "concluida":
        task.data_conclusao = None
    db.commit()
    db.refresh(task)
    return task


def set_task_conclusao_data(
    db: Session,
    task_id: int,
    value: date | None,
) -> models.Task | None:
    task = get_task(db, task_id)
    if not task:
        return None
    task.data_conclusao = value
    if value:
        task.status = "concluida"
    elif task.status == "concluida":
        task.status = "pendente"
    db.commit()
    db.refresh(task)
    return task


def replicate_task(
    db: Session,
    task_id: int,
    nova_competencia: str,
) -> models.Task | None:
    original = get_task(db, task_id)
    if not original:
        return None

    copy = models.Task(
        titulo=original.titulo,
        categoria=original.categoria,
        tipo=original.tipo,
        prioridade=original.prioridade,
        status="pendente",
        competencia=nova_competencia,
        liberacao=original.liberacao,
        vencimento=None,
        cliente=original.cliente,
        responsavel=original.responsavel,
        obs=original.obs,
        created_at=date.today(),
        legacy_data="{}",
        data_conclusao=None,
    )
    db.add(copy)
    db.flush()

    for subtask in original.subtarefas:
        db.add(
            models.Subtask(
                task_id=copy.id,
                titulo=subtask.titulo,
                responsavel=subtask.responsavel,
                concluida=False,
                liberacao=subtask.liberacao,
                vencimento=subtask.vencimento,
                data_conclusao="",
            )
        )

    db.commit()
    db.refresh(copy)
    return copy


def add_subtask(
    db: Session,
    task_id: int,
    data: schemas.SubtaskCreate,
) -> models.Task | None:
    task = get_task(db, task_id)
    if not task:
        return None
    db.add(
        models.Subtask(
            task_id=task_id,
            titulo=data.titulo.strip(),
            responsavel=data.responsavel or "",
            concluida=data.concluida,
            liberacao=data.liberacao or "",
            vencimento=data.vencimento,
            data_conclusao=data.data_conclusao or "",
        )
    )
    db.flush()
    db.refresh(task)
    logic.sync_task_status_from_subtasks(task)
    db.commit()
    db.refresh(task)
    return task


def update_subtask(
    db: Session,
    task_id: int,
    subtask_id: int,
    data: schemas.SubtaskCreate,
) -> models.Task | None:
    task = get_task(db, task_id)
    if not task:
        return None
    subtask = next((item for item in task.subtarefas if item.id == subtask_id), None)
    if not subtask:
        return None

    subtask.titulo = data.titulo.strip()
    subtask.responsavel = data.responsavel or ""
    subtask.concluida = data.concluida
    subtask.liberacao = data.liberacao or ""
    subtask.vencimento = data.vencimento
    subtask.data_conclusao = data.data_conclusao or ""
    logic.sync_task_status_from_subtasks(task)
    db.commit()
    db.refresh(task)
    return task


def toggle_subtask(
    db: Session,
    task_id: int,
    subtask_id: int,
) -> models.Task | None:
    task = get_task(db, task_id)
    if not task:
        return None
    subtask = next((item for item in task.subtarefas if item.id == subtask_id), None)
    if not subtask:
        return None

    subtask.concluida = not subtask.concluida
    subtask.data_conclusao = date.today().isoformat() if subtask.concluida else ""
    logic.sync_task_status_from_subtasks(task)
    db.commit()
    db.refresh(task)
    return task


def delete_subtask(
    db: Session,
    task_id: int,
    subtask_id: int,
) -> models.Task | None:
    task = get_task(db, task_id)
    if not task:
        return None
    subtask = next((item for item in task.subtarefas if item.id == subtask_id), None)
    if not subtask:
        return None

    db.delete(subtask)
    db.flush()
    db.refresh(task)
    logic.sync_task_status_from_subtasks(task)
    db.commit()
    db.refresh(task)
    return task


def seed_demo_data(db: Session) -> None:
    if not get_users(db):
        users = [
            {
                "id": "gerente",
                "nome": "Gerente",
                "senha": "gerente123",
                "perfil": "gerente",
                "categoria": None,
                "cor": "#1e3a5f",
            },
            {
                "id": "fiscal",
                "nome": "Equipe Fiscal",
                "senha": "equipe123",
                "perfil": "equipe",
                "categoria": "fiscal",
                "cor": "#2563eb",
            },
            {
                "id": "dp",
                "nome": "Equipe DP",
                "senha": "equipe123",
                "perfil": "equipe",
                "categoria": "dp",
                "cor": "#16a34a",
            },
            {
                "id": "contabil",
                "nome": "Equipe Contábil",
                "senha": "equipe123",
                "perfil": "equipe",
                "categoria": "contabil",
                "cor": "#7c3aed",
            },
            {
                "id": "apoio",
                "nome": "Equipe Apoio",
                "senha": "equipe123",
                "perfil": "equipe",
                "categoria": "honorarios",
                "cor": "#ea580c",
            },
        ]
        for user in users:
            user["senha"] = security.hash_password(user["senha"])
        db.add_all(models.User(**user) for user in users)
        db.flush()

    if db.query(models.Task).count() > 0:
        return

    demo_tasks = [
        schemas.TaskCreate(
            titulo="SPED Fiscal",
            categoria="fiscal",
            tipo="rotina",
            prioridade="alta",
            status="em_andamento",
            competencia="Jun/26",
            liberacao=date(2026, 7, 1),
            vencimento=date(2026, 7, 15),
            cliente="Cliente Alfa",
            responsavel="Equipe Fiscal",
            obs="Conferir notas de entrada antes do envio.",
            subtarefas=[
                schemas.SubtaskCreate(
                    titulo="Conferir XMLs importados",
                    responsavel="Ana",
                    concluida=True,
                    liberacao="2026-07-01",
                    vencimento=date(2026, 7, 8),
                    data_conclusao="2026-07-08",
                ),
                schemas.SubtaskCreate(
                    titulo="Validar arquivo no PVA",
                    responsavel="Bruno",
                    liberacao="2026-07-08",
                    vencimento=date(2026, 7, 12),
                ),
            ],
        ),
        schemas.TaskCreate(
            titulo="Folha de pagamento",
            categoria="dp",
            tipo="rotina",
            prioridade="critica",
            status="pendente",
            competencia="Jun/26",
            liberacao=date(2026, 7, 1),
            vencimento=date(2026, 7, 5),
            cliente="Cliente Beta",
            responsavel="Equipe DP",
            obs="Aguardando apontamentos finais.",
            subtarefas=[
                schemas.SubtaskCreate(
                    titulo="Conferir admissões e desligamentos",
                    responsavel="Carla",
                    liberacao="2026-07-01",
                    vencimento=date(2026, 7, 4),
                ),
                schemas.SubtaskCreate(
                    titulo="Enviar recibos ao cliente",
                    responsavel="Carla",
                    liberacao="NA",
                    vencimento=date(2026, 7, 5),
                ),
            ],
        ),
        schemas.TaskCreate(
            titulo="Balanço mensal",
            categoria="contabil",
            tipo="rotina",
            prioridade="normal",
            status="pendente",
            competencia="Jun/26",
            liberacao=date(2026, 7, 3),
            vencimento=date(2026, 7, 31),
            cliente="Cliente Gama",
            responsavel="Equipe Contábil",
            obs="Fechamento aguardando conciliação bancária.",
        ),
        schemas.TaskCreate(
            titulo="Alteração contratual",
            categoria="societario",
            tipo="extraordinaria",
            prioridade="alta",
            status="em_andamento",
            competencia="Jun/26",
            liberacao=date(2026, 7, 2),
            vencimento=date(2026, 7, 10),
            cliente="Cliente Delta",
            responsavel="Equipe Apoio",
            obs="Processo extraordinário solicitado pelo cliente.",
            subtarefas=[
                schemas.SubtaskCreate(
                    titulo="Coletar documentos dos sócios",
                    responsavel="Marina",
                    concluida=True,
                    liberacao="2026-07-02",
                    vencimento=date(2026, 7, 6),
                    data_conclusao="2026-07-06",
                ),
                schemas.SubtaskCreate(
                    titulo="Protocolar alteração",
                    responsavel="Marina",
                    liberacao="2026-07-06",
                    vencimento=date(2026, 7, 10),
                ),
            ],
        ),
        schemas.TaskCreate(
            titulo="Cobrança de honorários",
            categoria="honorarios",
            tipo="rotina",
            prioridade="baixa",
            status="concluida",
            competencia="Jun/26",
            liberacao=date(2026, 6, 25),
            vencimento=date(2026, 7, 3),
            data_conclusao=date(2026, 7, 2),
            cliente="Carteira mensal",
            responsavel="Equipe Apoio",
            obs="Concluída no prazo.",
        ),
    ]

    for task in demo_tasks:
        create_task(db, task)


def bootstrap_data(db: Session) -> dict[str, int | str]:
    if db.query(models.Task).count() > 0:
        return {
            "source": "existing",
            "users": db.query(models.User).count(),
            "tasks": db.query(models.Task).count(),
            "subtasks": db.query(models.Subtask).count(),
        }

    tables = legacy_import.load_legacy_tables()
    if tables.get("users") and tables.get("tasks"):
        counts = legacy_import.import_legacy_tables(db, tables)
        counts["source"] = "legacy"
        return counts

    seed_demo_data(db)
    return {
        "source": "demo",
        "users": db.query(models.User).count(),
        "tasks": db.query(models.Task).count(),
        "subtasks": db.query(models.Subtask).count(),
    }
