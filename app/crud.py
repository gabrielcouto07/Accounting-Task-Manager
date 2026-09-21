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

        # Coluna nova (2026-09): quem abriu a obrigacao. Fica NULL nas
        # tarefas antigas, o que e esperado e nao quebra nada.
        _ensure_column(db, "tasks", task_columns, "solicitante", "solicitante VARCHAR")

    user_columns = _column_names(db, "users")
    if user_columns:
        # Coluna nova (2026-09): forca troca de senha no primeiro acesso.
        # DEFAULT 0 => nenhum usuario que ja existe e afetado.
        _ensure_column(
            db,
            "users",
            user_columns,
            "must_change_password",
            "must_change_password BOOLEAN NOT NULL DEFAULT 0",
        )
        db.execute(
            text("UPDATE users SET must_change_password = 0 WHERE must_change_password IS NULL")
        )

    subtask_columns = _column_names(db, "subtasks")
    if subtask_columns and "legacy_id" not in subtask_columns:
        db.execute(text("ALTER TABLE subtasks ADD COLUMN legacy_id TEXT"))

    # Indices auxiliares. CREATE INDEX IF NOT EXISTS e idempotente e barato.
    for ddl in (
        "CREATE INDEX IF NOT EXISTS ix_tasks_competencia ON tasks (competencia)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_categoria ON tasks (categoria)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status)",
        "CREATE INDEX IF NOT EXISTS ix_subtasks_task_id ON subtasks (task_id)",
    ):
        db.execute(text(ddl))

    db.flush()


def upgrade_plaintext_passwords(db: Session) -> int:
    """Converte senhas gravadas em texto puro para hash PBKDF2.

    O banco herdado do sistema antigo guardava a senha literal. O login ja
    fazia o upgrade quando a pessoa entrava, mas quem nunca entrou continuava
    com a senha legivel no arquivo .db. Aqui isso e resolvido de uma vez.
    A senha da pessoa NAO muda - muda apenas a forma de guardar.
    """
    convertidos = 0
    for user in db.query(models.User).all():
        if security.is_hashed_password(user.senha):
            continue
        user.senha = security.hash_password(user.senha or "")
        convertidos += 1
    if convertidos:
        db.flush()
    return convertidos


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


def create_user(
    db: Session,
    data: schemas.UserCreate,
    cor: str,
    must_change_password: bool = True,
) -> models.User:
    user = models.User(
        id=data.id.strip(),
        nome=data.nome.strip(),
        senha=security.hash_password(data.senha),
        perfil=data.perfil,
        categoria=None if data.perfil == "gerente" else data.categoria,
        cor=cor,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def change_user_password(
    db: Session,
    user_id: str,
    senha: str,
    *,
    must_change_password: bool = False,
) -> bool:
    """Grava uma nova senha (sempre com hash).

    `must_change_password=True` e usado quando o GERENTE reseta a senha de
    outra pessoa: o dono da conta sera obrigado a trocar no proximo acesso.
    Quando a propria pessoa troca a senha, o flag e desligado.
    """
    user = get_user(db, user_id)
    if not user:
        return False
    user.senha = security.hash_password(senha)
    user.must_change_password = must_change_password
    db.commit()
    return True


def count_gerentes(db: Session) -> int:
    return db.query(models.User).filter(models.User.perfil == "gerente").count()


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


def delete_chamado(db: Session, chamado_id: int) -> bool:
    chamado = get_chamado(db, chamado_id)
    if not chamado:
        return False
    db.delete(chamado)
    db.commit()
    return True


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


def _scope_conditions(current_user: models.User, categoria_tab: str = "todas") -> list:
    """Restricoes de visibilidade: gerente ve tudo (ou a aba escolhida),
    usuario de equipe ve apenas a propria categoria."""
    if current_user.perfil != "gerente":
        return [models.Task.categoria == current_user.categoria]
    if categoria_tab != "todas":
        return [models.Task.categoria == categoria_tab]
    return []


def scoped_tasks_query(
    db: Session,
    current_user: models.User,
    categoria_tab: str = "todas",
):
    query = _tasks_query(db)
    for condicao in _scope_conditions(current_user, categoria_tab):
        query = query.filter(condicao)
    return query


SEM_VALOR = "__sem__"


def _escape_like(valor: str) -> str:
    """Neutraliza os coringas do LIKE para que % e _ sejam texto literal."""
    return valor.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtrar_por_pessoa(query, coluna, valor: str, *, contem: bool):
    """Aplica o filtro de responsavel/solicitante sobre uma coluna de texto.

    `contem=True` usa LIKE %valor% porque o campo Responsavel e texto livre e
    no banco existem registros como "ISABELLE E MARESSA" ou "ISABELLE, MARESSA".
    Com igualdade exata, escolher "ISABELLE" perderia essas linhas.
    """
    valor = (valor or "").strip()
    if not valor:
        return query
    if valor == SEM_VALOR:
        return query.filter(or_(coluna.is_(None), coluna == ""))
    padrao = _escape_like(valor)
    alvo = f"%{padrao}%" if contem else padrao
    return query.filter(coluna.ilike(alvo, escape="\\"))


def aplicar_filtros_pessoa(query, responsavel: str = "", solicitante: str = ""):
    query = _filtrar_por_pessoa(query, models.Task.responsavel, responsavel, contem=True)
    return _filtrar_por_pessoa(query, models.Task.solicitante, solicitante, contem=False)


def get_filtered_tasks(
    db: Session,
    current_user: models.User,
    categoria_tab: str = "todas",
    status: str = "todos",
    categoria: str = "todas",
    tipo: str = "todos",
    prioridade: str = "todas",
    busca: str = "",
    responsavel: str = "",
    solicitante: str = "",
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
        like = f"%{_escape_like(busca.strip())}%"
        query = query.filter(
            or_(
                models.Task.titulo.ilike(like, escape="\\"),
                models.Task.cliente.ilike(like, escape="\\"),
                models.Task.responsavel.ilike(like, escape="\\"),
            )
        )

    query = aplicar_filtros_pessoa(query, responsavel, solicitante)
    return query.all()


def _valores_distintos(db: Session, current_user: models.User, categoria_tab: str, coluna) -> list[str]:
    """Valores unicos de uma coluna de texto, dentro do escopo do usuario.

    Usado para montar as opcoes dos selects de Responsavel e Solicitante.
    Duplicatas que diferem so por caixa/espaco ("Isabelle" x "ISABELLE") sao
    agrupadas, mantendo a primeira grafia encontrada.
    """
    # Query "crua" de uma coluna so: nao reaproveita scoped_tasks_query porque
    # aquela carrega as subtarefas (selectinload), inutil aqui.
    base = db.query(coluna).distinct()
    for condicao in _scope_conditions(current_user, categoria_tab):
        base = base.filter(condicao)
    vistos: dict[str, str] = {}
    for (valor,) in base:
        texto = (valor or "").strip()
        if not texto:
            continue
        vistos.setdefault(texto.casefold(), texto)
    return sorted(vistos.values(), key=str.casefold)


def listar_responsaveis(db: Session, current_user: models.User, categoria_tab: str = "todas") -> list[str]:
    return _valores_distintos(db, current_user, categoria_tab, models.Task.responsavel)


def listar_solicitantes(db: Session, current_user: models.User, categoria_tab: str = "todas") -> list[str]:
    return _valores_distintos(db, current_user, categoria_tab, models.Task.solicitante)


def competencias_existentes(db: Session) -> list[str]:
    return [row[0] for row in db.query(models.Task.competencia).distinct() if row[0]]


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


def create_task(
    db: Session,
    task_data: schemas.TaskCreate,
    solicitante: str | None = None,
) -> models.Task:
    """Cria a obrigacao. `solicitante` e gravado uma unica vez, na criacao,
    e nao e alterado depois por `update_task`."""
    task = models.Task(
        created_at=date.today(),
        legacy_data="{}",
        solicitante=(solicitante or "").strip() or None,
    )
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
        solicitante=original.solicitante,
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
