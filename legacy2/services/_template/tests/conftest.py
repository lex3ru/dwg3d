"""The service under test runs on a scratch database with tokens signed here;
no other service is needed."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from twin_chassis.testing import Tokens, running, scratch_database, test_settings

from app.main import SERVICE, build


@pytest.fixture(scope="session")
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


@pytest_asyncio.fixture
async def app(database_url, tokens):
    async with running(build(test_settings(SERVICE, database_url), tokens.verifier())) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
