"""Sign-in through Keycloak (OpenID Connect), sessions, the current user.

The API is the OIDC client (a "backend for frontend"): the browser is sent
to Keycloak by GET /api/auth/login and comes back to /api/auth/callback with
a code, which the API exchanges for tokens (authorization code flow with
PKCE). The tokens stay on the server, in the session row; the browser keeps
only a random session token in an HttpOnly cookie (the row keeps its
SHA-256). Every few minutes a request refreshes the Keycloak tokens, so a
user signed out, disabled or with other roles in Keycloak is noticed.

Roles come from the client roles of the access token,
resource_access.<client_id>.roles, named dwg3d.<role>:
  dwg3d.admin          every project, the catalog
  dwg3d.catalog_admin  the catalog
  dwg3d.user           an ordinary user (a user with no dwg3d.* role is one too)
  dwg3d.<role>         any other role: kept with the user (Me.roles, has()) for checks
                       that need it
Realm roles are not read. What a user may do in a project is in
project_members (see access.py). Users and their roles are managed in
Keycloak (its admin console is at /auth/admin/).

A share link (access.py) signs in a guest: read-only, one project.

  DWG3D_AUTH                 oidc (default) | off — off: no sign-in, everyone is admin
                             (development, or a server reachable from a trusted network only)
  DWG3D_OIDC_ISSUER          issuer as browsers see it, e.g. https://plans.example.com/auth/realms/dwg3d
  DWG3D_OIDC_INTERNAL        the same as the API reaches it (default: the issuer),
                             e.g. http://keycloak:8080/auth/realms/dwg3d
  DWG3D_OIDC_CLIENT_ID       (dwg3d), DWG3D_OIDC_CLIENT_SECRET
  DWG3D_PUBLIC_URL           base URL of the site for the redirect back (default: from the request)
  DWG3D_SECRET               key signing the sign-in state cookie (set it when several API processes run)
  DWG3D_SESSION_DAYS         session lifetime since the last request (14)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from . import db
from .models import AuthSession, ProjectMember, User

log = logging.getLogger("dwg3d.auth")
GLOBAL_ROLES = ("user", "catalog_admin", "admin")
ROLE_PREFIX = "dwg3d."
ROLE_NAMES = {"user": "пользователь", "catalog_admin": "администратор каталога", "admin": "администратор"}
COOKIE = "dwg3d_session"
STATE_COOKIE = "dwg3d_oidc"
STATE_TTL = 600
REFRESH_EVERY = timedelta(minutes=5)
_TOUCH = timedelta(minutes=5)          # last_seen is refreshed at most this often
_SECRET = (os.environ.get("DWG3D_SECRET") or secrets.token_hex(32)).encode()


@dataclass(frozen=True)
class Me:
    id: int | None
    login: str
    name: str
    role: str                                   # user | catalog_admin | admin
    email: str | None = None
    # a guest of a share link: {"id", "project_id", "drawings", "layers"}
    share: dict | None = field(default=None, compare=False)
    # the application's roles from Keycloak, full names: ("dwg3d.user", "dwg3d.nurse", ...)
    roles: tuple[str, ...] = field(default=(), compare=False)
    # the copilot acting for this user (copilot.identity): {"id", "name", "project_id", "mode", "copilot"}
    agent: dict | None = field(default=None, compare=False)

    def can(self, role: str) -> bool:
        return GLOBAL_ROLES.index(self.role) >= GLOBAL_ROLES.index(role)

    def has(self, role: str) -> bool:
        """Whether the user has the role dwg3d.<role> in Keycloak."""
        return f"{ROLE_PREFIX}{role}" in self.roles

    def actor(self) -> str | None:
        """Who made a change, for the audit log: the login, and «Копилот» when it acted for the user."""
        if self.agent is None:
            return self.login or None
        return " · ".join(x for x in (self.login, self.agent["name"] or self.agent["id"]) if x)

    def json(self) -> dict:
        o = {"id": self.id, "login": self.login, "name": self.name, "role": self.role,
             "role_name": ROLE_NAMES[self.role], "roles": list(self.roles), "email": self.email, "auth": enabled()}
        if self.share is not None:
            o["guest"] = {"project_id": self.share["project_id"], "drawings": self.share["drawings"],
                          "layers": self.share["layers"], "name": self.share.get("name") or ""}
        if self.agent is not None:
            o["agent"] = {k: self.agent[k] for k in ("id", "name", "project_id", "mode")}
        return o


ANONYMOUS_ADMIN = Me(None, "", "", "admin")
# the user of the current request (set by the API middleware; read by the audit log and access checks)
current: ContextVar[Me | None] = ContextVar("dwg3d_user", default=None)
# the HTTP method of the current request (access checks: reading or changing)
method: ContextVar[str] = ContextVar("dwg3d_method", default="GET")


def enabled() -> bool:
    return os.environ.get("DWG3D_AUTH", "oidc").strip().lower() not in ("off", "0", "false", "no")


def session_days() -> float:
    return float(os.environ.get("DWG3D_SESSION_DAYS", "14"))


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------- OIDC setup ---
class OIDCError(RuntimeError):
    """Sign-in failed (bad state, Keycloak refused, token invalid)."""


def issuer() -> str:
    iss = os.environ.get("DWG3D_OIDC_ISSUER", "").rstrip("/")
    if not iss:
        raise OIDCError("Вход не настроен: задайте DWG3D_OIDC_ISSUER (или DWG3D_AUTH=off)")
    return iss


def _internal() -> str:
    return (os.environ.get("DWG3D_OIDC_INTERNAL") or issuer()).rstrip("/")


def client_id() -> str:
    return os.environ.get("DWG3D_OIDC_CLIENT_ID", "dwg3d")


def _endpoint(name: str, internal: bool) -> str:
    return f"{_internal() if internal else issuer()}/protocol/openid-connect/{name}"


def _post_form(url: str, data: dict) -> dict:
    """POST to Keycloak with the client credentials (replaced in tests)."""
    import httpx

    r = httpx.post(url, data=data, auth=(client_id(), os.environ.get("DWG3D_OIDC_CLIENT_SECRET", "")), timeout=15)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200:
        raise OIDCError(body.get("error_description") or body.get("error") or f"HTTP {r.status_code}")
    return body


_jwks = None


def _signing_key(token: str):
    """The Keycloak key a token is signed with (replaced in tests)."""
    global _jwks
    import jwt

    if _jwks is None:
        _jwks = jwt.PyJWKClient(_endpoint("certs", internal=True), cache_keys=True, lifespan=3600)
    return _jwks.get_signing_key_from_jwt(token).key


def _decode(token: str, audience: str | None, nonce: str | None = None) -> dict:
    import jwt

    try:
        claims = jwt.decode(token, _signing_key(token), algorithms=["RS256", "RS384", "RS512", "ES256", "PS256"],
                            issuer=issuer(), audience=audience, leeway=30,
                            options={"verify_aud": audience is not None})
    except jwt.PyJWTError as ex:
        raise OIDCError(f"недействительный токен: {ex}") from ex
    if nonce is not None and claims.get("nonce") != nonce:
        raise OIDCError("недействительный токен: nonce")
    return claims


def app_roles(access_claims: dict) -> list[str]:
    """The application's roles in an access token: resource_access.<client_id>.roles named dwg3d.<role>."""
    client = (access_claims.get("resource_access") or {}).get(client_id()) or {}
    return sorted({r for r in client.get("roles") or []
                   if isinstance(r, str) and r.startswith(ROLE_PREFIX) and len(r) > len(ROLE_PREFIX)})


def _role(roles: list[str]) -> str:
    """The global role: admin, catalog_admin or (also with no role at all) user."""
    if f"{ROLE_PREFIX}admin" in roles:
        return "admin"
    return "catalog_admin" if f"{ROLE_PREFIX}catalog_admin" in roles else "user"


# ----------------------------------------------------- signed state cookie ---
def _sign(data: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    mac = hmac.new(_SECRET, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{mac}"


def _unsign(value: str | None) -> dict | None:
    if not value or "." not in value:
        return None
    raw, mac = value.rsplit(".", 1)
    if not hmac.compare_digest(mac, hmac.new(_SECRET, raw.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("exp", 0) > time.time() else None


def safe_next(nxt: str | None) -> str:
    """Only paths of this site (no //host, no scheme)."""
    if not nxt or not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt:
        return "/"
    return nxt


def login_redirect(base_url: str, nxt: str | None) -> tuple[str, str]:
    """(URL of the Keycloak sign-in page, state cookie value)."""
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {"client_id": client_id(), "response_type": "code", "scope": "openid profile email",
              "redirect_uri": f"{base_url}/api/auth/callback", "state": state, "nonce": nonce,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    cookie = _sign({"state": state, "nonce": nonce, "verifier": verifier, "next": safe_next(nxt),
                    "exp": time.time() + STATE_TTL})
    return f"{_endpoint('auth', internal=False)}?{urllib.parse.urlencode(params)}", cookie


# --------------------------------------------------------------- sign-in ---
def _upsert_user(s, claims: dict, roles: list[str]) -> User:
    sub = claims["sub"]
    login = claims.get("preferred_username") or claims.get("email") or sub
    name = claims.get("name") or " ".join(x for x in (claims.get("given_name"), claims.get("family_name")) if x) or login
    email = claims.get("email")
    u = s.scalar(select(User).where(User.sub == sub))
    if u is None:
        # a user known before Keycloak (same login, no subject yet) is taken over
        u = s.scalar(select(User).where(func.lower(User.login) == login.lower(), User.sub.is_(None)))
    if u is None:
        taken = s.scalar(select(User.id).where(func.lower(User.login) == login.lower()))
        u = User(login=login if taken is None else f"{login}#{sub[:8]}")
        s.add(u)
    u.sub, u.name, u.email, u.role, u.roles, u.active = sub, name, email, _role(roles), roles, True
    u.last_login_at = func.now()
    s.flush()
    if email:     # invitations to projects by e-mail
        for m in s.scalars(select(ProjectMember).where(ProjectMember.user_id.is_(None),
                                                       func.lower(ProjectMember.email) == email.lower())):
            if s.scalar(select(ProjectMember.id).where(ProjectMember.project_id == m.project_id,
                                                       ProjectMember.user_id == u.id)) is None:
                m.user_id = u.id
            else:
                s.delete(m)
    return u


def complete_login(base_url: str, code: str, state: str, cookie: str | None, user_agent: str = "") -> tuple[str, Me, str]:
    """Finish the code flow: (session token, user, path to return to)."""
    st = _unsign(cookie)
    if st is None or not hmac.compare_digest(str(st.get("state")), str(state)):
        raise OIDCError("Сеанс входа устарел или подменён: начните вход заново")
    tok = _post_form(_endpoint("token", internal=True), {
        "grant_type": "authorization_code", "code": code, "redirect_uri": f"{base_url}/api/auth/callback",
        "code_verifier": st["verifier"]})
    idc = _decode(tok["id_token"], client_id(), st["nonce"])
    acc = _decode(tok["access_token"], None)
    if acc.get("sub") != idc.get("sub"):
        raise OIDCError("недействительный токен: sub")
    token = secrets.token_urlsafe(32)
    with db.session() as s:
        u = _upsert_user(s, {**acc, **idc}, app_roles(acc))
        if not u.active:
            raise OIDCError("Учётная запись отключена")
        s.add(AuthSession(token_hash=_digest(token), user_id=u.id, user_agent=user_agent[:300],
                          id_token=tok["id_token"], refresh_token=tok.get("refresh_token")))
        me = _me(u)
    return token, me, st["next"]


def _me(u: User) -> Me:
    return Me(u.id, u.login, u.name or u.login, u.role, u.email, roles=tuple(u.roles or ()))


def resolve(token: str | None) -> Me | None:
    """The user of a session token, or None (unknown, expired, ended in Keycloak)."""
    if not token:
        return None
    now = datetime.now(timezone.utc)
    with db.session() as s:
        row = s.execute(select(AuthSession, User).join(User, User.id == AuthSession.user_id)
                        .where(AuthSession.token_hash == _digest(token))).first()
        if row is None:
            return None
        sess, u = row
        if not u.active or sess.last_seen_at < now - timedelta(days=session_days()):
            s.delete(sess)
            return None
        if sess.refresh_token and sess.refreshed_at < now - REFRESH_EVERY:
            try:
                tok = _post_form(_endpoint("token", internal=True),
                                 {"grant_type": "refresh_token", "refresh_token": sess.refresh_token})
                acc = _decode(tok["access_token"], None)
                u.roles = app_roles(acc)
                u.role = _role(u.roles)
                sess.refresh_token = tok.get("refresh_token") or sess.refresh_token
                sess.id_token = tok.get("id_token") or sess.id_token
                sess.refreshed_at = now
            except OIDCError as ex:            # signed out / disabled in Keycloak
                log.info("session of %s ended: %s", u.login, ex)
                s.delete(sess)
                return None
            except Exception:                  # Keycloak unreachable: keep the session, try later
                log.warning("token refresh failed (Keycloak unreachable?)", exc_info=True)
        if sess.last_seen_at < now - _TOUCH:
            sess.last_seen_at = now
        return _me(u)


def logout(token: str | None, base_url: str) -> str | None:
    """End the session; the Keycloak sign-out URL to send the browser to (None without a session)."""
    if not token:
        return None
    with db.session() as s:
        sess = s.scalar(select(AuthSession).where(AuthSession.token_hash == _digest(token)))
        if sess is None:
            return None
        id_token = sess.id_token
        s.delete(sess)
    if not enabled() or not os.environ.get("DWG3D_OIDC_ISSUER"):
        return None
    params = {"client_id": client_id(), "post_logout_redirect_uri": f"{base_url}/"}
    if id_token:
        params["id_token_hint"] = id_token
    return f"{_endpoint('logout', internal=False)}?{urllib.parse.urlencode(params)}"


# ------------------------------------------------------------------ users ---
def list_users(q: str = "", limit: int = 20) -> list[dict]:
    with db.session() as s:
        sel = select(User).where(User.active).order_by(User.name, User.login).limit(min(max(limit, 1), 100))
        if q:
            like = f"%{q.lower()}%"
            sel = sel.where(func.lower(User.login).like(like) | func.lower(User.name).like(like)
                            | func.lower(func.coalesce(User.email, "")).like(like))
        return [{"id": u.id, "login": u.login, "name": u.name, "email": u.email, "role": u.role, "roles": list(u.roles or []),
                 "last_login": u.last_login_at.isoformat(timespec="minutes") if u.last_login_at else None}
                for u in s.scalars(sel)]


def purge_sessions():
    """Drop expired sessions (called now and then by the API)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=session_days())
    with db.session() as s:
        s.execute(delete(AuthSession).where(AuthSession.last_seen_at < cutoff))
