"""Projects, their audit and live events, members and share links."""
from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import func

from .. import access, auth, db, events, store, uicontext, viewdata
from ..config import load_config
from ..models import Project, ProjectMember
from . import common
from .common import STREAM_HEADERS, bad, base_url, text, whoami

router = APIRouter()


@router.get("/api/config/default")
def default_config():
    return load_config()


@router.get("/api/projects")
def list_projects():
    """The projects the user may open, with their drawings and the user's role."""
    with db.session() as s:
        return store.list_projects(s, auth.current.get())


@router.post("/api/projects", status_code=201)
def create_project(v: dict):
    name = text(v, "name", 200, required=True)
    with db.session() as s:
        me = auth.current.get()
        p = Project(id=uuid.uuid4().hex[:12], name=name, description=text(v, "description", 5000) or "",
                    created_by=me.id if me else None)
        s.add(p)
        s.flush()
        if me is not None and me.id is not None:           # the author owns it
            s.add(ProjectMember(project_id=p.id, user_id=me.id, role="owner", added_by=me.id))
        viewdata.audit_entry(s, p.id, "project", p.id, "create", None, {"name": p.name})
        return store.project_json(s, p, [], "owner")


@router.get("/api/projects/{pid}")
def get_project(pid: str):
    with db.session() as s:
        p = common.project(s, pid)
        return store.project_json(s, p, None, access.project_role(s, auth.current.get(), pid))


@router.patch("/api/projects/{pid}")
def update_project(pid: str, v: dict):
    with db.session() as s:
        p = common.project(s, pid, lock=True)
        before, after = {}, {}
        for key, n, req in (("name", 200, True), ("description", 5000, False)):
            if key in v:
                x = text(v, key, n, required=req) or ""
                if x != getattr(p, key):
                    before[key], after[key] = getattr(p, key), x
                    setattr(p, key, x)
        if after:
            p.updated_at = func.now()
            viewdata.audit_entry(s, p.id, "project", p.id, "update", before, after)
        s.flush()
        return store.project_json(s, p, None, access.project_role(s, auth.current.get(), pid))


@router.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str):
    """Hidden at once; rows and files go with the retention cleanup (or stay for recovery)."""
    with db.session() as s:
        p = common.project(s, pid, lock=True, need="owner")
        if any(store.has_active(s, d["id"]) for d in store.list_drawings(s, pid)):
            raise HTTPException(409, "Идёт обработка чертежа: удалите проект после её окончания")
        p.deleted_at = func.now()
        viewdata.audit_entry(s, p.id, "project", p.id, "delete", {"name": p.name}, None)


@router.get("/api/projects/{pid}/audit")
def get_audit(pid: str, limit: int = 100, drawing: str | None = None):
    me = auth.current.get()
    if me is not None and me.share is not None:
        raise HTTPException(403, "Журнал изменений недоступен по ссылке")
    with db.session() as s:
        common.project(s, pid)
        return viewdata.audit(s, pid, limit, drawing)


@router.get("/api/projects/{pid}/events")
async def project_events(pid: str, request: Request):
    """Changes in the project as they happen (Server-Sent Events, see events.py):
    `event: change` with what changed, or `entity: resync` — read everything
    again. Every HEARTBEAT seconds `event: ping` (windows reopen a stream that
    stays silent longer: a proxy may keep a dead one open), and the access is
    checked again (signed out, removed from the project, link or token revoked:
    the stream ends)."""
    def allowed() -> auth.Me | None:
        who = whoami(request)
        with db.session() as s:
            return who if store.get_project(s, pid) is not None and access.project_role(s, who, pid) else None

    me = await run_in_threadpool(allowed)
    if me is None:
        raise HTTPException(404, "Проект не найден")
    q = events.subscribe(pid)

    def visible(ev: dict) -> dict | None:
        if "to_user" in ev:                 # a command to one user's windows (uicontext.py)
            mine = me.share is None and me.id == ev["to_user"]
            return ev if mine else None
        if me.share is None:
            return ev
        # a guest: no names; only the drawings of the link
        drawings = me.share["drawings"]
        changes = [c for c in ev.get("changes", []) if drawings is None or c.get("drawing") in (None, *drawings)]
        return {"project": pid, "changes": changes, "more": ev.get("more", 0)} if "changes" in ev else ev

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), events.HEARTBEAT)
                except TimeoutError:
                    if await run_in_threadpool(allowed) is None:
                        return
                    yield "event: ping\ndata: {}\n\n"          # an event, not a comment: windows watch for it
                    continue
                ev = visible(ev)
                if ev is not None and "changes" not in ev or ev["changes"] or ev.get("more"):
                    yield f"event: change\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        finally:
            events.unsubscribe(pid, q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=STREAM_HEADERS)


@router.post("/api/projects/{pid}/ui-context", status_code=204)
def report_ui_context(pid: str, v: dict):
    """What this window shows ({client, drawing, floor, view, selected, room, proposal, tool}, or
    {client, closed: true}), for the user's agents (uicontext.py)."""
    me = auth.current.get()
    with db.session() as s:
        common.project(s, pid, need="viewer")
        try:
            uicontext.report(s, pid, me.id if me else None, v.get("client"), v)
        except uicontext.ContextError as ex:
            raise HTTPException(400, str(ex))


# ------------------------------------------------ members and share links ---
@router.get("/api/projects/{pid}/members")
def list_members(pid: str):
    with db.session() as s:
        common.project(s, pid)
        return access.members(s, pid)


@router.post("/api/projects/{pid}/members", status_code=201)
def add_member(pid: str, v: dict):
    """{who: login or e-mail, role}: an e-mail of someone who has not signed in yet is an invitation."""
    with db.session() as s:
        common.project(s, pid, lock=True, need="owner")
        m = bad(access.add_member, s, pid, v.get("who") or v.get("login") or v.get("email") or "", v.get("role"))
        viewdata.audit_entry(s, pid, "member", str(m["id"]), "create", None, m)
        return m


@router.patch("/api/projects/{pid}/members/{mid}")
def update_member(pid: str, mid: int, v: dict):
    with db.session() as s:
        common.project(s, pid, lock=True, need="owner")
        m = bad(access.set_member_role, s, pid, mid, v.get("role"))
        viewdata.audit_entry(s, pid, "member", str(mid), "update", None, m)
        return m


@router.delete("/api/projects/{pid}/members/{mid}", status_code=204)
def delete_member(pid: str, mid: int):
    with db.session() as s:
        common.project(s, pid, lock=True, need="owner")
        m = bad(access.remove_member, s, pid, mid)
        viewdata.audit_entry(s, pid, "member", str(mid), "delete", m, None)


@router.get("/api/projects/{pid}/shares")
def list_shares(pid: str):
    with db.session() as s:
        common.project(s, pid, need="owner")
        return access.shares(s, pid)


@router.post("/api/projects/{pid}/shares", status_code=201)
def create_share(pid: str, v: dict, request: Request):
    """{name?, days?, drawings?, layers?} -> the link (its token is shown only now)."""
    with db.session() as s:
        common.project(s, pid, lock=True, need="owner")
        x, token = bad(access.create_share, s, pid, v if isinstance(v, dict) else {})
        viewdata.audit_entry(s, pid, "share", x["id"], "create", None, x)
    return {**x, "token": token, "url": f"{base_url(request)}/#/s/{token}"}


@router.delete("/api/projects/{pid}/shares/{sid}")
def revoke_share(pid: str, sid: str):
    with db.session() as s:
        common.project(s, pid, lock=True, need="owner")
        x = bad(access.revoke_share, s, pid, sid)
        viewdata.audit_entry(s, pid, "share", sid, "revoke", None, x)
        return x
