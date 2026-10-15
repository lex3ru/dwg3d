"""A guest by a link: /s/<token> opens a look of its own, renewed while the link is good."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest_asyncio
from sqlalchemy import select, update
from twin_chassis.testing import running, test_settings

from app.config import GatewayConfig
from app.main import SERVICE, build
from app.models import guest_sessions, sessions

from .conftest import PUBLIC, UPSTREAM, sign_in

B, F, R = (f"0192f000-0000-7000-8000-00000000000{n}" for n in range(1, 4))
LINK = "Zq3xK9mW2pL7vT4nR8sY1cB6dF0hJ5gA"
SERVICES = {name: UPSTREAM for name in ("ping", "access", "buildings", "assets", "people")}
UNTIL = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)


@pytest_asyncio.fixture
async def app(database_url, tokens, world):
    config = GatewayConfig(public_url=PUBLIC, client_secret="s3cret", secret="test-secret", services=SERVICES)
    http = httpx.AsyncClient(transport=httpx.MockTransport(world.handle))
    world.links[LINK] = {"share": "share-1", "building_id": B, "scope": {"kind": "floor", "id": F}, "floor_id": F,
                         "expires_at": UNTIL.isoformat().replace("+00:00", "Z")}
    world.answers.update({
        ("GET", f"/api/buildings/v1/buildings/{B}"): {"id": B, "name": "Корпус", "address": ""},
        ("GET", "/api/people/v1/me"): {"person": None, "reason": "unknown"},
        ("GET", "/api/access/v1/me/scopes"): {"admin": False, "person_id": None, "buildings": [], "grants": []},
    })
    async with running(build(test_settings(SERVICE, database_url), tokens.verifier(), config, http)) as app:
        yield app


async def test_a_link_opens_a_guest_look(client, app, world):
    r = await client.get(f"/s/{LINK}")
    assert r.status_code == 302 and r.headers["location"] == "/#/g"
    cookie = r.headers["set-cookie"]
    assert "twin_guest=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "twin_session" not in cookie
    assert world.opened == [{"token": LINK, "renew": False, "address": "127.0.0.1"}]

    me = (await client.get("/api/me")).json()
    assert me == {"kind": "guest", "name": "Гость",
                  "guest": {"building_id": B, "building_name": "Корпус", "scope": {"kind": "floor", "id": F},
                            "floor_id": F, "expires_at": UNTIL.isoformat().replace("+00:00", "Z")}}
    # neither the link nor the guest token is kept in the clear
    async with app.state.db.begin() as session:
        row = (await session.execute(select(guest_sessions))).one()
    assert LINK not in row.link and not row.access_token.startswith("ey")
    assert row.token_hash != client.cookies["twin_guest"]

    # the buildings service away: the name is not known, the look goes on
    del world.answers[("GET", f"/api/buildings/v1/buildings/{B}")]
    world.answers[("GET", f"/api/buildings/v1/buildings/{B}")] = lambda r: (503, {"code": "down"})
    assert (await client.get("/api/me")).json()["guest"]["building_name"] is None


async def test_a_bad_link_or_no_access_service(client, world):
    r = await client.get("/s/Unknown-link-0000000000")
    assert r.status_code == 302 and r.headers["location"] == "/#/g?invalid=1" and "set-cookie" not in r.headers
    asked = len(world.opened)
    r = await client.get("/s/no!such")
    assert r.headers["location"] == "/#/g?invalid=1" and len(world.opened) == asked      # not even asked
    world.access_up = False
    r = await client.get(f"/s/{LINK}")
    assert r.status_code == 302 and r.headers["location"] == "/#/g?unavailable=1"
    assert (await client.get("/api/me")).status_code == 401


async def test_the_guest_token_goes_to_the_services(client, world, tokens):
    await client.get(f"/s/{LINK}")
    r = await client.get("/api/ping/v1/notes")
    assert r.status_code == 200
    passed = tokens.verifier().identity(world.seen[-1].headers["authorization"].removeprefix("Bearer "))
    assert passed.kind == "guest" and passed.sub == "guest:share-1" and passed.guest == ("floor", F, B, F)
    # a changing request with the guest cookie is checked for its page like any other
    r = await client.post("/api/ping/v1/notes", json={"text": "x"}, headers={"Origin": "https://evil.test"})
    assert r.status_code == 403 and r.json()["code"] == "foreign_origin"


async def test_the_guest_token_is_renewed_by_the_link(client, world):
    world.guest_ttl = 30                     # about to expire as soon as it is issued
    await client.get(f"/s/{LINK}")
    world.guest_ttl = 600
    assert (await client.get("/api/ping/v1/notes")).status_code == 200
    assert [o["renew"] for o in world.opened] == [False, True] and world.opened[1]["token"] == LINK
    assert (await client.get("/api/ping/v1/notes")).status_code == 200    # the new token is good: no second renewal
    assert len(world.opened) == 2


async def test_a_link_revoked_while_looking_ends_the_look(client, world):
    world.guest_ttl = 30
    await client.get(f"/s/{LINK}")
    del world.links[LINK]
    r = await client.get("/api/ping/v1/notes")
    assert r.status_code == 401 and r.json()["code"] == "guest_ended"
    assert r.json()["detail"] == "Просмотр по ссылке закончился: ссылка отозвана или истекла"
    assert "twin_guest=" in r.headers["set-cookie"] and "twin_guest" not in client.cookies
    # the cookie is gone with it: from now on this browser is no one
    assert (await client.get("/api/me")).json()["code"] == "unauthenticated"


async def test_a_look_past_the_links_date_is_over(client, app):
    await client.get(f"/s/{LINK}")
    async with app.state.db.begin() as session:
        await session.execute(update(guest_sessions).values(link_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    r = await client.get("/api/me")
    assert r.status_code == 401 and r.json()["code"] == "guest_ended"
    async with app.state.db.begin() as session:
        assert (await session.execute(select(guest_sessions))).all() == []


async def test_the_guest_cookie_wins_and_leaving_keeps_the_users_session(client, app, world):
    await sign_in(client)
    assert (await client.get("/api/me")).json()["kind"] == "user"
    await client.get(f"/s/{LINK}")
    assert (await client.get("/api/me")).json()["kind"] == "guest"

    assert (await client.post("/auth/logout", headers={"Origin": "https://evil.test"})).status_code == 403
    out = await client.post("/auth/logout", headers={"Origin": PUBLIC})
    assert out.status_code == 200 and out.json() == {"url": "/"}
    assert "twin_guest" not in client.cookies and "twin_session" in client.cookies
    me = (await client.get("/api/me")).json()
    assert me["kind"] == "user" and me["user"]["login"] == "ivanov"
    async with app.state.db.begin() as session:
        assert (await session.execute(select(guest_sessions))).all() == []
        assert len((await session.execute(select(sessions))).all()) == 1


async def test_a_guest_leaves_even_an_ended_look(client, world):
    world.guest_ttl = 30
    await client.get(f"/s/{LINK}")
    del world.links[LINK]
    out = await client.post("/auth/logout")
    assert out.status_code == 200 and out.json() == {"url": "/"} and "twin_guest" not in client.cookies


async def test_what_the_gateway_gathers_itself_is_not_for_a_guest(client, world):
    await client.get(f"/s/{LINK}")
    seen = len(world.seen)
    refused = [await client.get("/api/views/cabinet", params={"building_id": B}),
               await client.get("/api/reports/assets.xlsx", params={"building_id": B}),
               await client.get(f"/api/reports/rooms/{R}/sheet.pdf"),
               await client.post(f"/api/reports/buildings/{B}/drawing", json={"drawing_id": R}),
               await client.get("/api/system/status"),
               await client.get("/api/stream"),
               await client.get("/q/A7K2M9Q4ZX")]
    for r in refused:
        assert r.status_code == 403, r.request.url
        assert r.json()["code"] == "guest" and r.json()["detail"] == "Гостю по ссылке это недоступно"
    assert len(world.seen) == seen
