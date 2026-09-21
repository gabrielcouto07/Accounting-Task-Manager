from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db


SESSION_KEY = "user_id"
CHANGE_PASSWORD_PATH = "/trocar-senha"


def _auth_exception(request: Request, detail: str) -> HTTPException:
    if request.url.path.startswith("/api/"):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail=detail,
        headers={"Location": "/login"},
    )


def login_user(request: Request, user: models.User) -> None:
    request.session[SESSION_KEY] = user.id


def logout_user(request: Request) -> None:
    request.session.pop(SESSION_KEY, None)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> models.User:
    user_id = request.session.get(SESSION_KEY)
    if not user_id:
        raise _auth_exception(request, "Nao autenticado")

    user = crud.get_user(db, user_id)
    if not user:
        logout_user(request)
        raise _auth_exception(request, "Usuario invalido")
    return user


def get_current_user_optional(
    request: Request,
    db: Session,
) -> models.User | None:
    user_id = request.session.get(SESSION_KEY)
    if not user_id:
        return None
    return crud.get_user(db, user_id)


def _password_change_exception(request: Request) -> HTTPException:
    """Bloqueia o acesso enquanto a senha provisoria nao for trocada."""
    detail = "Troque a senha antes de continuar"
    if request.url.path.startswith("/api/"):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail=detail,
        headers={"Location": CHANGE_PASSWORD_PATH},
    )


def get_active_user(
    request: Request,
    db: Session = Depends(get_db),
) -> models.User:
    """Usuario logado E com a senha em dia.

    Toda tela/endpoint normal usa esta dependencia. Apenas /trocar-senha e
    /logout usam `get_current_user`, senao o usuario ficaria preso em um
    redirecionamento infinito.
    """
    user = get_current_user(request, db)
    if user.must_change_password:
        raise _password_change_exception(request)
    return user


def require_gerente(user: models.User = Depends(get_active_user)) -> models.User:
    if user.perfil != "gerente":
        raise HTTPException(status_code=403, detail="Acao restrita ao gerente")
    return user
