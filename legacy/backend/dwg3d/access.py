"""Who may do what in a project: members and share links.

  owner    everything, plus members, share links, deleting the project
  editor   drawings, layers, objects, pins, settings
  viewer   reading

Global admins (Keycloak realm role "admin") are owners of every project.
A project someone may not open looks like one that does not exist (404);
a member without the needed role gets 403.

A share link gives read-only access to one project without an account,
optionally to some of its drawings and layers only; it may expire and be
revoked. Opening it (POST /api/share/{token}) puts the token in a cookie;
requests with it act as a guest (auth.Me.share).

The copilot (copilot.identity) acts for its user in one project only, with
the user's role there capped by its mode (AGENT_CAP).
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auth
from .models import Drawing, Layer, Project, ProjectMember, ShareLink, User

ROLES = ("viewer", "editor", "owner")
ROLE_NAMES = {"viewer": "просмотр", "editor": "редактор", "owner": "владелец"}
# the highest role the copilot has in its project (proposals need only reading); never owner
AGENT_CAP = {"read": "viewer", "propose": "viewer"}
SHARE_COOKIE = "dwg3d_share"
MAX_MEMBERS = 500
MAX_SHARES = 100


class Denied(Exception):
    """Not allowed: 404 (can't see the project) or 403 (can't do this)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def rank(role: str | None) -> int:
    return ROLES.index(role) if role in ROLES else -1


def need_for_request() -> str:
    return "viewer" if auth.method.get() in ("GET", "HEAD", "OPTIONS") else "editor"


def agent_cap(me: auth.Me, role: str | None) -> str | None:
    """The role of an agent: its user's, no higher than the token's mode allows."""
    if role is None or me.agent is None:
        return role
    return min(role, AGENT_CAP[me.agent["mode"]], key=rank)


def project_role(s: Session, me: auth.Me | None, pid: str) -> str | None:
    if me is None:
        return None
    if me.share is not None:
        return "viewer" if me.share["project_id"] == pid else None
    if me.agent is not None and me.agent["project_id"] != pid:
        return None
    if me.role == "admin":
        return agent_cap(me, "owner")
    return agent_cap(me, s.scalar(select(ProjectMember.role).where(ProjectMember.project_id == pid,
                                                                   ProjectMember.user_id == me.id)))


def check(s: Session, pid: str, need: str | None = None, what: str = "Проект не найден") -> str:
    """The current user's role in the project, or Denied."""
    me = auth.current.get()
    role = project_role(s, me, pid)
    need = need or need_for_request()
    if role is None:
        raise Denied(404, what)
    if rank(role) < rank(need):
        raise Denied(403, f"Недостаточно прав: нужна роль «{ROLE_NAMES[need]}» в проекте")
    return role


def check_drawing(s: Session, d: Drawing, need: str | None = None) -> str:
    me = auth.current.get()
    if me is not None and me.share is not None and me.share["drawings"] is not None \
            and d.id not in me.share["drawings"]:
        raise Denied(404, "Чертёж не найден")
    return check(s, d.project_id, need, "Чертёж не найден")


def visible(q, me: auth.Me | None, project_col=Project.id):
    """Limit a query to the projects the user may open."""
    if me is None:
        return q.where(False)
    if me.share is not None:
        return q.where(project_col == me.share["project_id"])
    if me.agent is not None:
        q = q.where(project_col == me.agent["project_id"])
    if me.role == "admin":
        return q
    return q.where(project_col.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == me.id)))


def visible_drawing(me: auth.Me | None, did: str) -> bool:
    return not (me is not None and me.share is not None and me.share["drawings"] is not None
                and did not in me.share["drawings"])


def visible_layers(me: auth.Me | None) -> set[str] | None:
    """The layers a guest may see (None: all)."""
    if me is not None and me.share is not None and me.share["layers"] is not None:
        return set(me.share["layers"])
    return None


def roles_of(s: Session, me: auth.Me | None, pids: list[str]) -> dict[str, str]:
    if me is None or not pids:
        return {}
    if me.share is not None:
        return {me.share["project_id"]: "viewer"} if me.share["project_id"] in pids else {}
    if me.agent is not None:
        pids = [p for p in pids if p == me.agent["project_id"]]
    if me.role == "admin":
        return {p: agent_cap(me, "owner") for p in pids}
    return {p: agent_cap(me, r) for p, r in s.execute(
        select(ProjectMember.project_id, ProjectMember.role)
        .where(ProjectMember.user_id == me.id, ProjectMember.project_id.in_(pids))).all()}


# --------------------------------------------------------------- members ---
def member_json(m: ProjectMember, u: User | None) -> dict:
    return {"id": m.id, "role": m.role, "role_name": ROLE_NAMES[m.role], "pending": m.user_id is None,
            "email": (u.email if u else None) or m.email,
            "user": {"id": u.id, "login": u.login, "name": u.name} if u else None}


def members(s: Session, pid: str) -> list[dict]:
    q = (select(ProjectMember, User).outerjoin(User, User.id == ProjectMember.user_id)
         .where(ProjectMember.project_id == pid))
    rows = sorted(s.execute(q), key=lambda r: (-rank(r[0].role), (r[1].name if r[1] else r[0].email or "").lower()))
    return [member_json(m, u) for m, u in rows]


def _role_arg(role) -> str:
    if role not in ROLES:
        raise ValueError(f"роль: {', '.join(ROLES)}")
    return role


def add_member(s: Session, pid: str, who: str, role: str) -> dict:
    """Add a user found by login or e-mail; an unknown e-mail becomes an invitation."""
    _role_arg(role)
    who = (who or "").strip()
    if not who or len(who) > 200:
        raise ValueError("укажите логин или e-mail")
    if s.scalar(select(func.count()).select_from(ProjectMember).where(ProjectMember.project_id == pid)) >= MAX_MEMBERS:
        raise ValueError(f"не больше {MAX_MEMBERS} участников")
    u = s.scalar(select(User).where(User.active, (func.lower(User.login) == who.lower())
                                    | (func.lower(User.email) == who.lower())))
    me = auth.current.get()
    if u is not None:
        if s.scalar(select(ProjectMember.id).where(ProjectMember.project_id == pid, ProjectMember.user_id == u.id)):
            raise ValueError(f"«{u.name or u.login}» уже участник проекта")
        m = ProjectMember(project_id=pid, user_id=u.id, role=role, added_by=me.id if me else None)
    else:
        if "@" not in who:
            raise ValueError(f"пользователь «{who}» не найден: пригласите его по e-mail")
        if s.scalar(select(ProjectMember.id).where(ProjectMember.project_id == pid, ProjectMember.user_id.is_(None),
                                                   func.lower(ProjectMember.email) == who.lower())):
            raise ValueError(f"приглашение для {who} уже есть")
        m = ProjectMember(project_id=pid, email=who, role=role, added_by=me.id if me else None)
    s.add(m)
    s.flush()
    return member_json(m, u)


def _owners(s: Session, pid: str) -> int:
    return s.scalar(select(func.count()).select_from(ProjectMember)
                    .where(ProjectMember.project_id == pid, ProjectMember.role == "owner",
                           ProjectMember.user_id.is_not(None)))


def set_member_role(s: Session, pid: str, mid: int, role: str) -> dict:
    _role_arg(role)
    m = s.scalar(select(ProjectMember).where(ProjectMember.id == mid, ProjectMember.project_id == pid)
                 .with_for_update())
    if m is None:
        raise LookupError(mid)
    if m.role == "owner" and role != "owner" and m.user_id is not None and _owners(s, pid) <= 1:
        raise ValueError("в проекте должен остаться хотя бы один владелец")
    m.role = role
    s.flush()
    return member_json(m, s.get(User, m.user_id) if m.user_id else None)


def remove_member(s: Session, pid: str, mid: int) -> dict:
    m = s.scalar(select(ProjectMember).where(ProjectMember.id == mid, ProjectMember.project_id == pid)
                 .with_for_update())
    if m is None:
        raise LookupError(mid)
    if m.role == "owner" and m.user_id is not None and _owners(s, pid) <= 1:
        raise ValueError("в проекте должен остаться хотя бы один владелец")
    out = member_json(m, s.get(User, m.user_id) if m.user_id else None)
    s.delete(m)
    return out


# ----------------------------------------------------------- share links ---
def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def share_json(x: ShareLink) -> dict:
    now = datetime.now(timezone.utc)
    return {"id": x.id, "name": x.name, "drawings": x.drawings, "layers": x.layers,
            "expires": x.expires_at.timestamp() if x.expires_at else None,
            "revoked": x.revoked_at is not None, "active": x.revoked_at is None and (x.expires_at is None or x.expires_at > now),
            "created": x.created_at.timestamp() if x.created_at else None,
            "last_used": x.last_used_at.timestamp() if x.last_used_at else None}


def shares(s: Session, pid: str) -> list[dict]:
    q = select(ShareLink).where(ShareLink.project_id == pid).order_by(ShareLink.created_at.desc())
    return [share_json(x) for x in s.scalars(q)]


def create_share(s: Session, pid: str, v: dict) -> tuple[dict, str]:
    """A new link: (its JSON, the token — shown once, only its hash is stored)."""
    if s.scalar(select(func.count()).select_from(ShareLink).where(ShareLink.project_id == pid,
                                                                   ShareLink.revoked_at.is_(None))) >= MAX_SHARES:
        raise ValueError(f"не больше {MAX_SHARES} действующих ссылок")
    name = v.get("name") or ""
    if not isinstance(name, str) or len(name) > 200:
        raise ValueError("name: строка до 200 символов")
    days = v.get("days")
    if days is not None and (isinstance(days, bool) or not isinstance(days, (int, float)) or not 0 < days <= 3650):
        raise ValueError("days: число дней от 1 до 3650 или null (бессрочно)")

    def ids(key, model, extra):
        x = v.get(key)
        if x is None:
            return None
        if not isinstance(x, list) or not all(isinstance(i, str) for i in x) or len(x) > 1000:
            raise ValueError(f"{key}: список id или null (все)")
        found = set(s.scalars(select(model.id).where(model.id.in_(x), model.project_id == pid, *extra)))
        if missing := [i for i in x if i not in found]:
            raise ValueError(f"{key}: нет в проекте: {', '.join(missing[:5])}")
        return list(dict.fromkeys(x))

    drawings = ids("drawings", Drawing, [Drawing.deleted_at.is_(None)])
    layers = ids("layers", Layer, [])
    token = secrets.token_urlsafe(24)
    me = auth.current.get()
    x = ShareLink(id=uuid.uuid4().hex[:12], project_id=pid, token_hash=_digest(token), name=name.strip(),
                  drawings=drawings, layers=layers, created_by=me.id if me else None,
                  expires_at=datetime.now(timezone.utc) + timedelta(days=days) if days else None)
    s.add(x)
    s.flush()
    return share_json(x), token


def revoke_share(s: Session, pid: str, sid: str) -> dict:
    x = s.scalar(select(ShareLink).where(ShareLink.id == sid, ShareLink.project_id == pid).with_for_update())
    if x is None:
        raise LookupError(sid)
    if x.revoked_at is None:
        x.revoked_at = func.now()
        s.flush()
        s.refresh(x)
    return share_json(x)


def resolve_share(token: str | None, touch: bool = False) -> auth.Me | None:
    """The guest of a share token (None: unknown, revoked, expired, project deleted)."""
    if not token or len(token) > 100:
        return None
    from . import db
    with db.session() as s:
        row = s.execute(select(ShareLink, Project).join(Project, Project.id == ShareLink.project_id)
                        .where(ShareLink.token_hash == _digest(token), ShareLink.revoked_at.is_(None),
                               Project.deleted_at.is_(None))).first()
        if row is None:
            return None
        x, p = row
        if x.expires_at is not None and x.expires_at <= datetime.now(timezone.utc):
            return None
        if touch:
            x.last_used_at = func.now()
        return auth.Me(None, "", x.name or "Гость", "user", None,
                       share={"id": x.id, "project_id": x.project_id, "drawings": x.drawings,
                              "layers": x.layers, "name": x.name, "project_name": p.name})
