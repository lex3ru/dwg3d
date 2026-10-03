"""Changes in a project as they happen, for the open windows (SSE).

Every change recorded in the audit log (viewdata.audit_entry) is also sent
with PostgreSQL NOTIFY in the same transaction: it goes out only when the
transaction commits, and reaches every API process. Each process has one
thread LISTENing on the channel and hands the events to the event streams
of the project open in it (GET /api/projects/{id}/events).

The changes of one transaction go as one event per project, small (NOTIFY
payloads are limited to 8000 bytes): what changed, not how —
  {"project", "user_id", "actor", "agent",
   "changes": [{"drawing", "entity", "id", "action"}], "more": <changes left out>}
the windows read the changed rows themselves, with their own access.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict

from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from . import db

log = logging.getLogger("dwg3d.events")
CHANNEL = "dwg3d_events"
HEARTBEAT = 25.0                # seconds between keep-alive comments (and access re-checks) of a stream
QUEUE = 1000                    # events waiting for a slow stream; more and it is closed

_subs: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = defaultdict(set)
_lock = threading.Lock()
_listener: threading.Thread | None = None
ready = threading.Event()       # the listener is LISTENing


MAX_PAYLOAD = 7500


def publish(s: Session, project: str, change: dict, who: dict):
    """A change to tell when the session's transaction commits (dropped on rollback).
    `who`: user_id, actor, agent of the change."""
    s.info.setdefault("dwg3d_events", {}).setdefault(project, ({**who, "project": project}, []))[1].append(change)


@sa_event.listens_for(Session, "before_commit")
def _send(s: Session):
    """One NOTIFY per project with the transaction's changes (delivered on commit)."""
    pending = s.info.pop("dwg3d_events", None)
    for head, changes in (pending or {}).values():
        ev = {**head, "changes": changes}
        body = json.dumps(ev, ensure_ascii=False, default=str)
        while len(body.encode()) > MAX_PAYLOAD and ev["changes"]:
            keep = len(ev["changes"]) // 2
            ev = {**head, "changes": changes[:keep], "more": len(changes) - keep}
            body = json.dumps(ev, ensure_ascii=False, default=str)
        s.execute(select(func.pg_notify(CHANNEL, body)))


@sa_event.listens_for(Session, "after_rollback")
def _drop(s: Session):
    s.info.pop("dwg3d_events", None)


# ---------------------------------------------------------- subscribers ---
def subscribe(pid: str) -> asyncio.Queue:
    """A queue of the project's events for a stream running in the current event loop."""
    q: asyncio.Queue = asyncio.Queue(QUEUE)
    with _lock:
        _subs[pid].add((asyncio.get_running_loop(), q))
    _start()
    return q


def unsubscribe(pid: str, q: asyncio.Queue):
    with _lock:
        _subs[pid] = {x for x in _subs[pid] if x[1] is not q}
        if not _subs[pid]:
            del _subs[pid]


RESYNC = {"entity": "resync"}     # events were lost: the window reads everything again


def _put(q: asyncio.Queue, event: dict):
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:           # the stream is not read: drop what waits, tell it to start over
        while not q.empty():
            q.get_nowait()
        q.put_nowait(RESYNC)


def dispatch(event: dict, everyone: bool = False):
    """Hand an event to the streams of its project, or of all projects (from any thread)."""
    with _lock:
        targets = [x for subs in _subs.values() for x in subs] if everyone \
            else list(_subs.get(event.get("project") or "", ()))
    for loop, q in targets:
        try:
            loop.call_soon_threadsafe(_put, q, event)
        except RuntimeError:            # the loop is closed: the stream is gone
            pass


# -------------------------------------------------------------- listener ---
def _conninfo() -> str:
    return make_url(db.database_url()).set(drivername="postgresql").render_as_string(hide_password=False)


def _listen():
    import psycopg

    delay, first = 1.0, True
    while True:
        try:
            with psycopg.connect(_conninfo(), autocommit=True) as conn:
                conn.execute(f"LISTEN {CHANNEL}")
                ready.set()
                delay = 1.0
                log.info("listening for changes (%s)", CHANNEL)
                if not first:                   # changes made while away are not coming
                    dispatch(RESYNC, everyone=True)
                first = False
                while True:
                    for n in conn.notifies(timeout=30):
                        try:
                            dispatch(json.loads(n.payload))
                        except ValueError:
                            log.warning("bad event payload: %.200s", n.payload)
                    conn.execute("SELECT 1")            # notice a dead connection
        except Exception:
            ready.clear()
            log.warning("event listener lost the database; retrying in %.0fs", delay, exc_info=True)
            time.sleep(delay)
            delay = min(delay * 2, 30.0)


def _start():
    """Start this process's listener (once, on the first stream)."""
    global _listener
    with _lock:
        if _listener is None:
            _listener = threading.Thread(target=_listen, name="dwg3d-events", daemon=True)
            _listener.start()
