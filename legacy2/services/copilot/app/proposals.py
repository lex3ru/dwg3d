# ruff: noqa: E501
"""Proposals of the copilot: a list of actions the user applies with a click, with their own token — so the
services check the rights and the journal names the person. Changes of objects go as planning variants
instead (tools/proposing.py); here is everything else."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import Identity, Problem, emit
from twin_chassis.client import ServiceClient

from .models import proposals

log = logging.getLogger("copilot")
MAX_ACTIONS = 500


def action(label: str, service: str, method: str, path: str, body: dict | None = None, show: dict | None = None) -> dict:
    """`show` — how the panel draws it on the plan: {kind: new|move|remove, floor_id, x, y, from?: {floor_id, x, y}, title}."""
    return {"label": label, "service": service, "method": method, "path": path, **({"body": body} if body is not None else {}),
            **({"show": show} if show else {})}


def new_asset_action(label: str, type_id: str, floor_id: str, x: float, y: float, angle: float | None = None,
                     product_id: str | None = None, inventory_no: str | None = None, show: dict | None = None) -> dict:
    """A new object; without an inventory number it is placed off the books, to be put on them later in its card."""
    return {"label": label, "kind": "asset_new", "type_id": type_id, "floor_id": floor_id, "x": x, "y": y,
            **({"angle": angle} if angle is not None else {}), **({"product_id": product_id} if product_id else {}),
            **({"inventory_no": inventory_no} if inventory_no else {}), **({"show": show} if show else {})}


def sketch_action(label: str, drawing_id: str, version: int, sketch: dict) -> dict:
    return {"label": label, "kind": "sketch", "drawing_id": drawing_id, "version": version, "sketch": sketch}


def _iso(t) -> str | None:
    return t.isoformat() if isinstance(t, datetime) else t


def as_json(row) -> dict:
    m = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    acts = m.get("actions") or []
    return {"id": str(m["id"]), "kind": "proposal", "chat_id": str(m["chat_id"]), "user_sub": m["user_sub"],
            "building_id": str(m["building_id"]) if m.get("building_id") else None, "summary": m["summary"],
            "status": m["status"], "result": m.get("result"), "created_at": _iso(m.get("created_at")), "decided_at": _iso(m.get("decided_at")),
            "decided_by": m.get("decided_by"), "count": len(acts),
            "labels": [a.get("label") for a in acts][:50],
            "sketch": next(({"drawing_id": a["drawing_id"], "version": a["version"]} for a in acts if a.get("kind") == "sketch"), None),
            "shows": [a["show"] for a in acts if a.get("show")][:500],
            "drawing_id": next((d.get("drawing_id") for d in ((m.get("result") or {}).get("done") or []) if d.get("drawing_id")), None)}


async def create(session: AsyncSession, *, chat_id: str, me: Identity, building_id: str | None, summary: str,
                 actions: list[dict]) -> dict:
    if not actions:
        raise ValueError("Нечего предлагать: список действий пуст")
    if len(actions) > MAX_ACTIONS:
        raise ValueError(f"Слишком много действий в одном предложении (больше {MAX_ACTIONS}): разбейте")
    summary = summary.strip()[:2000] or "Предложение копилота"
    pid = uuid4()
    await session.execute(proposals.insert().values(
        id=pid, chat_id=UUID(chat_id), user_sub=me.sub, building_id=UUID(building_id) if building_id else None,
        summary=summary, actions=actions, status="open"))
    row = (await session.execute(select(proposals).where(proposals.c.id == pid))).one()
    await emit(session, "copilot.proposal.created", ("proposal", pid),
               {"proposal_id": str(pid), "chat_id": str(chat_id), "summary": summary, "actions": len(actions)},
               **({"building_id": UUID(building_id)} if building_id else {}))
    return as_json(row)


async def one(session: AsyncSession, pid: UUID, *, lock: bool = False):
    q = select(proposals).where(proposals.c.id == pid)
    if lock:
        q = q.with_for_update()
    return (await session.execute(q)).one_or_none()


async def apply(session: AsyncSession, client: ServiceClient, row, me: Identity, token: str) -> dict:
    """Run the actions in order with the applier's token; stop at the first refusal. A 409 (someone changed the
    data) makes the proposal stale; another refusal leaves it open with the reason, so it may be retried or rejected.
    A `sketch` action puts the whole drawn plan (its editor applies such a proposal itself when it is open)."""
    if row.status != "open":
        raise Problem(409, "not_open", f"Предложение уже {STATUS_NAMES.get(row.status, row.status)}")
    done: list[dict] = []
    failure: dict | None = None
    status = "applied"
    for i, a in enumerate(row.actions or []):
        try:
            if a.get("kind") == "sketch":
                r = await client.request("PUT", "import", f"/drawings/{a['drawing_id']}/sketch", token=token,
                                         json={"sketch": a["sketch"], "version": a["version"]})
            elif a.get("kind") == "asset_new":
                number = a.get("inventory_no") or None
                r = await client.request("POST", "assets", "/assets", token=token, json={
                    "type_id": a["type_id"], "inventory_no": number, "floor_id": a["floor_id"], "x": a["x"], "y": a["y"],
                    **({"angle": a["angle"]} if a.get("angle") is not None else {}),
                    **({"product_id": a["product_id"]} if a.get("product_id") else {})})
                if r.status_code < 300:
                    done.append({"index": i, "label": a.get("label"), "status": r.status_code, "asset_id": r.json().get("id"),
                                 "inventory_no": r.json().get("inventory_no")})
                    continue
            elif a.get("kind") == "sketch_new":
                # a new drawn plan: the drawing first, then its plan over the empty one it starts with
                r = await client.request("POST", "import", "/sketches", token=token,
                                         json={"building_id": a["building_id"], "name": a["name"]})
                if r.status_code < 300:
                    made = r.json()
                    v = await client.request("GET", "import", f"/drawings/{made['id']}/sketch", token=token)
                    version = v.json().get("version", 0) if v.status_code == 200 else 0
                    r = await client.request("PUT", "import", f"/drawings/{made['id']}/sketch", token=token,
                                             json={"sketch": a["sketch"], "version": version})
                    if r.status_code < 300:
                        done.append({"index": i, "label": a.get("label"), "status": r.status_code, "drawing_id": made["id"]})
                        continue
            else:
                kw = {"json": a["body"]} if a.get("body") is not None else {}
                r = await client.request(a["method"], a["service"], a["path"], token=token, **kw)
        except Problem as ex:
            failure = {"index": i, "label": a.get("label"), "status": ex.status, "detail": ex.detail or ex.code}
            status = "open"
            break
        if r.status_code >= 300:
            try:
                detail = r.json().get("detail") or r.json().get("code")
            except ValueError:
                detail = r.text[:200]
            failure = {"index": i, "label": a.get("label"), "status": r.status_code, "detail": detail}
            status = "stale" if r.status_code == 409 else "open"
            break
        done.append({"index": i, "label": a.get("label"), "status": r.status_code})
    result = {"done": done, "failed": failure, "at": datetime.now(UTC).isoformat()}
    values: dict = {"result": result, "status": status}
    if status != "open":
        values.update(decided_at=datetime.now(UTC), decided_by=me.sub)
    await session.execute(update(proposals).where(proposals.c.id == row.id).values(**values))
    if status == "applied":
        await emit(session, "copilot.proposal.applied", ("proposal", row.id),
                   {"proposal_id": str(row.id), "chat_id": str(row.chat_id), "summary": row.summary, "actions": len(done)},
                   **({"building_id": row.building_id} if row.building_id else {}))
    fresh = await one(session, row.id)
    return as_json(fresh)


async def applied_elsewhere(session: AsyncSession, row, me: Identity) -> dict:
    """The editor applied the plan of the proposal itself: mark it, run nothing."""
    if row.status != "open":
        raise Problem(409, "not_open", f"Предложение уже {STATUS_NAMES.get(row.status, row.status)}")
    if not any(a.get("kind") == "sketch" for a in row.actions or []):
        raise Problem(422, "invalid", "Так применяется только предложение о нарисованном плане")
    result = {"done": [{"index": i, "label": a.get("label"), "status": "editor"} for i, a in enumerate(row.actions or [])],
              "failed": None, "at": datetime.now(UTC).isoformat()}
    await session.execute(update(proposals).where(proposals.c.id == row.id).values(
        result=result, status="applied", decided_at=datetime.now(UTC), decided_by=me.sub))
    await emit(session, "copilot.proposal.applied", ("proposal", row.id),
               {"proposal_id": str(row.id), "chat_id": str(row.chat_id), "summary": row.summary, "actions": len(row.actions or [])},
               **({"building_id": row.building_id} if row.building_id else {}))
    return as_json(await one(session, row.id))


async def reject(session: AsyncSession, row, me: Identity, reason: str | None) -> dict:
    if row.status != "open":
        raise Problem(409, "not_open", f"Предложение уже {STATUS_NAMES.get(row.status, row.status)}")
    await session.execute(update(proposals).where(proposals.c.id == row.id).values(
        status="rejected", result={"reason": (reason or "").strip()[:2000]}, decided_at=datetime.now(UTC), decided_by=me.sub))
    await emit(session, "copilot.proposal.rejected", ("proposal", row.id),
               {"proposal_id": str(row.id), "chat_id": str(row.chat_id), "summary": row.summary, "actions": len(row.actions or [])},
               **({"building_id": row.building_id} if row.building_id else {}))
    return as_json(await one(session, row.id))


STATUS_NAMES = {"open": "ждёт решения", "applied": "применено", "rejected": "отклонено", "stale": "устарело"}
