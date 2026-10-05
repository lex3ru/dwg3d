"""Events: published after the change, handled once, not lost while NATS is away."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy import func, select
from twin_chassis import emit
from twin_chassis.db import outbox
from twin_chassis.events import envelope
from twin_chassis.testing import running, test_settings

from app.main import SERVICE, build

API = "/api/__service__/v1"


async def wait_for(check, within: float = 8.0):
    """Poll `check()` until it returns something truthy."""
    deadline = asyncio.get_running_loop().time() + within
    while True:
        if value := await check():
            return value
        assert asyncio.get_running_loop().time() < deadline, "не дождались"
        await asyncio.sleep(0.1)


async def unpublished(app) -> int:
    async with app.state.db.begin() as session:
        return (await session.execute(
            select(func.count()).select_from(outbox).where(outbox.c.published_at.is_(None)))).scalar_one()


async def test_event_reaches_the_handler(client, app, tokens):
    me = tokens.bearer()
    note = (await client.post(f"{API}/notes", json={"text": "эхо"}, headers=me)).json()

    async def echoed():
        n = (await client.get(f"{API}/notes/{note['id']}", headers=me)).json()
        return n if n["echoed_at"] else None

    assert (await wait_for(echoed))["echoes"] == 1
    assert await unpublished(app) == 0


async def test_event_is_stored_with_the_change(client, app, tokens):
    note = (await client.post(f"{API}/notes", json={"text": "событие"}, headers=tokens.bearer("user-7"))).json()
    async with app.state.db.begin() as session:
        event = (await session.execute(select(outbox.c.payload))).scalar_one()
    assert event["type"] == "__service__.note.created"
    assert event["subject"] == {"kind": "note", "id": note["id"]}
    assert event["actor"] == {"kind": "user", "id": "user-7"}
    assert event["data"] == {"text": "событие"}


async def test_redelivered_event_is_handled_once(client, app, tokens):
    me = tokens.bearer()
    note = (await client.post(f"{API}/notes", json={"text": "дважды"}, headers=me)).json()
    await wait_for(lambda: _echoes(client, note, me))

    event = envelope("__service__.note.created", ("note", note["id"]), {"text": "дважды"})
    assert await app.state.bus.handle("echo", event) is True       # an event not seen before
    assert await app.state.bus.handle("echo", event) is False      # the same one again
    assert await app.state.bus.handle("echo", event) is False
    assert (await client.get(f"{API}/notes/{note['id']}", headers=me)).json()["echoes"] == 2


async def _echoes(client, note, headers):
    return (await client.get(f"{API}/notes/{note['id']}", headers=headers)).json()["echoes"]


async def test_event_not_matching_the_contract_is_refused(app):
    with pytest.raises(ValueError, match="не соответствует контракту"):
        async with app.state.db.begin() as session:
            await emit(session, "__service__.note.created", ("note", "1"), {"text": 5})
    with pytest.raises(RuntimeError, match="Нет контракта"):
        async with app.state.db.begin() as session:
            await emit(session, "__service__.note.vanished", ("note", "1"), {})
    assert await unpublished(app) == 0


async def test_works_while_nats_is_away_and_catches_up(database_url, tokens):
    # NATS unreachable: the request succeeds, the event waits in the outbox
    offline = test_settings(SERVICE, database_url, nats_url="nats://127.0.0.1:1")
    async with running(build(offline, tokens.verifier())) as app:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"{API}/notes", json={"text": "без шины"}, headers=tokens.bearer())
            assert r.status_code == 201
            note = r.json()
            assert (await client.get("/healthz")).json() == {"service": SERVICE, "ok": True, "db": True, "nats": False}
        await asyncio.sleep(0.5)
        assert await unpublished(app) == 1

    # NATS is back (same database): the waiting event is published and handled
    async with running(build(test_settings(SERVICE, database_url), tokens.verifier())) as app:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await wait_for(lambda: _echoes(client, note, tokens.bearer()))
        assert await unpublished(app) == 0
