"""Sign-in, the session, sign-out."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from twin_chassis.testing import ISSUER

from app.models import sessions

from .conftest import PUBLIC, sign_in


async def test_login_sends_the_browser_to_keycloak(client):
    r = await client.get("/auth/login", params={"next": "/#/buildings"})
    assert r.status_code == 302
    url = urlsplit(r.headers["location"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert r.headers["location"].startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    assert query["client_id"] == "twin" and query["redirect_uri"] == f"{PUBLIC}/auth/callback"
    assert query["code_challenge_method"] == "S256" and query["code_challenge"] and query["state"]
    assert "twin_login" in r.cookies


async def test_sign_in_then_me_then_sign_out(client, app, world):
    assert (await client.get("/api/me")).status_code == 401

    r = await sign_in(client, next="/#/system")
    assert r.status_code == 302 and r.headers["location"] == "/#/system"
    cookie = r.headers["set-cookie"]
    assert "twin_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert world.token_calls[0]["client_secret"] == "s3cret"

    me = (await client.get("/api/me")).json()
    assert me["user"] == {"sub": "user-1", "login": "ivanov", "name": "Иван Иванов", "email": "ivanov@example.test",
                          "roles": [], "is_admin": False}

    out = await client.post("/auth/logout")
    assert out.status_code == 200
    url = out.json()["url"]
    assert url.startswith(f"{ISSUER}/protocol/openid-connect/logout?") and "id-token-1" in url
    assert (await client.get("/api/me")).status_code == 401
    async with app.state.db.begin() as session:
        assert (await session.execute(select(sessions))).all() == []


async def test_tokens_are_not_stored_in_the_clear(signed_in, app):
    async with app.state.db.begin() as session:
        row = (await session.execute(select(sessions))).one()
    cookie = signed_in.cookies["twin_session"]
    assert cookie not in row.token_hash and not row.access_token.startswith("ey") and row.refresh_token != "refresh-1"


async def test_wrong_state_or_code_does_not_sign_in(client):
    await client.get("/auth/login")
    r = await client.get("/auth/callback", params={"code": "good-code", "state": "forged"})
    assert r.status_code == 302 and r.headers["location"] == "/?signin=failed"
    assert (await client.get("/api/me")).status_code == 401

    r = await client.get("/auth/login")
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = await client.get("/auth/callback", params={"code": "bad-code", "state": state})
    assert r.headers["location"] == "/?signin=failed"
    assert (await client.get("/api/me")).status_code == 401


async def test_return_address_must_be_local(client):
    for evil in ("https://evil.test/", "//evil.test/", "/\\evil.test"):
        r = await sign_in(client, next=evil)
        assert r.headers["location"] == "/"


async def test_keycloak_down_is_503_not_500(client, world):
    r = await client.get("/auth/login")
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    world.keycloak_up = False
    r = await client.get("/auth/callback", params={"code": "good-code", "state": state})
    assert r.status_code == 503 and r.json()["code"] == "auth_unavailable"


async def test_expiring_token_is_refreshed(client, world):
    world.access_ttl = 5                      # about to expire as soon as it is issued
    await sign_in(client)
    world.access_ttl = 300
    assert (await client.get("/api/me")).status_code == 200
    assert [c["grant_type"] for c in world.token_calls] == ["authorization_code", "refresh_token"]
    assert (await client.get("/api/me")).status_code == 200          # the new token is good: no second refresh
    assert len(world.token_calls) == 2


async def test_refused_refresh_ends_the_session(client, world):
    world.access_ttl = 5
    await sign_in(client)
    world.refresh_ok = False
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/me")).status_code == 401
