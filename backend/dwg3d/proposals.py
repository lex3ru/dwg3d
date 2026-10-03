"""Proposals of AI agents: changes a person applies or rejects.

An agent (MCP propose_changes) proposes operations on the layer objects of a
drawing — the same as viewdata.apply takes. They are checked at once against
the current rows (a dry run in a savepoint, rolled back) and kept; a person
sees what they would do (preview: the rows created, the rows before and after
an update, the rows deleted — again a dry run, on the rows as they are now)
and applies them as their own change, marked in the audit log, or rejects
them. A proposal whose rows or build changed since is stale: it can no longer
be applied (the agent may propose again).

  open → applied | rejected | stale
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auth, viewdata
from .models import Drawing, LayerObject, Proposal, User

STATUSES = ("open", "applied", "rejected", "stale")
STATUS_NAMES = {"open": "ждёт решения", "applied": "применено", "rejected": "отклонено", "stale": "устарело"}
MAX_OPS = 1000
MAX_OPEN = 50                   # open proposals in a project


@contextmanager
def savepoint(s: Session, keep: bool):
    """Run changes in a savepoint: kept (`keep`, and no error) or rolled back
    together with the events they queued for the commit (events.py)."""
    pending = s.info.get("dwg3d_events")
    kept = {k: (dict(h), list(c)) for k, (h, c) in pending.items()} if pending else None

    def undo():
        sp.rollback()
        if kept is None:
            s.info.pop("dwg3d_events", None)
        else:
            s.info["dwg3d_events"] = kept

    sp = s.begin_nested()
    try:
        yield
    except BaseException:
        undo()
        raise
    if keep:
        sp.commit()
    else:
        undo()


def dry_run(s: Session):
    """Run changes to see they apply (or what they give), then roll them back."""
    return savepoint(s, keep=False)


def counts(ops: list) -> dict:
    return {k: sum(1 for o in ops if o.get("op") == k) for k in ("create", "update", "delete")}


def proposal_json(p: Proposal, users: dict[int, User] | None = None, drawing: Drawing | None = None) -> dict:
    users = users or {}
    who = users.get(p.user_id) if p.user_id else None
    by = users.get(p.decided_by) if p.decided_by else None
    o = {"id": p.id, "project_id": p.project_id, "drawing_id": p.drawing_id, "summary": p.summary,
         "status": p.status, "status_name": STATUS_NAMES[p.status], "reason": p.reason,
         "agent": p.agent, "user": {"id": who.id, "login": who.login, "name": who.name} if who else None,
         "counts": counts(p.ops), "build": p.build,
         "created": p.created_at.timestamp() if p.created_at else None,
         "decided": p.decided_at.timestamp() if p.decided_at else None,
         "decided_by": {"id": by.id, "login": by.login, "name": by.name} if by else None}
    if drawing is not None:
        o["drawing"] = drawing.name or (drawing.filename or "").rsplit(".", 1)[0]
    return o


def _users(s: Session, ps: list[Proposal]) -> dict[int, User]:
    ids = {i for p in ps for i in (p.user_id, p.decided_by) if i}
    return {u.id: u for u in s.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def listing(s: Session, pid: str, status: str | None = None, drawing: str | None = None,
            token: str | None = None, limit: int = 100) -> list[dict]:
    q = select(Proposal).where(Proposal.project_id == pid).order_by(Proposal.created_at.desc()).limit(min(max(limit, 1), 500))
    if status:
        q = q.where(Proposal.status == status)
    if drawing:
        q = q.where(Proposal.drawing_id == drawing)
    if token:
        q = q.where(Proposal.token_id == token)
    ps = list(s.scalars(q))
    users = _users(s, ps)
    names = {d.id: d for d in s.scalars(select(Drawing).where(Drawing.id.in_({p.drawing_id for p in ps})))}
    return [proposal_json(p, users, names.get(p.drawing_id)) for p in ps]


def _ids(ops: list) -> list[dict]:
    """New objects get their ids now: the proposal shows and applies the same ones."""
    if not isinstance(ops, list) or not ops or len(ops) > MAX_OPS:
        raise viewdata.Invalid(f"ops: от 1 до {MAX_OPS} операций")
    if any(not isinstance(o, dict) for o in ops):
        raise viewdata.Invalid("ops: список объектов-операций")
    return [{**o, "id": o.get("id") or uuid.uuid4().hex[:8]} if o.get("op") == "create" else o for o in ops]


def create(s: Session, d: Drawing, summary: str, ops: list, build: int | None) -> Proposal:
    """Check the operations against the current rows (all would apply) and keep them.
    Raises viewdata.Invalid / Conflict as apply would."""
    me = auth.current.get()
    summary = (summary or "").strip()
    if not summary or len(summary) > 2000:
        raise viewdata.Invalid("summary: что и зачем меняется, до 2000 символов")
    ops = _ids(ops)
    if s.scalar(select(func.count()).select_from(Proposal).where(Proposal.project_id == d.project_id,
                                                                 Proposal.status == "open")) >= MAX_OPEN:
        raise viewdata.Invalid(f"в проекте уже {MAX_OPEN} предложений ждут решения")
    with dry_run(s):
        viewdata.apply(s, d.id, "object", ops, build=build)
    p = Proposal(id=uuid.uuid4().hex[:12], project_id=d.project_id, drawing_id=d.id,
                 token_id=me.agent["id"] if me and me.agent and not me.agent.get("copilot") else None,
                 agent=(me.agent["name"] or me.agent["id"]) if me and me.agent else "",
                 user_id=me.id if me else None, summary=summary, ops=ops, build=d.current_build)
    s.add(p)
    s.flush()
    s.refresh(p)
    return p


def _stale(p: Proposal, why: str):
    p.status, p.reason, p.decided_at = "stale", why, datetime.now(timezone.utc)


def preview(s: Session, p: Proposal) -> dict:
    """What the proposal would do now: {created: [rows], updated: [{before, after}], deleted: [rows]}.
    An open proposal that no longer applies becomes stale (with the reason)."""
    floors = viewdata._floors(s, p.drawing_id)
    ids = [o["id"] for o in p.ops if o.get("op") in ("update", "delete") and isinstance(o.get("id"), str)]
    before = {r.id: viewdata.object_json(r, floors) for r in s.scalars(
        select(LayerObject).where(LayerObject.project_id == p.project_id, LayerObject.id.in_(ids)))}
    out: dict = {"created": [], "updated": [], "deleted": []}
    if p.status != "open":
        return out
    try:
        with dry_run(s):
            res = viewdata.apply(s, p.drawing_id, "object", p.ops, build=p.build)
    except (viewdata.Invalid, viewdata.Conflict, LookupError) as ex:
        _stale(p, str(ex) or "чертёж удалён")
        return out
    created = {o["id"] for o in p.ops if o.get("op") == "create"}
    for row in res["items"]:
        if row["id"] in created:
            out["created"].append(row)
        else:
            out["updated"].append({"before": before.get(row["id"]), "after": row})
    out["deleted"] = [before[i] for i in res["deleted"] if i in before]
    return out


def apply(s: Session, p: Proposal) -> dict:
    """Apply as the current user's change ("по предложению агента" in the audit log).
    Returns viewdata.apply's answer; a proposal that no longer applies becomes stale
    and viewdata.Conflict is raised (the caller commits the status)."""
    if p.status != "open":
        raise viewdata.Invalid(f"предложение {STATUS_NAMES[p.status]}")
    token = viewdata.audit_via.set(f"по предложению агента «{p.agent or 'агент'}»")
    try:
        with savepoint(s, keep=True):       # a failure leaves nothing half done, only the status
            res = viewdata.apply(s, p.drawing_id, "object", p.ops, build=p.build)
    except (viewdata.Invalid, viewdata.Conflict, LookupError) as ex:
        _stale(p, str(ex) or "чертёж удалён")
        raise viewdata.Conflict(f"Предложение устарело: {p.reason}", []) from ex
    finally:
        viewdata.audit_via.reset(token)
    me = auth.current.get()
    p.status, p.decided_at, p.decided_by = "applied", datetime.now(timezone.utc), me.id if me else None
    return res


def reject(s: Session, p: Proposal, reason: str | None):
    if p.status != "open":
        raise viewdata.Invalid(f"предложение {STATUS_NAMES[p.status]}")
    me = auth.current.get()
    p.status, p.decided_at, p.decided_by = "rejected", datetime.now(timezone.utc), me.id if me else None
    p.reason = (reason or "").strip()[:2000] or None
