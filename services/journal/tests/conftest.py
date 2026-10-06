"""The journal under test: a scratch database, tokens signed here, a stand-in for the
access service (who has which grants); events are played straight into the handler."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from twin_chassis.client import ServiceClient
from twin_chassis.events import envelope
from twin_chassis.testing import ISSUER, Tokens, running, scratch_database, test_settings

from app.main import SERVICE, build

API = "/api/journal/v1"
ACCESS = "http://access.test"
B, F, R1, R2, A1, P1, P2 = (f"0192f000-0000-7000-8000-00000000000{n}" for n in range(1, 8))


class Access:
    def __init__(self, tokens: Tokens):
        self.tokens = tokens
        self.grants: dict[str, list[dict]] = {}
        self.persons: dict[str, str] = {}

    def person(self, sub: str, person_id: str, *grants: tuple[str, str, str]) -> dict[str, str]:
        self.persons[sub] = person_id
        self.grants[sub] = [{"role": r, "scope": {"kind": k, "id": i}, "building_id": B} for r, k, i in grants]
        return self.tokens.bearer(sub)

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(ACCESS) and not str(request.url).startswith(ISSUER)
        me = self.tokens.verifier().identity(request.headers["authorization"].removeprefix("Bearer "))
        return httpx.Response(200, json={"admin": False, "person_id": self.persons.get(me.sub),
                                         "grants": self.grants.get(me.sub, []), "buildings": [B]})


@pytest.fixture(scope="session")
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def access(tokens) -> Access:
    return Access(tokens)


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


@pytest_asyncio.fixture
async def app(database_url, tokens, access):
    settings = test_settings(SERVICE, database_url)
    http = httpx.AsyncClient(transport=httpx.MockTransport(access.handle))
    client = ServiceClient(settings, {"access": ACCESS}, http)
    async with running(build(settings, tokens.verifier(), client, keep_days=30)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def happened(app, type_: str, subject: tuple[str, str], data: dict | None = None, *, actor: dict | None = None,
                   **scope) -> dict:
    """An event arrives from the bus (the handler runs as the bus would run it)."""
    event = envelope(type_, subject, data or {}, actor=actor or {"kind": "service", "id": "test"}, **scope)
    await app.state.bus.handle("journal", event)
    return event
