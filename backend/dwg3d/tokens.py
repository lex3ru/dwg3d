"""Tokens of AI agents: access to one project without the browser.

An agent (an MCP client, a script) sends `Authorization: Bearer <token>` and
acts for the user who made the token: with that user's role in the project,
capped by the token's mode (access.AGENT_CAP), and only in that project.
Changes it makes are recorded under the user, marked with the token's name.

  read     reading
  propose  reading (later: proposals a person applies or rejects)
  write    reading; objects and pins, creating and changing layers

What an agent may never do, whatever its user's role (agent_may): manage
members, share links and tokens, delete layers, drawings or the project,
upload revisions, rebuild, change the catalog, lock or unlock layers.

A token is shown once (only its SHA-256 is stored), expires (at most a year)
and may be revoked by its author or an owner of the project. A user who left
the project or was disabled takes their tokens' access with them.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auth
from .models import AgentToken, Project, User

MODES = ("read", "propose", "write")
MODE_NAMES = {"read": "только чтение", "propose": "предложения", "write": "изменение"}
PREFIX = "dwg3d_"
MAX_TOKENS = 100            # active tokens in a project
MAX_DAYS = 365
_TOUCH = timedelta(minutes=5)

# changes an agent may make with a "write" token: (methods, path)
AGENT_WRITES = (
    ({"POST", "PATCH", "DELETE"}, re.compile(r"/api/drawings/[^/]+/(objects|pins)(:batch|/[^/]+)?")),
    ({"POST"}, re.compile(r"/api/projects/[^/]+/layers")),
    ({"PATCH"}, re.compile(r"/api/projects/[^/]+/layers/[^/]+")),
)
# not even to read: who is who, and the tokens themselves
AGENT_HIDDEN = re.compile(r"/api/users|/api/copilot(/.*)?|/api/projects/[^/]+/(members|shares|agent-tokens|copilot)(/.*)?")


def agent_may(method: str, path: str, mode: str) -> bool:
    """Whether an agent's token of this mode may make this request at all
    (the role in the project is checked by the endpoint, as for everyone)."""
    if AGENT_HIDDEN.fullmatch(path):
        return False
    if path == "/api/mcp":               # JSON-RPC over POST: each tool checks for itself (agent_mcp.py)
        return True
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    return mode == "write" and any(method in m and rx.fullmatch(path) for m, rx in AGENT_WRITES)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_json(x: AgentToken, u: User | None, me: auth.Me | None = None) -> dict:
    now = datetime.now(timezone.utc)
    return {"id": x.id, "name": x.name, "mode": x.mode, "mode_name": MODE_NAMES[x.mode],
            "user": {"id": u.id, "login": u.login, "name": u.name} if u else None,
            "mine": me is not None and x.user_id == me.id,
            "expires": x.expires_at.timestamp(), "revoked": x.revoked_at is not None,
            "active": x.revoked_at is None and x.expires_at > now,
            "created": x.created_at.timestamp() if x.created_at else None,
            "last_used": x.last_used_at.timestamp() if x.last_used_at else None}


def list_tokens(s: Session, pid: str, me: auth.Me | None, owner: bool) -> list[dict]:
    """The project's tokens: all of them for an owner, else the user's own."""
    q = (select(AgentToken, User).outerjoin(User, User.id == AgentToken.user_id)
         .where(AgentToken.project_id == pid).order_by(AgentToken.created_at.desc()))
    if not owner:
        q = q.where(AgentToken.user_id == (me.id if me else None))
    return [token_json(x, u, me) for x, u in s.execute(q)]


def create(s: Session, pid: str, v: dict, role: str) -> tuple[dict, str]:
    """A new token of the current user: (its JSON, the token — shown once).
    `role`: the user's role in the project; writing takes an editor."""
    me = auth.current.get()
    mode = v.get("mode") or "read"
    if mode not in MODES:
        raise ValueError(f"mode: {', '.join(MODES)}")
    if mode == "write" and role not in ("editor", "owner"):
        raise PermissionError("Токен на изменение может выпустить только редактор или владелец проекта")
    name = v.get("name") or ""
    if not isinstance(name, str) or len(name.strip()) > 120:
        raise ValueError("name: строка до 120 символов")
    days = v.get("days", 90)
    if isinstance(days, bool) or not isinstance(days, (int, float)) or not 0 < days <= MAX_DAYS:
        raise ValueError(f"days: число дней от 1 до {MAX_DAYS}")
    if s.scalar(select(func.count()).select_from(AgentToken).where(
            AgentToken.project_id == pid, AgentToken.revoked_at.is_(None),
            AgentToken.expires_at > func.now())) >= MAX_TOKENS:
        raise ValueError(f"не больше {MAX_TOKENS} действующих токенов в проекте")
    token = PREFIX + secrets.token_urlsafe(32)
    x = AgentToken(id=uuid.uuid4().hex[:12], project_id=pid, user_id=me.id if me else None,
                   token_hash=_digest(token), name=name.strip(), mode=mode,
                   expires_at=datetime.now(timezone.utc) + timedelta(days=days))
    s.add(x)
    s.flush()
    s.refresh(x)
    return token_json(x, s.get(User, x.user_id) if x.user_id else None, me), token


def revoke(s: Session, pid: str, tid: str, owner: bool) -> dict:
    """Revoke a token: the user's own, or any of the project's for an owner."""
    me = auth.current.get()
    x = s.scalar(select(AgentToken).where(AgentToken.id == tid, AgentToken.project_id == pid).with_for_update())
    if x is None or not (owner or (me is not None and x.user_id == me.id)):
        raise LookupError(tid)
    if x.revoked_at is None:
        x.revoked_at = func.now()
        s.flush()
        s.refresh(x)
    return token_json(x, s.get(User, x.user_id) if x.user_id else None, me)


def resolve(token: str | None) -> auth.Me | None:
    """The agent of a token, acting as its user (None: unknown, revoked,
    expired, project deleted, user disabled)."""
    if not token or not token.startswith(PREFIX) or len(token) > 100:
        return None
    from . import db
    now = datetime.now(timezone.utc)
    with db.session() as s:
        row = s.execute(select(AgentToken, User).join(Project, Project.id == AgentToken.project_id)
                        .outerjoin(User, User.id == AgentToken.user_id)
                        .where(AgentToken.token_hash == _digest(token), AgentToken.revoked_at.is_(None),
                               AgentToken.expires_at > now, Project.deleted_at.is_(None))).first()
        if row is None:
            return None
        x, u = row
        if u is None and auth.enabled() or u is not None and not u.active:
            return None
        if x.last_used_at is None or x.last_used_at < now - _TOUCH:
            x.last_used_at = now
        agent = {"id": x.id, "name": x.name, "project_id": x.project_id, "mode": x.mode}
        if u is None:                       # made with sign-in off
            return auth.Me(None, "", "", "admin", agent=agent)
        return auth.Me(u.id, u.login, u.name or u.login, u.role, u.email, roles=tuple(u.roles or ()), agent=agent)
