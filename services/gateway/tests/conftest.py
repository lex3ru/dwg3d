"""The gateway under test: a scratch database, and stand-ins for everything it
talks to — Keycloak's token endpoint and one upstream service — behind its
HTTP client. No real neighbour is needed."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from twin_chassis.testing import ISSUER, Tokens, running, scratch_database, test_settings

from app.config import GatewayConfig
from app.main import SERVICE, build

PUBLIC = "http://twin.test"
UPSTREAM = "http://ping.test"


class _Body(httpx.AsyncByteStream):
    def __init__(self, data: bytes):
        self.data = data

    async def __aiter__(self):
        yield self.data


def reply(status: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    """A response that still has to be read, like one from the network."""
    return httpx.Response(status, headers={"content-type": "application/json", **(headers or {})},
                          stream=_Body(json.dumps(payload).encode()))


class World:
    """What the gateway sees through its HTTP client."""

    def __init__(self, tokens: Tokens):
        self.tokens = tokens
        self.user = {"sub": "user-1", "roles": (), "login": "ivanov", "name": "Иван Иванов"}
        self.access_ttl = 300
        self.refresh_ok = True
        self.keycloak_up = True
        self.upstream_up = True
        self.seen: list[httpx.Request] = []        # requests that reached the upstream service
        self.token_calls: list[dict] = []

    def _tokens(self) -> dict:
        access = self.tokens.make(self.user["sub"], roles=self.user["roles"], login=self.user["login"],
                                  name=self.user["name"], expires_in=self.access_ttl)
        return {"access_token": access, "refresh_token": "refresh-1", "id_token": "id-token-1",
                "expires_in": self.access_ttl}

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(ISSUER):
            if not self.keycloak_up:
                raise httpx.ConnectError("keycloak is down")
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_calls.append(form)
            fresh = form["grant_type"] == "authorization_code" and form.get("code") == "good-code"
            if fresh and form.get("code_verifier"):
                return reply(200, self._tokens())
            if form["grant_type"] == "refresh_token" and self.refresh_ok:
                return reply(200, self._tokens())
            return reply(400, {"error": "invalid_grant"})
        if str(request.url).startswith(UPSTREAM):
            if not self.upstream_up:
                raise httpx.ConnectError("service is down")
            self.seen.append(request)
            if request.url.path == "/healthz":
                return reply(200, {"service": "ping", "ok": True, "db": True, "nats": True})
            if request.url.path.endswith("/missing"):
                return reply(404, {"code": "not_found", "status": 404}, {"content-type": "application/problem+json"})
            echo = {"path": request.url.path, "query": request.url.query.decode(), "body": request.content.decode()}
            status = 201 if request.method == "POST" else 200
            return reply(status, echo, {"x-from-service": "ping", "set-cookie": "leak=1"})
        raise AssertionError(f"unexpected request: {request.url}")


@pytest.fixture(scope="session")
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def world(tokens) -> World:
    return World(tokens)


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


@pytest_asyncio.fixture
async def app(database_url, tokens, world):
    config = GatewayConfig(public_url=PUBLIC, client_secret="s3cret", secret="test-secret", services={"ping": UPSTREAM})
    http = httpx.AsyncClient(transport=httpx.MockTransport(world.handle))
    async with running(build(test_settings(SERVICE, database_url), tokens.verifier(), config, http)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC) as client:
        yield client


async def sign_in(client: httpx.AsyncClient, next: str | None = None) -> httpx.Response:
    """Go through the sign-in as a browser would; returns the final redirect."""
    r = await client.get("/auth/login", params={"next": next} if next else None)
    assert r.status_code == 302
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    return await client.get("/auth/callback", params={"code": "good-code", "state": state})


@pytest_asyncio.fixture
async def signed_in(client):
    r = await sign_in(client)
    assert r.status_code == 302 and r.headers["location"] == "/"
    return client
