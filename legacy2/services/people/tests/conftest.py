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
BUILDINGS = "http://buildings.test"
ASSETS = "http://assets.test"
BUILDING = "0192f000-0000-7000-8000-00000000000b"
FLOOR = "0192f000-0000-7000-8000-00000000000f"
ROOM_A = "0192f000-0000-7000-8000-0000000000a1"
ROOM_B = "0192f000-0000-7000-8000-0000000000b2"
DESK = "0192f000-0000-7000-8000-0000000000d1"


class Access:
    """Answers GET /me/scopes: accounts listed in `admins` administer the building; `grants` adds more.
    Also plays buildings (two rooms of one floor) and assets (a desk in room A)."""

    def __init__(self, tokens: Tokens):
        self.tokens, self.admins, self.up = tokens, {"boss"}, True
        self.grants: dict[str, list[dict]] = {}
        self.persons: dict[str, str] = {}

    def person(self, sub: str, person_id: str, *grants: tuple[str, str, str]) -> dict[str, str]:
        self.persons[sub] = person_id
        self.grants[sub] = [{"role": r, "scope": {"kind": k, "id": i}, "building_id": BUILDING} for r, k, i in grants]
        return self.tokens.bearer(sub)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert not url.startswith(ISSUER)
        if url.startswith(BUILDINGS):
            room = request.url.path.rsplit("/", 1)[-1]
            if room in (ROOM_A, ROOM_B):
                return httpx.Response(200, json={"id": room, "building_id": BUILDING, "floor_id": FLOOR,
                                                 "name": "Кабинет"})
            return httpx.Response(404, json={"code": "not_found"})
        if url.startswith(ASSETS):
            if request.url.path.endswith(DESK):
                return httpx.Response(200, json={"id": DESK, "room_id": ROOM_A, "building_id": BUILDING})
            return httpx.Response(404, json={"code": "not_found"})
        assert url.startswith(ACCESS)
        if not self.up:
            raise httpx.ConnectError("access is down")
        me = self.tokens.verifier().identity(request.headers["authorization"].removeprefix("Bearer "))
        grants = [{"role": "admin", "scope": {"kind": "building", "id": BUILDING}, "building_id": BUILDING}]
        mine = (grants if me.sub in self.admins else []) + self.grants.get(me.sub, [])
        return httpx.Response(200, json={"admin": False, "person_id": self.persons.get(me.sub), "buildings": [BUILDING],
                                         "grants": mine})


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
    client = ServiceClient(settings, {"access": ACCESS, "buildings": BUILDINGS, "assets": ASSETS}, http)
    async with running(build(settings, tokens.verifier(), client)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
