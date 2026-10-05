"""What the user's open viewer windows show, and commands to them from agents.

A window reports (POST /api/projects/{id}/ui-context, debounced, and every
minute while open) what it shows: the drawing, floor, 2D / 3D, the selected
objects and room, the proposal being looked at; closing it sends `closed`.
The copilot acting for the user reads that (agent_tools.get_ui_context) to
understand "this", "on this floor".

It may also move the user's view (agent_tools.show_in_viewer): a command goes
as an event addressed to the user (events.py: "to_user"); the user's windows
of the project fly to the floor / room / objects and outline them. Commands
change nothing in the data.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from . import events
from .models import CatalogItem, Drawing, Floor, LayerObject, Room, UIContext

FRESH = timedelta(minutes=3)            # a window silent longer is taken for closed
KEEP = timedelta(days=1)
VIEWS = ("2d", "3d")


class ContextError(ValueError):
    """Bad report (HTTP 400)."""


def _str(v, n: int) -> str | None:
    return v[:n] if isinstance(v, str) and v else None


def clean(v: dict) -> dict:
    """The report as stored: known keys, bounded sizes."""
    if not isinstance(v, dict):
        raise ContextError("ожидается объект")
    sel = v.get("selected") or []
    if not isinstance(sel, list):
        raise ContextError("selected: список id")
    return {"drawing": _str(v.get("drawing"), 40), "floor": _str(v.get("floor"), 40),
            "view": v.get("view") if v.get("view") in VIEWS else None,
            "selected": [x[:40] for x in sel if isinstance(x, str)][:50],
            "room": v.get("room") if isinstance(v.get("room"), int) and not isinstance(v.get("room"), bool) else None,
            "proposal": _str(v.get("proposal"), 40), "tool": _str(v.get("tool"), 40)}


def report(s: Session, pid: str, user_id: int | None, client: str, v: dict):
    """Keep (or with `closed`, drop) what a window shows."""
    if not isinstance(client, str) or not 8 <= len(client) <= 64:
        raise ContextError("client: id окна, 8–64 символа")
    if v.get("closed"):
        s.execute(delete(UIContext).where(UIContext.client == client, UIContext.project_id == pid))
        return
    data = clean(v)
    stmt = insert(UIContext).values(client=client, project_id=pid, user_id=user_id, data=data, updated_at=func.now())
    s.execute(stmt.on_conflict_do_update(index_elements=[UIContext.client],
                                         set_={"project_id": pid, "user_id": user_id, "data": data, "updated_at": func.now()}))
    s.execute(delete(UIContext).where(UIContext.updated_at < datetime.now(timezone.utc) - KEEP))


def windows(s: Session, pid: str, user_id: int | None) -> list[dict]:
    """The user's open windows of the project, the most recently active first, with names next to ids."""
    now = datetime.now(timezone.utc)
    q = (select(UIContext).where(UIContext.project_id == pid, UIContext.updated_at > now - FRESH)
         .order_by(UIContext.updated_at.desc()))
    q = q.where(UIContext.user_id.is_(None) if user_id is None else UIContext.user_id == user_id)
    return [{"active_seconds_ago": int((now - w.updated_at).total_seconds()), **describe(s, pid, w.data)}
            for w in s.scalars(q)]


def describe(s: Session, pid: str, d: dict) -> dict:
    """What a window shows (its report), with names next to ids."""
    o: dict = {"view": d.get("view"), "tool": d.get("tool")}
    dr = s.get(Drawing, d["drawing"]) if d.get("drawing") else None
    if dr is not None and dr.project_id == pid and dr.deleted_at is None:
        o["drawing"] = {"id": dr.id, "name": dr.name or (dr.filename or "").rsplit(".", 1)[0]}
        if d.get("floor"):
            f = s.scalar(select(Floor).where(Floor.drawing_id == dr.id, Floor.candidate == d["floor"]))
            o["floor"] = {"id": d["floor"], "name": f.name if f else ""}
        if d.get("room") is not None:
            r = s.get(Room, d["room"])
            if r is not None and r.drawing_id == dr.id:
                o["room"] = {"id": r.id, "name": r.name or "", "area": round(r.area, 2)}
    if d.get("selected"):
        rows = s.execute(select(LayerObject.id, LayerObject.item_id, CatalogItem.name)
                         .outerjoin(CatalogItem, CatalogItem.id == LayerObject.item_id)
                         .where(LayerObject.project_id == pid, LayerObject.id.in_(d["selected"]))).all()
        o["selected"] = [{"id": i, "item": it, "name": nm or ""} for i, it, nm in rows]
    if d.get("proposal"):
        o["proposal"] = d["proposal"]
    return o


def command(s: Session, pid: str, user_id: int | None, cmd: dict, agent: str | None):
    """Send a view command to the user's windows of the project (on commit)."""
    ev = {"project": pid, "entity": "view", "to_user": user_id, "agent": agent, "command": cmd}
    s.execute(select(func.pg_notify(events.CHANNEL, json.dumps(ev, ensure_ascii=False, default=str))))
