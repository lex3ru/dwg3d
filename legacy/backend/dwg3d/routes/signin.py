"""Sign-in through Keycloak (session cookie), share links, the user directory."""
from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import access, auth
from .common import base_url, secure, whoami

router = APIRouter()


@router.get("/api/auth/login")
def auth_login(request: Request, next: str = "/"):
    """Off to the Keycloak sign-in page; it sends the browser back to /api/auth/callback."""
    if not auth.enabled():
        return RedirectResponse(auth.safe_next(next), status_code=303)
    url, state = auth.login_redirect(base_url(request), next)
    r = RedirectResponse(url, status_code=303)
    r.set_cookie(auth.STATE_COOKIE, state, max_age=auth.STATE_TTL, httponly=True, samesite="lax",
                 secure=secure(request), path="/api/auth")
    return r


@router.get("/api/auth/callback")
def auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                  error_description: str | None = None):
    if error or not code or not state:
        msg = error_description or error or "нет кода авторизации"
        return HTMLResponse(_signin_failed(msg), status_code=400)
    try:
        token, _, nxt = auth.complete_login(base_url(request), code, state, request.cookies.get(auth.STATE_COOKIE),
                                            request.headers.get("user-agent", ""))
    except auth.OIDCError as ex:
        return HTMLResponse(_signin_failed(str(ex)), status_code=400)
    auth.purge_sessions()
    r = RedirectResponse(nxt, status_code=303)
    r.delete_cookie(auth.STATE_COOKIE, path="/api/auth")
    r.delete_cookie(access.SHARE_COOKIE, path="/")
    r.set_cookie(auth.COOKIE, token, max_age=int(auth.session_days() * 86400), httponly=True,
                 samesite="lax", secure=secure(request), path="/")
    return r


def _signin_failed(msg: str) -> str:
    return ("<!doctype html><meta charset=utf-8><title>Вход не выполнен</title>"
            "<body style='font-family:sans-serif;max-width:40em;margin:4em auto'>"
            f"<h1>Вход не выполнен</h1><p>{html.escape(msg)}</p><p><a href='/'>Попробовать ещё раз</a></p>")


@router.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    """End the session; `logout_url` signs out of Keycloak too (the browser goes there)."""
    url = auth.logout(request.cookies.get(auth.COOKIE), base_url(request))
    response.delete_cookie(auth.COOKIE, path="/")
    response.delete_cookie(access.SHARE_COOKIE, path="/")
    return {"ok": True, "logout_url": url}


@router.get("/api/auth/me")
def auth_me(request: Request):
    me = whoami(request)
    if me is None:
        return JSONResponse({"detail": "Войдите, чтобы продолжить", "login": True}, status_code=401)
    return me.json()


@router.post("/api/share/{token}")
def open_share(token: str, request: Request, response: Response):
    """Open a share link: the token goes into a cookie; the project to show."""
    me = access.resolve_share(token, touch=True)
    if me is None:
        raise HTTPException(404, "Ссылка недействительна: её отозвали, срок истёк или проект удалён")
    response.set_cookie(access.SHARE_COOKIE, token, max_age=30 * 86400, httponly=True, samesite="lax",
                        secure=secure(request), path="/")
    return me.json()


@router.get("/api/users")
def search_users(q: str = "", limit: int = 20):
    """Users who have signed in at least once (to add them to a project)."""
    return auth.list_users(q[:100], limit)
