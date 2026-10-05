"""Proposals of AI agents: changes a person applies or rejects.

The copilot (agent_tools.propose_changes) proposes operations on the layer objects of a
drawing — the same as viewdata.apply takes — and on layers (LAYER_OPS: a new layer, a
variant, renaming or showing, deleting), which run first, so that objects may go to a
layer made in the same proposal. They are checked at once against
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

from . import auth, layers, viewdata
from .models import Drawing, Layer, LayerObject, Project, Proposal, User

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


LAYER_OPS = ("create_layer", "copy_layer", "update_layer", "delete_layer")


def counts(ops: list) -> dict:
    return {**{k: sum(1 for o in ops if o.get("op") == k) for k in ("create", "update", "delete")},
            "layers": sum(1 for o in ops if o.get("op") in LAYER_OPS)}


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


def one_json(s: Session, p: Proposal) -> dict:
    """proposal_json of one proposal, with its people and drawing looked up."""
    return proposal_json(p, _users(s, [p]), s.get(Drawing, p.drawing_id))


def listing(s: Session, pid: str, status: str | None = None, drawing: str | None = None,
            user_id: int | None = None, agent: str | None = None, limit: int = 100) -> list[dict]:
    """Proposals of a project, newest first; of one user's agent when `agent` is given."""
    q = select(Proposal).where(Proposal.project_id == pid).order_by(Proposal.created_at.desc()).limit(min(max(limit, 1), 500))
    if status:
        q = q.where(Proposal.status == status)
    if drawing:
        q = q.where(Proposal.drawing_id == drawing)
    if agent is not None:
        q = q.where(Proposal.agent == agent,
                    Proposal.user_id.is_(None) if user_id is None else Proposal.user_id == user_id)
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
    out = []
    for o in ops:
        if o.get("op") == "create":
            o = {**o, "id": o.get("id") or uuid.uuid4().hex[:8]}
        elif o.get("op") in ("create_layer", "copy_layer"):
            lid = o.get("id") or uuid.uuid4().hex[:12]
            if not isinstance(lid, str) or not lid.isalnum() or not 6 <= len(lid) <= 24:
                raise viewdata.Invalid(f"{o['op']}.id: 6–24 латинских букв и цифр")
            o = {**o, "id": lid}
        out.append(o)
    return out


def _layer(s: Session, pid: str, lid) -> Layer:
    layer = s.get(Layer, lid) if isinstance(lid, str) else None
    if layer is None or layer.project_id != pid:
        raise viewdata.Invalid(f"слоя «{lid}» нет в проекте")
    return layer


def _layer_op(s: Session, pid: str, o: dict) -> dict:
    """One operation on layers (audited like the HTTP API's): what it did, for the preview."""
    op = o["op"]
    if op == "create_layer":
        layer = layers.create(s, pid, {"kind": o.get("kind"), "name": o.get("name")}, o["id"])
        viewdata.audit_entry(s, pid, "layer", layer.id, "create", None, layers.layer_json(layer))
        out = {"op": op, "id": layer.id, "name": layer.name, "kind": layer.kind}
    elif op == "copy_layer":
        src = _layer(s, pid, o.get("layer"))
        layer = layers.copy_layer(s, src, o.get("name"), o["id"], derived_ids=True)
        n = s.scalar(select(func.count()).select_from(LayerObject).where(LayerObject.layer_id == layer.id))
        viewdata.audit_entry(s, pid, "layer", layer.id, "create", None, {**layers.layer_json(layer), "copy_of": src.id})
        out = {"op": op, "id": layer.id, "name": layer.name, "kind": layer.kind, "of": src.name, "objects": n}
    elif op == "update_layer":
        layer = _layer(s, pid, o.get("layer"))
        if "locked" in o:
            raise viewdata.Invalid("блокировку слоя меняет только человек")
        changes = layers.update(layer, {k: o[k] for k in ("name", "visible") if k in o})
        if changes:
            viewdata.audit_entry(s, pid, "layer", layer.id, "update", {k: b for k, (b, _) in changes.items()},
                                 {k: a for k, (_, a) in changes.items()})
        out = {"op": op, "id": layer.id, "name": layer.name, "changes": {k: a for k, (_, a) in changes.items()}}
    else:
        layer = _layer(s, pid, o.get("layer"))
        if layer.locked:
            raise viewdata.Invalid(f"слой «{layer.name}» заблокирован")
        n = s.scalar(select(func.count()).select_from(LayerObject).where(LayerObject.layer_id == layer.id))
        viewdata.audit_entry(s, pid, "layer", layer.id, "delete", layers.layer_json(layer), None)
        out = {"op": op, "id": layer.id, "name": layer.name, "objects": n}
        s.delete(layer)
    s.flush()
    s.execute(Project.__table__.update().where(Project.id == pid).values(updated_at=func.now()))
    return out


def _run(s: Session, pid: str, did: str, ops: list, build: int | None) -> tuple[list[dict], dict]:
    """The layer operations, then the objects' (viewdata.apply): (what the layer ones did, apply's answer)."""
    done = []
    try:
        for o in ops:
            if o.get("op") in LAYER_OPS:
                done.append(_layer_op(s, pid, o))
    except layers.LayerError as ex:
        raise viewdata.Invalid(str(ex)) from ex
    objs = [o for o in ops if o.get("op") not in LAYER_OPS]
    res = viewdata.apply(s, did, "object", objs, build=build) if objs else {"items": [], "deleted": []}
    return done, res


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
        _run(s, d.project_id, d.id, ops, build)
    p = Proposal(id=uuid.uuid4().hex[:12], project_id=d.project_id, drawing_id=d.id,
                 agent=(me.agent["name"] or me.agent["id"]) if me and me.agent else "",
                 user_id=me.id if me else None, summary=summary, ops=ops, build=d.current_build)
    s.add(p)
    s.flush()
    s.refresh(p)
    return p


def _stale(p: Proposal, why: str):
    p.status, p.reason, p.decided_at = "stale", why, datetime.now(timezone.utc)


def preview(s: Session, p: Proposal) -> dict:
    """What the proposal would do now: {layers: [what each layer operation does],
    created: [rows], updated: [{before, after}], deleted: [rows]}.
    An open proposal that no longer applies becomes stale (with the reason)."""
    floors = viewdata._floors(s, p.drawing_id)
    ids = [o["id"] for o in p.ops if o.get("op") in ("update", "delete") and isinstance(o.get("id"), str)]
    before = {r.id: viewdata.object_json(r, floors) for r in s.scalars(
        select(LayerObject).where(LayerObject.project_id == p.project_id, LayerObject.id.in_(ids)))}
    out: dict = {"layers": [], "created": [], "updated": [], "deleted": []}
    if p.status != "open":
        return out
    try:
        with dry_run(s):
            out["layers"], res = _run(s, p.project_id, p.drawing_id, p.ops, p.build)
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
    """Apply as the current user's change ("по предложению копилота" in the audit log).
    Returns viewdata.apply's answer; a proposal that no longer applies becomes stale
    and viewdata.Conflict is raised (the caller commits the status)."""
    if p.status != "open":
        raise viewdata.Invalid(f"предложение {STATUS_NAMES[p.status]}")
    token = viewdata.audit_via.set("по предложению копилота")
    try:
        with savepoint(s, keep=True):       # a failure leaves nothing half done, only the status
            done, res = _run(s, p.project_id, p.drawing_id, p.ops, p.build)
    except (viewdata.Invalid, viewdata.Conflict, LookupError) as ex:
        _stale(p, str(ex) or "чертёж удалён")
        raise viewdata.Conflict(f"Предложение устарело: {p.reason}", []) from ex
    finally:
        viewdata.audit_via.reset(token)
    me = auth.current.get()
    p.status, p.decided_at, p.decided_by = "applied", datetime.now(timezone.utc), me.id if me else None
    return {**res, "layers": done}


def reject(s: Session, p: Proposal, reason: str | None):
    if p.status != "open":
        raise viewdata.Invalid(f"предложение {STATUS_NAMES[p.status]}")
    me = auth.current.get()
    p.status, p.decided_at, p.decided_by = "rejected", datetime.now(timezone.utc), me.id if me else None
    p.reason = (reason or "").strip()[:2000] or None
