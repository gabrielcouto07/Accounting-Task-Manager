from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db


SESSION_KEY = "user_id"


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


def require_gerente(user: models.User = Depends(get_current_user)) -> models.User:
    if user.perfil != "gerente":
        raise HTTPException(status_code=403, detail="Acao restrita ao gerente")
    return user
