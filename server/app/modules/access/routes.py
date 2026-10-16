import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import tasks
from app.core.auth import Admin, CurrentActor
from app.core.config import config
from app.core.db import DB
from app.modules.access import api

auth = APIRouter(prefix="/api/auth", tags=["auth"])
users = APIRouter(prefix="/api/users", tags=["users"])


def _me(session: Session, account_id: uuid.UUID) -> dict[str, Any]:
    account = api.get(session, account_id)
    out = api.view(session, account)
    out["role_title"] = api.ROLE_TITLES[account.role]
    return out


class LoginIn(BaseModel):
    login: str = Field(max_length=100)
    password: str = Field(max_length=200)


@auth.post("/login")
def login(body: LoginIn, request: Request, session: DB) -> Response:
    result = api.login(session, body.login, body.password,
                       ip=request.client.host if request.client else None,
                       user_agent=request.headers.get("user-agent"))
    if result.error is not None:
        # не исключение: попытка должна остаться в журнале и счётчике (транзакция фиксируется)
        return JSONResponse(result.error.body(), status_code=result.error.status)
    assert result.account is not None and result.token is not None
    response = JSONResponse(jsonable_encoder(_me(session, result.account.id)))
    response.set_cookie(api.COOKIE, result.token, max_age=api.COOKIE_MAX_AGE, httponly=True,
                        secure=config().secure_cookies, samesite="lax", path="/")
    return response


@auth.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: DB) -> None:
    api.logout(session, request.cookies.get(api.COOKIE))
    response.delete_cookie(api.COOKIE, path="/")


@auth.get("/me")
def me(actor: CurrentActor, session: DB) -> dict[str, Any]:
    return _me(session, actor.user_id)


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


@auth.post("/password")
def change_password(body: PasswordIn, actor: CurrentActor, request: Request, session: DB
                    ) -> dict[str, Any]:
    account = api.change_password(session, actor, body.current, body.new,
                                  request.cookies.get(api.COOKIE))
    return _me(session, account.id)


# ---------------------------------------------------------------- учётные записи (С20)

@users.get("")
def list_users(_: Admin, session: DB) -> dict[str, Any]:
    return {"items": [api.view(session, a) for a in api.accounts(session)]}


class UserIn(BaseModel):
    login: str = Field(max_length=100)
    full_name: str = Field(max_length=200)
    role: str
    building_ids: list[uuid.UUID] = []
    # временный пароль; не задан — система придумает сама
    password: str | None = Field(default=None, max_length=200)


@users.post("", status_code=201)
def create_user(body: UserIn, actor: Admin, session: DB) -> dict[str, Any]:
    account, temporary = api.create(session, actor, login_name=body.login,
                                    full_name=body.full_name, role=body.role,
                                    building_ids=body.building_ids,
                                    password=body.password or None)
    return {"user": api.view(session, account), "temporary_password": temporary}


@users.get("/{account_id}")
def get_user(account_id: uuid.UUID, _: Admin, session: DB) -> dict[str, Any]:
    return api.view(session, api.get(session, account_id))


class UserPatch(BaseModel):
    version: int
    full_name: str | None = Field(default=None, max_length=200)
    role: str | None = None
    building_ids: list[uuid.UUID] | None = None


@users.patch("/{account_id}")
def update_user(account_id: uuid.UUID, body: UserPatch, actor: Admin, session: DB
                ) -> dict[str, Any]:
    account = api.update(session, actor, account_id, version=body.version,
                         full_name=body.full_name, role=body.role,
                         building_ids=body.building_ids)
    return api.view(session, account)


class ResetIn(BaseModel):
    password: str | None = Field(default=None, max_length=200)


@users.post("/{account_id}/reset-password")
def reset_password(account_id: uuid.UUID, body: ResetIn, actor: Admin, session: DB
                   ) -> dict[str, Any]:
    account, temporary = api.reset_password(session, actor, account_id, body.password or None)
    return {"user": api.view(session, account), "temporary_password": temporary}


@users.post("/{account_id}/block")
def block(account_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return api.view(session, api.set_blocked(session, actor, account_id, True))


@users.post("/{account_id}/unblock")
def unblock(account_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return api.view(session, api.set_blocked(session, actor, account_id, False))


@tasks.task("access.purge_sessions", "Удаление истёкших сеансов", every=timedelta(hours=6))
def purge_sessions(session: Session, _payload: dict[str, Any], _progress: tasks.Progress
                   ) -> dict[str, Any]:
    return {"removed": api.purge_sessions(session)}

