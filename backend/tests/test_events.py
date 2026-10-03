"""Changes as they happen: NOTIFY on commit, one event per transaction, the SSE stream."""
import asyncio
import json
import threading
import time

import httpx
import pytest

from sqlalchemy import text

from dwg3d import auth, db, events, viewdata
from test_auth import api, kc, sign_in  # noqa: F401  (fixtures)
from test_tokens import _setup


def _collect(pid: str, act, wait: float = 3.0) -> list[dict]:
    """Events of project `pid` that arrive while `act()` runs in another thread."""
    async def run():
        q = events.subscribe(pid)
        try:
            assert await asyncio.to_thread(events.ready.wait, 10), "listener not ready"
            await asyncio.to_thread(act)
            got = []
            try:
                while True:
                    got.append(await asyncio.wait_for(q.get(), wait if not got else 0.5))
            except TimeoutError:
                return got
        finally:
            events.unsubscribe(pid, q)
    return asyncio.run(run())


def _audit(n: int, pid: str = "evproj", fail: bool = False):
    def act():
        token = auth.current.set(auth.Me(None, "olga", "Ольга", "user", agent={"id": "t1", "name": "Claude", "project_id": pid, "mode": "write"}))
        try:
            with db.session() as s:
                for i in range(n):
                    viewdata.audit_entry(s, pid, "object", f"o{i}", "update", None, None, "d1")
                if fail:
                    raise RuntimeError("rollback")
        except RuntimeError:
            pass
        finally:
            auth.current.reset(token)
    return act


def test_one_event_per_transaction(pg):
    got = _collect("evproj", _audit(3))
    assert len(got) == 1
    ev = got[0]
    assert ev["project"] == "evproj" and ev["user_id"] is None and ev["agent"] == "Claude"
    assert ev["actor"] == "olga · агент «Claude»"
    assert [c["id"] for c in ev["changes"]] == ["o0", "o1", "o2"] and ev["changes"][0]["drawing"] == "d1"


def test_rolled_back_changes_are_not_told(pg):
    assert _collect("evproj", _audit(2, fail=True), wait=1.0) == []


def test_big_transactions_are_cut(pg):
    ev = _collect("evproj", _audit(2000))[0]
    assert ev["more"] > 0 and len(ev["changes"]) + ev["more"] == 2000
    assert len(json.dumps(ev, ensure_ascii=False).encode()) <= events.MAX_PAYLOAD


def test_other_projects_are_not_told(pg):
    assert _collect("evproj", _audit(1, pid="another"), wait=1.0) == []


@pytest.fixture
def live(api):  # noqa: F811
    """The API served by a real uvicorn (TestClient buffers whole bodies: no streams)."""
    import socket

    import uvicorn

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def test_sse_stream(kc, api, live, monkeypatch):  # noqa: F811
    owner, editor, viewer, pid, layer = _setup(api, kc)
    monkeypatch.setattr(events, "HEARTBEAT", 0.5)
    cookie = {auth.COOKIE: viewer.cookies.get(auth.COOKIE)}
    with httpx.Client(base_url=live, timeout=10) as h:
        assert h.get(f"/api/projects/{pid}/events").status_code == 401
        stranger = sign_in(api, kc, "ev-stranger")
        assert h.get(f"/api/projects/{pid}/events", cookies={auth.COOKIE: stranger.cookies.get(auth.COOKIE)}).status_code == 404
        with h.stream("GET", f"/api/projects/{pid}/events", cookies=cookie) as r:
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
            lines = r.iter_lines()
            assert next(lines).startswith("retry:")
            assert events.ready.wait(10)
            editor.patch(f"/api/projects/{pid}/layers/{layer}", json={"name": "Мебель 2"})
            got = []
            for line in lines:
                got.append(line)
                if line.startswith("data:"):
                    break
            # removed from the project: the open stream ends at the next heartbeat
            with db.session() as s:
                s.execute(text("DELETE FROM project_members WHERE project_id = :p AND user_id = "
                               "(SELECT id FROM users WHERE login = 'tok-viewer')"), {"p": pid})
            t0 = time.monotonic()
            rest = list(lines)
            assert time.monotonic() - t0 < 5 and "event: change" not in rest
        assert "event: ping" in got or "event: change" in got
        data = json.loads(got[-1][5:])
        assert data["project"] == pid and data["actor"] == "tok-editor"
        assert data["changes"] == [{"drawing": None, "entity": "layer", "id": layer, "action": "update"}]

        with h.stream("GET", f"/api/projects/{pid}/events", cookies=cookie) as r:
            assert r.status_code == 404
