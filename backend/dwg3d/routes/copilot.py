"""The built-in copilot (an external OpenAI-compatible model, see copilot.py) and its proposals."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from .. import access, auth, copilot, db, proposals, store, viewdata
from ..models import Proposal
from . import common
from .common import STREAM_HEADERS, admin, bad, log

router = APIRouter()


@router.get("/api/copilot/settings")
def get_copilot_settings():
    """The copilot's model endpoint and limits (admins); the key only as «…abcd»."""
    admin()
    with db.session() as s:
        return copilot.settings_json(copilot.load_settings(s))


@router.put("/api/copilot/settings")
def put_copilot_settings(v: dict):
    """{enabled?, base_url?, api_key? ("" removes), model?, daily_limit?, max_steps?, temperature?}"""
    admin()
    with db.session() as s:
        try:
            return copilot.settings_json(copilot.save_settings(s, v))
        except ValueError as ex:
            raise HTTPException(400, str(ex))


@router.post("/api/copilot/settings/check")
async def check_copilot_settings(v: dict | None = None):
    """Try the endpoint with the saved settings, or with these ({base_url, api_key?, model}) before saving."""
    admin()

    def cfg():
        with db.session() as s:
            c = copilot.load_settings(s)
        for k in ("base_url", "model", "api_key"):
            if (v or {}).get(k):
                c[k] = str(v[k]).strip().rstrip("/").removesuffix("/chat/completions") if k == "base_url" else str(v[k]).strip()
        return c
    try:
        return {"ok": True, **await copilot.check(await run_in_threadpool(cfg))}
    except copilot.CopilotError as ex:
        return {"ok": False, "error": str(ex)}


@router.get("/api/copilot/status")
def copilot_status():
    """Whether the copilot is on (the viewer shows its button), and the user's requests today."""
    me = auth.current.get()
    with db.session() as s:
        cfg = copilot.load_settings(s)
        used = copilot.requests_today(s, me) if me is not None else 0
    return {"enabled": copilot.ready(cfg), "model": cfg["model"] if copilot.ready(cfg) else None,
            "daily_limit": cfg["daily_limit"], "used_today": used}


def _copilot_user(s, pid: str) -> tuple[auth.Me, str]:
    me = auth.current.get()
    if me is None or me.share is not None:
        raise HTTPException(403, "Копилот доступен участникам проекта")
    common.project(s, pid, need="viewer")
    return me, access.project_role(s, me, pid)


def _line(ev: dict) -> str:
    return json.dumps(ev, ensure_ascii=False, default=str) + "\n"


@router.post("/api/projects/{pid}/copilot")
async def copilot_chat(pid: str, v: dict):
    """{message, chat?, ui?} -> the answer as it comes: NDJSON events (copilot.run)."""
    def who():
        with db.session() as s:
            return _copilot_user(s, pid)
    me, role = await run_in_threadpool(who)

    async def stream():
        try:
            async for ev in copilot.run(pid, me, role, v.get("chat"), v.get("message") or "", v.get("ui")):
                yield _line(ev)
        except copilot.CopilotError as ex:
            yield _line({"type": "error", "message": str(ex)})
        except LookupError:
            yield _line({"type": "error", "message": "Чат не найден"})
        except Exception:
            log.exception("copilot failed")
            yield _line({"type": "error", "message": "Сбой копилота: подробности в журнале сервера"})

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers=STREAM_HEADERS)


@router.get("/api/projects/{pid}/copilot/chats")
def list_copilot_chats(pid: str):
    with db.session() as s:
        me, _ = _copilot_user(s, pid)
        return copilot.chats(s, pid, me)


@router.get("/api/projects/{pid}/copilot/chats/{cid}")
def get_copilot_chat(pid: str, cid: str):
    with db.session() as s:
        me, _ = _copilot_user(s, pid)
        c = bad(copilot.own_chat, s, cid, me)
        if c.project_id != pid:
            raise HTTPException(404, "Не найдено")
        return {"id": c.id, "title": c.title, "items": copilot.display(c.messages)}


@router.delete("/api/projects/{pid}/copilot/chats/{cid}", status_code=204)
def delete_copilot_chat(pid: str, cid: str):
    with db.session() as s:
        me, _ = _copilot_user(s, pid)
        c = bad(copilot.own_chat, s, cid, me)
        if c.project_id == pid:
            s.delete(c)


# --------------------------------------------------------------- proposals ---
@router.get("/api/projects/{pid}/proposals")
def list_proposals(pid: str, status: str | None = None, drawing: str | None = None, limit: int = 100):
    """Proposals of the copilot (newest first; ?status=open, ?drawing=)."""
    if status is not None and status not in proposals.STATUSES:
        raise HTTPException(400, f"status: {', '.join(proposals.STATUSES)}")
    with db.session() as s:
        common.project(s, pid)
        return proposals.listing(s, pid, status, drawing, limit=limit)


def _proposal(s, prid: str, need: str | None = None) -> Proposal:
    p = s.scalar(select(Proposal).where(Proposal.id == prid).with_for_update())
    if p is None or store.get_drawing(s, p.drawing_id) is None:
        raise HTTPException(404, "Предложение не найдено")
    access.check(s, p.project_id, need, "Предложение не найдено")
    return p


def _audit(s, p: Proposal, action: str, after: dict):
    viewdata.audit_entry(s, p.project_id, "proposal", p.id, action, None, after, p.drawing_id)


@router.get("/api/proposals/{prid}")
def get_proposal(prid: str):
    """The proposal and what it would do now (preview: created, updated {before, after},
    deleted rows); one that no longer applies turns stale here."""
    with db.session() as s:
        p = _proposal(s, prid, need="viewer")
        was = p.status
        pv = proposals.preview(s, p)
        if p.status != was:
            _audit(s, p, "stale", {"reason": p.reason})
        return {**proposals.one_json(s, p), "ops": p.ops, "preview": pv}


@router.post("/api/proposals/{prid}/apply")
def apply_proposal(prid: str):
    """Apply as the current user's change (an editor); 409 when it no longer applies (it turns stale)."""
    with db.session() as s:
        p = _proposal(s, prid, need="editor")
        try:
            res = proposals.apply(s, p)
        except viewdata.Conflict as ex:
            _audit(s, p, "stale", {"reason": p.reason})
            out = JSONResponse({"detail": str(ex), "proposal": proposals.one_json(s, p)}, status_code=409)
        else:
            _audit(s, p, "apply", {"summary": p.summary})
            return {"proposal": proposals.one_json(s, p), **res}
    return out      # after the session: the stale status is committed


@router.post("/api/proposals/{prid}/reject")
def reject_proposal(prid: str, v: dict | None = None):
    """{reason?}: the copilot sees it with proposal_status."""
    with db.session() as s:
        p = _proposal(s, prid, need="editor")
        reason = (v or {}).get("reason")
        proposals.reject(s, p, reason if isinstance(reason, str) else None)
        _audit(s, p, "reject", {"reason": p.reason})
        return proposals.one_json(s, p)
