"""The people service under test: a scratch database, tokens signed here, and a
stand-in for the access service saying who administers buildings."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from twin_chassis.client import ServiceClient
from twin_chassis.testing import ISSUER, Tokens, running, scratch_database, test_settings

from app.main import SERVICE, build

API = "/api/people/v1"
ACCESS = "http://access.test"
BUILDING = "0192f000-0000-7000-8000-00000000000b"


class Access:
    """Answers GET /me/scopes: accounts listed in `admins` administer a building."""

    def __init__(self, tokens: Tokens):
        self.tokens, self.admins, self.up = tokens, {"boss"}, True

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(ACCESS) and not str(request.url).startswith(ISSUER)
        if not self.up:
            raise httpx.ConnectError("access is down")
        me = self.tokens.verifier().identity(request.headers["authorization"].removeprefix("Bearer "))
        grants = [{"role": "admin", "scope": {"kind": "building", "id": BUILDING}, "building_id": BUILDING}]
        return httpx.Response(200, json={"admin": False, "person_id": None, "buildings": [],
                                         "grants": grants if me.sub in self.admins else []})


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
    async with running(build(settings, tokens.verifier(), ServiceClient(settings, {"access": ACCESS}, http))) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
