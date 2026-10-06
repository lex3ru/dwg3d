"""The access service under test: a scratch database, tokens signed here; the people
service is played by its events."""
from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from twin_chassis.client import ServiceClient
from twin_chassis.events import envelope
from twin_chassis.testing import ISSUER, Tokens, running, scratch_database, test_settings

from app.main import SERVICE, build

API = "/api/access/v1"


@pytest.fixture(scope="session")
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


class Sources:
    """Plays the people and assets services for the reconciliation: what the automatic grants should follow."""

    def __init__(self, tokens: Tokens):
        self.tokens = tokens
        self.assignments: list[dict] = []
        self.responsibles: list[dict] = []
        self.up = True

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(ISSUER):
            token = self.tokens.make("svc-access", login="twin-svc-access", service=True)
            return httpx.Response(200, json={"access_token": token, "expires_in": 300})
        if not self.up:
            raise httpx.ConnectError("down")
        if request.url.path.endswith("/assignments"):
            return httpx.Response(200, json={"items": self.assignments})
        if request.url.path.endswith("/responsibles"):
            return httpx.Response(200, json={"items": self.responsibles})
        return httpx.Response(404, json={"code": "not_found"})


@pytest.fixture
def sources(tokens) -> Sources:
    return Sources(tokens)


@pytest_asyncio.fixture
async def app(database_url, tokens, sources):
    settings = test_settings(SERVICE, database_url)
    http = httpx.AsyncClient(transport=httpx.MockTransport(sources.handle))
    client = ServiceClient(settings, {"people": "http://people.test", "assets": "http://assets.test"}, http)
    async with running(build(settings, tokens.verifier(), client, reconcile_s=3600)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


class People:
    """Plays the people service: who is who."""

    def __init__(self, app, tokens):
        self.app, self.tokens = app, tokens

    async def person(self, sub: str) -> tuple[str, dict]:
        """A person of the directory with a linked account; returns the person's id and the account's headers."""
        person_id = str(uuid4())
        await self.event("person-linked", "people.person.linked", {"person_id": person_id, "user_sub": sub})
        return person_id, self.tokens.bearer(sub)

    async def event(self, handler: str, type_: str, data: dict) -> None:
        event = envelope(type_, ("person", data["person_id"]), data, actor={"kind": "service", "id": "people"})
        assert await self.app.state.bus.handle(handler, event) is True


@pytest.fixture
def people(app, tokens) -> People:
    return People(app, tokens)
