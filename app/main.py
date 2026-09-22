from contextlib import asynccontextmanager
from datetime import date
import logging
import os
from pathlib import Path
import secrets
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import auth, crud, email_service, logic, models, schemas
from app.database import Base, engine, get_db, session_scope


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
SENHA_MINIMA = 6

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _session_secret() -> str:
    """Chave usada para assinar o cookie de sessao.

    Antes havia um valor fixo no codigo ("troque-esta-chave-em-producao").
    Quem conhecesse esse texto conseguiria forjar um cookie e entrar como
    qualquer usuario. Agora: usa SESSION_SECRET_KEY se existir; senao gera
    uma chave aleatoria e a guarda em disco, para que as sessoes sobrevivam
    a um restart do servico.
    """
    env_secret = os.getenv("SESSION_SECRET_KEY", "").strip()
    if env_secret:
        return env_secret

    key_file = Path(os.getenv("SESSION_SECRET_FILE", str(ROOT_DIR / ".session_secret")))
    try:
        if key_file.exists():
            stored = key_file.read_text(encoding="utf-8").strip()
            if stored:
                return stored
    except OSError:
        logger.warning("Nao foi possivel ler %s", key_file)

    generated = secrets.token_urlsafe(48)
    try:
        key_file.write_text(generated, encoding="utf-8")
        logger.warning(
            "SESSION_SECRET_KEY nao definida. Chave aleatoria gerada em %s. "
            "Defina a variavel de ambiente para controlar esse valor.",
            key_file,
        )
    except OSError:
        logger.error(
            "SESSION_SECRET_KEY nao definida e nao foi possivel gravar %s. "
            "Usando chave temporaria: todos serao deslogados no proximo restart.",
            key_file,
        )
    return generated


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with session_scope() as db:
        crud.ensure_schema(db)
        crud.bootstrap_data(db)
        convertidas = crud.upgrade_plaintext_passwords(db)
    if convertidas:
        logger.warning("%s senha(s) em texto puro convertida(s) para hash.", convertidas)
    yield


app = FastAPI(title="Controle de Obrigacoes Contabeis", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(),
    session_cookie=os.getenv("SESSION_COOKIE_NAME", "gerenciado_contabil_session"),
    same_site="lax",
    https_only=os.getenv("SESSION_HTTPS_ONLY", "false").strip().lower() in {"1", "true", "yes", "sim"},
    max_age=int(os.getenv("SESSION_MAX_AGE", str(12 * 60 * 60))),
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
CHAMADO_STATUSES = ["Aberto", "Em Andamento", "Resolvido"]
CHAMADO_RECIPIENTS = [
    "apoio.informatica@scientificdental.com",
    "informatica@scientificdental.com",
]
def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


def _flash(request: Request, message: str) -> None:
    request.session.setdefault("_flash", []).append(message)


def _pop_flashes(request: Request) -> list[str]:
    return request.session.pop("_flash", [])


def _redirect_with_flash(request: Request, path: str, message: str) -> RedirectResponse:
    _flash(request, message)
    return _redirect(path)


def _require_admin_user(
    request: Request,
    db: Session = Depends(get_db),
) -> models.User:
    user = auth.get_active_user(request, db)
    if user.perfil != "gerente":
        _flash(request, "Acesso negado")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Acesso negado",
            headers={"Location": "/dashboard"},
        )
    return user


def _send_chamado_email(chamado: models.Chamado) -> bool:
    subject = f"[Chamado #{chamado.id}] {chamado.titulo}"
    body = (
        "Novo chamado aberto no Gerenciado Contabil.\n\n"
        f"Titulo: {chamado.titulo}\n"
        f"Solicitante: {chamado.solicitante}\n"
        "Descricao:\n"
        f"{chamado.descricao}\n\n"
        "Acesse o sistema para visualizar e atualizar o status.\n"
    )

    try:
        return email_service.send_email(CHAMADO_RECIPIENTS, subject, body)
    except Exception:
        logger.exception("Falha ao enviar notificacao do chamado %s", chamado.id)
        return False


def _date_or_none(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data invalida") from exc


def _serialize_subtask(subtask: models.Subtask) -> dict[str, Any]:
    return {
        "id": subtask.id,
        "task_id": subtask.task_id,
        "titulo": subtask.titulo,
        "responsavel": subtask.responsavel or "",
        "concluida": subtask.concluida,
        "liberacao": subtask.liberacao or "",
        "vencimento": subtask.vencimento.isoformat() if subtask.vencimento else "",
        "data_conclusao": subtask.data_conclusao or "",
    }


def _serialize_task(task: models.Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "titulo": task.titulo,
        "categoria": task.categoria,
        "tipo": task.tipo,
        "prioridade": task.prioridade,
        "status": task.status,
        "competencia": task.competencia,
        "liberacao": task.liberacao.isoformat() if task.liberacao else "",
        "vencimento": task.vencimento.isoformat() if task.vencimento else "",
        "data_conclusao": task.data_conclusao.isoformat() if task.data_conclusao else "",
        "cliente": task.cliente or "",
        "responsavel": task.responsavel or "",
        "solicitante": task.solicitante or "",
        "obs": task.obs or "",
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "subtarefas": [_serialize_subtask(subtask) for subtask in task.subtarefas],
    }


async def _request_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        return payload or {}
    form = await request.form()
    return dict(form)


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user_optional(request, db)
    if not user:
        return _redirect("/login")
    return _redirect("/dashboard")


@app.get("/health")
def healthcheck(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Usado pelo monitoramento da VM. Agora tambem confirma que o banco
    responde - antes retornava ok mesmo com o SQLite inacessivel."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Healthcheck: banco indisponivel")
        return {"ok": False, "database": False}
    return {"ok": True, "database": True}


@app.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    db: Session = Depends(get_db),
):
    if auth.get_current_user_optional(request, db):
        return _redirect("/dashboard")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "users": crud.get_users(db),
            "error": False,
            "flashes": _pop_flashes(request),
        },
    )


@app.post("/login", response_class=HTMLResponse)
def do_login(
    request: Request,
    user_id: str = Form(...),
    senha: str = Form(...),
    db: Session = Depends(get_db),
):
    user = crud.authenticate_user(db, user_id=user_id, senha=senha)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "users": crud.get_users(db),
                "error": True,
                "flashes": _pop_flashes(request),
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    auth.login_user(request, user)
    if user.must_change_password:
        return _redirect_with_flash(
            request,
            auth.CHANGE_PASSWORD_PATH,
            "Primeiro acesso: defina uma nova senha para continuar.",
        )
    return _redirect("/dashboard")


@app.get("/logout")
@app.post("/logout")
def do_logout(request: Request):
    auth.logout_user(request)
    return _redirect("/login")


def _validar_nova_senha(senha: str, confirmar: str, senha_atual: str) -> str | None:
    """Retorna a mensagem de erro, ou None se a senha for aceitavel."""
    if len(senha) < SENHA_MINIMA:
        return f"A nova senha precisa ter pelo menos {SENHA_MINIMA} caracteres"
    if senha != confirmar:
        return "As senhas nao conferem"
    if senha == senha_atual:
        return "A nova senha precisa ser diferente da atual"
    return None


@app.get("/trocar-senha", response_class=HTMLResponse)
def change_password_page(
    request: Request,
    user: models.User = Depends(auth.get_current_user),
):
    """Usa get_current_user (e nao get_active_user) de proposito: esta e a
    unica tela que alguem com senha provisoria consegue abrir."""
    return templates.TemplateResponse(
        request=request,
        name="change_password.html",
        context={
            "user": user,
            "obrigatorio": bool(user.must_change_password),
            "senha_minima": SENHA_MINIMA,
            "logic": logic,
            "categories": logic.CATEGORIES,
            "flashes": _pop_flashes(request),
        },
    )


@app.post("/trocar-senha")
def change_password(
    request: Request,
    senha_atual: str = Form(...),
    senha: str = Form(...),
    confirmar_senha: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    if not crud.authenticate_user(db, user_id=user.id, senha=senha_atual):
        return _redirect_with_flash(request, "/trocar-senha", "Senha atual incorreta")

    erro = _validar_nova_senha(senha, confirmar_senha, senha_atual)
    if erro:
        return _redirect_with_flash(request, "/trocar-senha", erro)

    crud.change_user_password(db, user.id, senha, must_change_password=False)
    return _redirect_with_flash(request, "/dashboard", "Senha alterada com sucesso")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    cat_tab: str = "todas",
    status_filter: str = "todos",
    categoria: str = "todas",
    tipo: str = "todos",
    prioridade: str = "todas",
    busca: str = "",
    responsavel: str = "",
    solicitante: str = "",
    dash_month: str | None = None,
    dash_all: bool = False,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    if user.perfil != "gerente":
        cat_tab = user.categoria or "todas"
        categoria = "todas"

    competencias = logic.montar_competencias(crud.competencias_existentes(db))
    if not dash_month:
        dash_month = logic.competencia_atual()
    if dash_month not in competencias:
        competencias = sorted({*competencias, dash_month}, key=logic.comp_sort_key)

    responsavel = responsavel.strip()
    solicitante = solicitante.strip()

    tasks = crud.get_filtered_tasks(
        db=db,
        current_user=user,
        categoria_tab=cat_tab,
        status=status_filter,
        categoria=categoria,
        tipo=tipo,
        prioridade=prioridade,
        busca=busca,
        responsavel=responsavel,
        solicitante=solicitante,
    )

    # Os KPIs e as barras por categoria tambem respeitam responsavel/
    # solicitante: e justamente o ponto do filtro ("quero ver so a equipe X").
    # Sem nada selecionado o comportamento e identico ao de antes.
    kpi_query = crud.aplicar_filtros_pessoa(
        crud.scoped_tasks_query(db, user, cat_tab),
        responsavel=responsavel,
        solicitante=solicitante,
    )
    kpi_base = kpi_query.all()
    kpi_src = kpi_base if dash_all else [t for t in kpi_base if t.competencia == dash_month]

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "kpis": logic.build_kpis(kpi_src),
            "cat_bars": logic.build_category_bars(kpi_src, user, cat_tab),
            "grouped": logic.group_tasks(tasks),
            "total_count": len(tasks),
            "scoped_count": len(kpi_base),
            "categories": logic.CATEGORIES,
            "prioridades": logic.PRIORIDADES,
            "tipo_cfg": logic.TIPO_CFG,
            "statuses": logic.STATUSES,
            "competencias": competencias,
            "dash_month": dash_month,
            "dash_all": dash_all,
            "cat_tab": cat_tab,
            "status_filter": status_filter,
            "categoria": categoria,
            "tipo": tipo,
            "prioridade": prioridade,
            "busca": busca,
            "responsavel": responsavel,
            "solicitante": solicitante,
            "responsaveis": crud.listar_responsaveis(db, user, cat_tab),
            "solicitantes": crud.listar_solicitantes(db, user, cat_tab),
            "sem_valor": crud.SEM_VALOR,
            "all_users": crud.get_users(db) if user.perfil == "gerente" else [],
            "tasks_json": [_serialize_task(task) for task in tasks],
            "logic": logic,
            "flashes": _pop_flashes(request),
        },
    )


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(_require_admin_user),
):
    return templates.TemplateResponse(
        request=request,
        name="admin_users.html",
        context={
            "user": user,
            "users": crud.get_users(db),
            "perfis": ["gerente", "equipe"],
            "categories": logic.CATEGORIES,
            "logic": logic,
            "flashes": _pop_flashes(request),
        },
    )


@app.post("/admin/users/change-password")
def admin_change_user_password(
    request: Request,
    user_id: str = Form(...),
    senha: str = Form(...),
    confirmar_senha: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(_require_admin_user),
):
    target = crud.get_user(db, user_id)
    if not target:
        return _redirect_with_flash(request, "/admin/users", "Usuario nao encontrado")
    if not senha:
        return _redirect_with_flash(request, "/admin/users", "Informe a nova senha")
    if senha != confirmar_senha:
        return _redirect_with_flash(request, "/admin/users", "As senhas nao conferem")
    if len(senha) < SENHA_MINIMA:
        return _redirect_with_flash(
            request, "/admin/users", f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres"
        )

    # Senha definida por terceiro e sempre provisoria: o dono da conta sera
    # obrigado a trocar no proximo login. Excecao: o gerente trocando a
    # propria senha, que ja sabe qual e.
    provisoria = target.id != user.id
    crud.change_user_password(db, user_id, senha, must_change_password=provisoria)
    aviso = " O usuario devera definir uma nova senha no proximo acesso." if provisoria else ""
    return _redirect_with_flash(request, "/admin/users", f"Senha alterada com sucesso.{aviso}")


@app.post("/admin/users/create")
def admin_create_user(
    request: Request,
    username: str = Form(...),
    senha: str = Form(...),
    confirmar_senha: str = Form(...),
    perfil: str = Form(...),
    categoria: str | None = Form(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(_require_admin_user),
):
    user_id = username.strip()
    if not user_id:
        return _redirect_with_flash(request, "/admin/users", "Informe o usuario")
    if crud.get_user(db, user_id):
        return _redirect_with_flash(request, "/admin/users", "Usuario ja existe")
    if not senha:
        return _redirect_with_flash(request, "/admin/users", "Informe a senha")
    if senha != confirmar_senha:
        return _redirect_with_flash(request, "/admin/users", "As senhas nao conferem")
    if len(senha) < SENHA_MINIMA:
        return _redirect_with_flash(
            request, "/admin/users", f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres"
        )
    if perfil not in {"gerente", "equipe"}:
        return _redirect_with_flash(request, "/admin/users", "Perfil invalido")
    if perfil == "equipe" and categoria not in logic.CATEGORIES:
        return _redirect_with_flash(request, "/admin/users", "Categoria obrigatoria para usuario de equipe")

    cor = logic.AVATAR_COLORS[len(crud.get_users(db)) % len(logic.AVATAR_COLORS)]
    data = schemas.UserCreate(
        id=user_id,
        nome=user_id,
        senha=senha,
        perfil=perfil,
        categoria=None if perfil == "gerente" else categoria,
    )
    # must_change_password=True: senha informada aqui e provisoria.
    crud.create_user(db, data, cor, must_change_password=True)
    return _redirect_with_flash(
        request,
        "/admin/users",
        "Usuario criado. Ele devera definir a propria senha no primeiro acesso.",
    )


@app.post("/admin/users/delete")
def admin_delete_user(
    request: Request,
    user_id: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(_require_admin_user),
):
    if user_id == user.id:
        return _redirect_with_flash(request, "/admin/users", "Nao e possivel remover o usuario logado")
    alvo = crud.get_user(db, user_id)
    if alvo and alvo.perfil == "gerente" and crud.count_gerentes(db) <= 1:
        return _redirect_with_flash(
            request, "/admin/users", "Nao e possivel remover o unico gerente do sistema"
        )
    if not crud.delete_user(db, user_id):
        return _redirect_with_flash(request, "/admin/users", "Usuario nao encontrado")
    return _redirect_with_flash(request, "/admin/users", "Usuario removido com sucesso")


@app.get("/chamados", response_class=HTMLResponse)
def chamados_page(
    request: Request,
    status_chamado: str = "",
    db: Session = Depends(get_db),
    user: models.User = Depends(_require_admin_user),
):
    selected_status = status_chamado if status_chamado in CHAMADO_STATUSES else ""
    return templates.TemplateResponse(
        request=request,
        name="chamados.html",
        context={
            "user": user,
            "chamados": crud.get_chamados(db, selected_status or None),
            "statuses": CHAMADO_STATUSES,
            "selected_status": selected_status,
            "logic": logic,
            "flashes": _pop_flashes(request),
        },
    )


@app.get("/chamados/novo", response_class=HTMLResponse)
def novo_chamado_page(
    request: Request,
    user: models.User = Depends(_require_admin_user),
):
    return templates.TemplateResponse(
        request=request,
        name="chamado_form.html",
        context={
            "user": user,
            "logic": logic,
            "flashes": _pop_flashes(request),
        },
    )


@app.post("/chamados/novo")
def novo_chamado(
    request: Request,
    titulo: str = Form(...),
    descricao: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(_require_admin_user),
):
    if not titulo.strip() or not descricao.strip():
        return _redirect_with_flash(request, "/chamados", "Informe titulo e descricao do chamado")

    chamado = crud.create_chamado(
        db,
        titulo=titulo,
        descricao=descricao,
        solicitante=user.id,
    )
    if _send_chamado_email(chamado):
        return _redirect_with_flash(request, "/chamados", "Chamado aberto com sucesso")
    return _redirect_with_flash(
        request,
        "/chamados",
        "Chamado aberto, mas o e-mail de notificacao NAO foi enviado. "
        "Verifique as configuracoes SMTP do servidor.",
    )


@app.get("/chamados/{chamado_id}", response_class=HTMLResponse)
def chamado_detail_page(
    chamado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(_require_admin_user),
):
    chamado = crud.get_chamado(db, chamado_id)
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado nao encontrado")
    return templates.TemplateResponse(
        request=request,
        name="chamado_detail.html",
        context={
            "user": user,
            "chamado": chamado,
            "statuses": CHAMADO_STATUSES,
            "logic": logic,
            "flashes": _pop_flashes(request),
        },
    )


@app.post("/chamados/{chamado_id}/status")
def update_chamado_status(
    chamado_id: int,
    request: Request,
    status_chamado: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(_require_admin_user),
):
    if status_chamado not in CHAMADO_STATUSES:
        return _redirect_with_flash(request, f"/chamados/{chamado_id}", "Status invalido")
    chamado = crud.update_chamado_status(db, chamado_id, status_chamado)
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado nao encontrado")
    return _redirect_with_flash(request, f"/chamados/{chamado_id}", "Status atualizado")


@app.post("/chamados/{chamado_id}/delete")
def delete_chamado(
    chamado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(_require_admin_user),
):
    if not crud.delete_chamado(db, chamado_id):
        raise HTTPException(status_code=404, detail="Chamado nao encontrado")
    return _redirect_with_flash(request, "/chamados", f"Chamado #{chamado_id} excluido")


def _require_task_access(db: Session, task_id: int, user: models.User) -> models.Task:
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    if user.perfil != "gerente" and task.categoria != user.categoria:
        raise HTTPException(status_code=403, detail="Acao restrita a sua categoria")
    return task


@app.post("/api/tasks")
def api_create_task(
    data: schemas.TaskCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    if user.perfil != "gerente":
        data = data.model_copy(update={"categoria": user.categoria})
    # Solicitante = quem esta criando. Gravado so aqui; update_task nao mexe.
    task = crud.create_task(db, data, solicitante=user.nome)
    return {"ok": True, "id": task.id}


@app.put("/api/tasks/{task_id}")
def api_update_task(
    task_id: int,
    data: schemas.TaskUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    _require_task_access(db, task_id, user)
    if user.perfil != "gerente":
        data = data.model_copy(update={"categoria": user.categoria})
    task = crud.update_task(db, task_id, data)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return {"ok": True, "id": task.id}


@app.delete("/api/tasks/{task_id}")
def api_delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_gerente),
):
    if not crud.delete_task(db, task_id):
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return {"ok": True}


@app.post("/api/tasks/{task_id}/status")
async def api_change_status(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    _require_task_access(db, task_id, user)
    payload = await _request_payload(request)
    status_value = payload.get("status")
    if status_value not in logic.STATUSES:
        raise HTTPException(status_code=400, detail="Status invalido")
    task = crud.change_status(db, task_id, status_value)
    return {"ok": True, "id": task.id}


@app.post("/api/tasks/{task_id}/conclusao")
async def api_set_conclusao(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    _require_task_access(db, task_id, user)
    payload = await _request_payload(request)
    value = _date_or_none(payload.get("value"))
    task = crud.set_task_conclusao_data(db, task_id, value)
    return {"ok": True, "id": task.id}


@app.post("/api/tasks/{task_id}/replicate")
def api_replicate(
    task_id: int,
    data: schemas.ReplicateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    _require_task_access(db, task_id, user)
    copy = crud.replicate_task(db, task_id, data.nova_competencia)
    if not copy:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return {"ok": True, "id": copy.id}


@app.post("/api/tasks/{task_id}/subtasks")
def api_add_subtask(
    task_id: int,
    data: schemas.SubtaskCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    _require_task_access(db, task_id, user)
    task = crud.add_subtask(db, task_id, data)
    return {"ok": True, "id": task.id}


@app.put("/api/tasks/{task_id}/subtasks/{subtask_id}")
def api_update_subtask(
    task_id: int,
    subtask_id: int,
    data: schemas.SubtaskCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    _require_task_access(db, task_id, user)
    task = crud.update_subtask(db, task_id, subtask_id, data)
    if not task:
        raise HTTPException(status_code=404, detail="Subtarefa nao encontrada")
    return {"ok": True, "id": task.id}


@app.post("/api/tasks/{task_id}/subtasks/{subtask_id}/toggle")
def api_toggle_subtask(
    task_id: int,
    subtask_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    _require_task_access(db, task_id, user)
    task = crud.toggle_subtask(db, task_id, subtask_id)
    if not task:
        raise HTTPException(status_code=404, detail="Subtarefa nao encontrada")
    return {"ok": True, "id": task.id}


@app.delete("/api/tasks/{task_id}/subtasks/{subtask_id}")
def api_delete_subtask(
    task_id: int,
    subtask_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_active_user),
):
    _require_task_access(db, task_id, user)
    task = crud.delete_subtask(db, task_id, subtask_id)
    if not task:
        raise HTTPException(status_code=404, detail="Subtarefa nao encontrada")
    return {"ok": True, "id": task.id}


@app.post("/api/users")
def api_create_user(
    data: schemas.UserCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_gerente),
):
    if crud.get_user(db, data.id):
        raise HTTPException(status_code=400, detail="Usuario ja existe")
    if data.perfil == "equipe" and not data.categoria:
        raise HTTPException(status_code=400, detail="Categoria obrigatoria para usuario de equipe")
    cor = logic.AVATAR_COLORS[len(crud.get_users(db)) % len(logic.AVATAR_COLORS)]
    crud.create_user(db, data, cor)
    return {"ok": True}


@app.delete("/api/users/{user_id}")
def api_delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_gerente),
):
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Nao e possivel remover o usuario logado")
    alvo = crud.get_user(db, user_id)
    if alvo and alvo.perfil == "gerente" and crud.count_gerentes(db) <= 1:
        raise HTTPException(status_code=400, detail="Nao e possivel remover o unico gerente do sistema")
    if not crud.delete_user(db, user_id):
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    return {"ok": True}
