"""The gateway's own requests (contracts/openapi/gateway.v1.json)."""
from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from twin_chassis import Problem

from .oidc import SignInFailed
from .proxy import check_origin, forward
from .sessions import COOKIE, Signed, signed

LOGIN_COOKIE = "twin_login"
router = APIRouter()


# ------------------------------------------------------------------ sign-in ---
def _local(path: str | None) -> str:
    """Only a path on this site is accepted as the place to return to."""
    return path if path and path.startswith("/") and not path.startswith("//") and "\\" not in path else "/"


@router.get("/auth/login", tags=["auth"], summary="Начать вход: переадресация в Keycloak", status_code=302,
            response_class=RedirectResponse)
async def login(request: Request, next: str | None = None):
    config = request.app.state.config
    url, state = request.app.state.oidc.begin(_local(next))
    response = RedirectResponse(url, 302)
    response.set_cookie(LOGIN_COOKIE, state, max_age=600, httponly=True, secure=config.secure, samesite="lax",
                        path="/auth")
    return response


@router.get("/auth/callback", tags=["auth"], summary="Завершить вход: Keycloak возвращает сюда", status_code=302,
            response_class=RedirectResponse)
async def callback(request: Request, code: str | None = None, state: str | None = None):
    app = request.app
    pending = app.state.oidc.unpack(request.cookies.get(LOGIN_COOKIE))
    failed = RedirectResponse("/?signin=failed", 302)
    failed.delete_cookie(LOGIN_COOKIE, path="/auth")
    if pending is None or not code or state != pending["state"]:
        return failed
    try:
        tokens = await app.state.oidc.exchange(code, pending["verifier"])
        cookie = await app.state.sessions.create(tokens, request.headers.get("user-agent", ""))
    except SignInFailed:
        return failed
    except Problem as ex:
        if ex.status == 503:
            raise
        return failed
    response = RedirectResponse(_local(pending.get("next")), 302)
    response.delete_cookie(LOGIN_COOKIE, path="/auth")
    app.state.sessions.set_cookie(response, cookie)
    return response


class LoggedOut(BaseModel):
    url: str = Field(description="Куда перейти, чтобы завершить и сеанс Keycloak")


@router.post("/auth/logout", tags=["auth"], response_model=LoggedOut, summary="Выйти")
async def logout(request: Request, me: Signed = Depends(signed)):
    check_origin(request, me)
    id_token = await request.app.state.sessions.end(request.cookies.get(COOKIE))
    response = JSONResponse({"url": request.app.state.oidc.logout_url(id_token)})
    request.app.state.sessions.clear_cookie(response)
    return response


# ----------------------------------------------------------------------- me ---
class User(BaseModel):
    sub: str
    login: str
    name: str
    email: str | None
    roles: list[str] = Field(description="Роли приложения из Keycloak")
    is_admin: bool = Field(description="Администратор системы")


class Me(BaseModel):
    user: User
    person: dict | None = Field(description="Запись справочника людей; null — учётной записи нет в справочнике")
    reason: str | None = Field(description="Почему нет записи: unknown, ambiguous, left")
    scopes: dict | None = Field(description="Области доступа: назначения и здания, план которых виден")
    partial: list[str] = Field(description="Сервисы, не ответившие: соответствующих частей в ответе нет")


@router.get("/api/me", tags=["me"], response_model=Me, summary="Кто вошёл")
async def me(request: Request, who: Signed = Depends(signed)):
    i = who.identity
    person, scopes = await asyncio.gather(_ask(request, who, "people", "/me"),
                                          _ask(request, who, "access", "/me/scopes"))
    # the first sign-in: the account has just been linked to its person, and the access service
    # learns of it from an event — give it a moment rather than answer "no rights"
    known = (person or {}).get("person")
    for _ in range(10):
        if not known or scopes is None or scopes.get("admin") or scopes.get("person_id") == known["id"]:
            break
        await asyncio.sleep(0.2)
        scopes = await _ask(request, who, "access", "/me/scopes")
    return {"user": {"sub": i.sub, "login": i.login, "name": i.name, "email": i.email, "roles": list(i.roles),
                     "is_admin": i.is_admin},
            "person": (person or {}).get("person"), "reason": (person or {}).get("reason"), "scopes": scopes,
            "partial": [name for name, got in (("people", person), ("access", scopes)) if got is None]}


async def _ask(request: Request, who: Signed, service: str, path: str) -> dict | None:
    """A service's answer to the user's own question, or None when it does not answer."""
    base = request.app.state.config.services.get(service)
    if base is None:
        return None
    try:
        r = await request.app.state.http.get(f"{base}/api/{service}/v1{path}", timeout=5,
                                             headers={"Authorization": f"Bearer {who.token}"})
        return r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


# ------------------------------------------------------------------- stream ---
@router.get("/api/stream", tags=["stream"], summary="Поток событий (Server-Sent Events)",
            response_class=StreamingResponse, responses={200: {"content": {"text/event-stream": {}}}})
async def stream(request: Request, who: Signed = Depends(signed)):
    async def buildings() -> list[str]:
        scopes = await _ask(request, who, "access", "/me/scopes")
        if scopes is None:
            raise RuntimeError("access is away")
        return scopes.get("buildings") or []

    return StreamingResponse(request.app.state.hub.events(who.identity, buildings), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------- status ---
class ServiceStatus(BaseModel):
    name: str
    ok: bool = Field(description="Сервис отвечает")
    db: bool | None = Field(description="Его база доступна")
    nats: bool | None = Field(description="Он подключён к шине событий")
    ms: float | None = Field(description="Время ответа")


class SystemStatus(BaseModel):
    services: list[ServiceStatus]
    viewers: int = Field(description="Сколько браузеров слушают поток событий")


@router.get("/api/system/status", tags=["system"], response_model=SystemStatus,
            summary="Состояние сервисов (администратор системы)")
async def status(request: Request, who: Signed = Depends(signed)):
    if not who.identity.is_admin:
        raise Problem(403, "forbidden", "Нужна роль администратора системы")
    app = request.app

    async def probe(name: str, url: str) -> dict:
        started = time.perf_counter()
        try:
            r = await app.state.http.get(f"{url}/healthz", timeout=2)
            body = r.json() if r.status_code == 200 else {}
            return {"name": name, "ok": r.status_code == 200, "db": body.get("db"), "nats": body.get("nats"),
                    "ms": round((time.perf_counter() - started) * 1000, 1)}
        except (httpx.HTTPError, ValueError):
            return {"name": name, "ok": False, "db": None, "nats": None, "ms": None}

    own = {"name": "gateway", "ok": True, "db": await app.state.db.ok(), "nats": app.state.bus.connected, "ms": 0.0}
    others = await asyncio.gather(*(probe(n, u) for n, u in sorted(app.state.config.services.items())))
    return {"services": [own, *others], "viewers": len(app.state.hub)}


# -------------------------------------------------------------------- proxy ---
@router.api_route("/api/{service}/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                  include_in_schema=False)
async def proxy(service: str, path: str, request: Request, who: Signed = Depends(signed)):
    return await forward(request, service, path, who)
