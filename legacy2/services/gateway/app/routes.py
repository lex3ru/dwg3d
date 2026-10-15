"""The gateway's own requests (contracts/openapi/gateway.v1.json)."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from twin_chassis import Problem

from .oidc import SignInFailed
from .proxy import check_origin, forward
from .sessions import COOKIE, GUEST_COOKIE, LinkAway, Signed, not_guest, signed

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


@router.post("/auth/logout", tags=["auth"], response_model=LoggedOut,
             summary="Выйти; гость по ссылке выходит только из просмотра по ней")
async def logout(request: Request):
    sessions = request.app.state.sessions
    guest = request.cookies.get(GUEST_COOKIE)
    if guest is not None:
        # the look by the link ends, ended already or not; the user's own session in this browser stays
        check_origin(request)
        await sessions.end_guest(guest)
        response = JSONResponse({"url": "/"})
        sessions.clear_guest_cookie(response)
        return response
    me = await signed(request)
    check_origin(request, me.by_cookie)
    id_token = await sessions.end(request.cookies.get(COOKIE))
    response = JSONResponse({"url": request.app.state.oidc.logout_url(id_token)})
    sessions.clear_cookie(response)
    return response


# ------------------------------------------------------------ guest by a link ---
LINK = re.compile(r"^[A-Za-z0-9_-]{10,200}$")


@router.get("/s/{token}", tags=["auth"], status_code=302, response_class=RedirectResponse,
            summary="Ссылка для просмотра без учётной записи: гостевой сеанс и переход к просмотру "
                    "(#/g; недействительна — #/g?invalid=1; сервис доступа недоступен — #/g?unavailable=1)")
async def share(token: str, request: Request):
    sessions = request.app.state.sessions
    if not LINK.match(token):
        return RedirectResponse("/#/g?invalid=1", 302)
    try:
        opened = await sessions.create_guest(token, request.client.host if request.client else None,
                                             request.headers.get("user-agent", ""))
    except LinkAway:
        return RedirectResponse("/#/g?unavailable=1", 302)
    except Problem as ex:                   # the keys of guest tokens could not be fetched
        if ex.status != 503:
            raise
        return RedirectResponse("/#/g?unavailable=1", 302)
    if opened is None:
        return RedirectResponse("/#/g?invalid=1", 302)
    await sessions.end_guest(request.cookies.get(GUEST_COOKIE))        # a look opened before is replaced
    response = RedirectResponse("/#/g", 302)
    sessions.set_guest_cookie(response, *opened)
    return response


# ----------------------------------------------------------------------- QR ---
QR_CODE = re.compile(r"^[A-Za-z0-9]{4,32}$")


@router.get("/q/{code}", tags=["qr"], status_code=302, response_class=RedirectResponse,
            summary="QR-метка: без входа — на вход, затем к карточке объекта (если есть право на него)")
async def qr(code: str, request: Request):
    if not QR_CODE.match(code):
        raise Problem(404, "not_found", "Нет такой метки")
    if GUEST_COOKIE in request.cookies:
        await not_guest(await signed(request))          # 401 guest_ended or 403 guest
    me = await request.app.state.sessions.resolve(request.cookies.get(COOKIE))
    if me is None:
        return RedirectResponse(f"/auth/login?next=/q/{code}", 302)
    return RedirectResponse(f"/#/q/{code}", 302)


# ----------------------------------------------------------------------- me ---
class User(BaseModel):
    sub: str
    login: str
    name: str
    email: str | None
    roles: list[str] = Field(description="Роли приложения из Keycloak")
    is_admin: bool = Field(description="Администратор системы")


class Me(BaseModel):
    kind: Literal["user"] = "user"
    user: User
    person: dict | None = Field(description="Запись справочника людей; null — учётной записи нет в справочнике")
    reason: str | None = Field(description="Почему нет записи: unknown, ambiguous, left")
    scopes: dict | None = Field(description="Области доступа: назначения и здания, план которых виден")
    partial: list[str] = Field(description="Сервисы, не ответившие: соответствующих частей в ответе нет")


class Area(BaseModel):
    kind: str = Field(description="building, floor или room")
    id: str


class GuestLook(BaseModel):
    building_id: str
    building_name: str | None = Field(description="null — сервис зданий не ответил")
    scope: Area = Field(description="Что открывает ссылка")
    floor_id: str | None = Field(description="Этаж, план которого виден (для этажа и помещения)")
    expires_at: str | None = Field(description="До какого времени действует ссылка")


class GuestMe(BaseModel):
    kind: Literal["guest"]
    name: str
    guest: GuestLook


@router.get("/api/me", tags=["me"], response_model=Me | GuestMe, summary="Кто вошёл (или гость по ссылке)")
async def me(request: Request, who: Signed = Depends(signed)):
    i = who.identity
    if i.kind == "guest":
        kind, scope_id, building_id, floor_id = i.guest
        building = await _ask(request, who, "buildings", f"/buildings/{building_id}")
        until = who.until.isoformat().replace("+00:00", "Z") if who.until else None
        return {"kind": "guest", "name": i.name,
                "guest": {"building_id": building_id, "building_name": (building or {}).get("name"),
                          "scope": {"kind": kind, "id": scope_id}, "floor_id": floor_id or None, "expires_at": until}}
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
    return {"kind": "user",
            "user": {"sub": i.sub, "login": i.login, "name": i.name, "email": i.email, "roles": list(i.roles),
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
async def stream(request: Request, who: Signed = Depends(not_guest)):
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
async def status(request: Request, who: Signed = Depends(not_guest)):
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
