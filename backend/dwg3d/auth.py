"""Users, roles and sessions.

Roles, each including the previous one:
  viewer         opens projects, models, reports
  editor         uploads and rebuilds drawings, edits furniture, pins, settings
  catalog_admin  edits the equipment catalog

Passwords are hashed with scrypt (stdlib). A login creates a session row;
the browser keeps only a random token in an HttpOnly cookie, the database
keeps its SHA-256. Users are managed from the command line:

  python -m dwg3d user add LOGIN --role editor [--name "Имя"]   (asks for the password)
  python -m dwg3d user passwd LOGIN | role LOGIN ROLE | disable LOGIN | enable LOGIN | list

  DWG3D_AUTH           on (default) | off — off: no login, everyone is catalog_admin
                       (only for a server reachable from a trusted network)
  DWG3D_SESSION_DAYS   session lifetime since the last request (14)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from . import db
from .models import AuthSession, User

ROLES = ("viewer", "editor", "catalog_admin")
ROLE_NAMES = {"viewer": "просмотр", "editor": "редактор", "catalog_admin": "администратор каталога"}
COOKIE = "dwg3d_session"
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
_TOUCH = timedelta(minutes=5)          # last_seen is refreshed at most this often


@dataclass(frozen=True)
class Me:
    id: int | None
    login: str
    name: str
    role: str

    def can(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)

    def json(self) -> dict:
        return {"id": self.id, "login": self.login, "name": self.name, "role": self.role,
                "role_name": ROLE_NAMES[self.role], "auth": enabled()}


ANONYMOUS_ADMIN = Me(None, "", "", "catalog_admin")
# the user of the current request (set by the API middleware; read by the audit log)
current: ContextVar[Me | None] = ContextVar("dwg3d_user", default=None)


def enabled() -> bool:
    return os.environ.get("DWG3D_AUTH", "on").strip().lower() not in ("off", "0", "false", "no")


def session_days() -> float:
    return float(os.environ.get("DWG3D_SESSION_DAYS", "14"))


# -------------------------------------------------------------- passwords ---
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${h.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    try:
        algo, n, r, p, salt, h = (stored or "").split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(h) // 2)
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password(secrets.token_hex(8))    # same work for unknown logins (no timing oracle)


def _me(u: User) -> Me:
    return Me(u.id, u.login, u.name or u.login, u.role)


# --------------------------------------------------------------- sessions ---
def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(login_: str, password: str, user_agent: str = "") -> tuple[str, Me] | None:
    """(token, user) for valid credentials of an active user, else None."""
    with db.session() as s:
        u = s.scalar(select(User).where(func.lower(User.login) == login_.strip().lower()))
        ok = check_password(password, u.password_hash if u else _DUMMY)
        if not (u and ok and u.active):
            return None
        token = secrets.token_urlsafe(32)
        s.add(AuthSession(token_hash=_digest(token), user_id=u.id, user_agent=user_agent[:300]))
        u.last_login_at = func.now()
        return token, _me(u)


def resolve(token: str | None) -> Me | None:
    """The user of a session token, or None (unknown, expired, user disabled)."""
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
        if sess.last_seen_at < now - _TOUCH:
            sess.last_seen_at = now
        return _me(u)


def logout(token: str | None):
    if token:
        with db.session() as s:
            s.execute(delete(AuthSession).where(AuthSession.token_hash == _digest(token)))


# ------------------------------------------------------------------ users ---
class UserError(ValueError):
    pass


def _check_role(role: str):
    if role not in ROLES:
        raise UserError(f"роль: {', '.join(ROLES)}")


def _check_password(password: str):
    if len(password) < 8:
        raise UserError("пароль — не короче 8 символов")


def add_user(login_: str, password: str, role: str = "viewer", name: str = "") -> int:
    login_ = login_.strip()
    if not login_ or len(login_) > 80:
        raise UserError("логин — от 1 до 80 символов")
    _check_role(role)
    _check_password(password)
    with db.session() as s:
        if s.scalar(select(User.id).where(func.lower(User.login) == login_.lower())):
            raise UserError(f"пользователь «{login_}» уже есть")
        u = User(login=login_, name=name.strip() or login_, role=role, password_hash=hash_password(password))
        s.add(u)
        s.flush()
        return u.id


def _user(s, login_: str) -> User:
    u = s.scalar(select(User).where(func.lower(User.login) == login_.strip().lower()))
    if u is None:
        raise UserError(f"пользователя «{login_}» нет")
    return u


def set_password(login_: str, password: str):
    _check_password(password)
    with db.session() as s:
        u = _user(s, login_)
        u.password_hash = hash_password(password)
        s.execute(delete(AuthSession).where(AuthSession.user_id == u.id))     # sign out everywhere


def set_role(login_: str, role: str):
    _check_role(role)
    with db.session() as s:
        _user(s, login_).role = role


def set_active(login_: str, active: bool):
    with db.session() as s:
        u = _user(s, login_)
        u.active = active
        if not active:
            s.execute(delete(AuthSession).where(AuthSession.user_id == u.id))


def list_users() -> list[dict]:
    with db.session() as s:
        return [{"login": u.login, "name": u.name, "role": u.role, "active": u.active,
                 "last_login": u.last_login_at.isoformat(timespec="minutes") if u.last_login_at else None}
                for u in s.scalars(select(User).order_by(User.login))]


def has_users() -> bool:
    with db.session() as s:
        return s.scalar(select(func.count()).select_from(User).where(User.active)) > 0


def purge_sessions():
    """Drop expired sessions (called now and then by the API)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=session_days())
    with db.session() as s:
        s.execute(delete(AuthSession).where(AuthSession.last_seen_at < cutoff))

