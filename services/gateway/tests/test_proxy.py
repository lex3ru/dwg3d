"""Requests passed on to services."""
from __future__ import annotations

import asyncio
import time

from app import proxy

from .conftest import PUBLIC, UPSTREAM


async def test_request_goes_on_with_the_users_token(signed_in, world, tokens):
    r = await signed_in.post("/api/ping/v1/notes?x=1", json={"text": "привет"}, headers={"X-Request-ID": "req-7"})
    assert r.status_code == 201
    assert r.json() == {"path": "/api/ping/v1/notes", "query": "x=1", "body": '{"text":"привет"}'}
    assert r.headers["x-from-service"] == "ping" and "set-cookie" not in r.headers
    assert r.headers["x-request-id"] == "req-7"

    seen = world.seen[-1]
    assert str(seen.url) == f"{UPSTREAM}/api/ping/v1/notes?x=1"
    assert seen.headers["x-request-id"] == "req-7" and "cookie" not in seen.headers
    assert tokens.verifier().identity(seen.headers["authorization"].removeprefix("Bearer ")).sub == "user-1"


async def test_service_answers_pass_through(signed_in):
    r = await signed_in.get("/api/ping/v1/missing")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


async def test_not_signed_in_is_401(client, world):
    r = await client.get("/api/ping/v1/notes")
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    assert r.headers["content-type"].startswith("application/problem+json")
    assert world.seen == []


async def test_own_bearer_token_passes_without_a_session(client, world, tokens):
    r = await client.get("/api/ping/v1/notes", headers=tokens.bearer("robot-1"))
    assert r.status_code == 200
    assert tokens.verifier().identity(world.seen[-1].headers["authorization"].removeprefix("Bearer ")).sub == "robot-1"
    assert (await client.get("/api/ping/v1/notes", headers={"Authorization": "Bearer forged"})).status_code == 401


async def test_unknown_service_is_404(signed_in):
    r = await signed_in.get("/api/nosuch/v1/things")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


async def test_service_down_is_503(signed_in, world, monkeypatch):
    monkeypatch.setattr(proxy, "RETRY_READS_FOR", 0.6)
    world.upstream_up = False
    r = await signed_in.get("/api/ping/v1/notes")
    assert r.status_code == 503
    assert r.json()["code"] == "service_unavailable" and r.json()["service"] == "ping"


async def test_a_read_waits_for_a_service_being_updated(signed_in, world, monkeypatch):
    monkeypatch.setattr(proxy, "RETRY_READS_FOR", 5.0)
    world.upstream_up = False

    async def back():
        await asyncio.sleep(0.7)
        world.upstream_up = True

    task = asyncio.create_task(back())
    started = time.monotonic()
    assert (await signed_in.get("/api/ping/v1/notes")).status_code == 200
    assert 0.5 < time.monotonic() - started < 3
    await task
    # a change is not sent twice: refused at once
    world.upstream_up = False
    started = time.monotonic()
    r = await signed_in.post("/api/ping/v1/notes", json={"text": "x"}, headers={"Origin": PUBLIC})
    assert r.status_code == 503 and time.monotonic() - started < 0.5


async def test_changing_request_from_a_foreign_page_is_refused(signed_in, world):
    r = await signed_in.post("/api/ping/v1/notes", json={"text": "x"}, headers={"Origin": "https://evil.test"})
    assert r.status_code == 403 and r.json()["code"] == "foreign_origin"
    assert world.seen == []
    ours = await signed_in.post("/api/ping/v1/notes", json={"text": "x"}, headers={"Origin": PUBLIC})
    assert ours.status_code == 201
    assert (await signed_in.get("/api/ping/v1/notes", headers={"Origin": "https://evil.test"})).status_code == 200


async def test_system_status_is_for_admins(signed_in, client, world, tokens):
    assert (await signed_in.get("/api/system/status")).status_code == 403

    r = await client.get("/api/system/status", headers=tokens.admin())
    assert r.status_code == 200
    services = {s["name"]: s for s in r.json()["services"]}
    assert services["gateway"]["ok"] and services["gateway"]["db"] is True
    assert services["ping"] == {"name": "ping", "ok": True, "db": True, "nats": True, "ms": services["ping"]["ms"]}

    world.upstream_up = False
    r = await client.get("/api/system/status", headers=tokens.admin())
    assert {s["name"]: s["ok"] for s in r.json()["services"]} == {"gateway": True, "ping": False}
