"""The catalog under test: a scratch database (with what the catalog starts with), a bucket of
its own in the dev stack's S3, tokens signed here. No other service is needed."""
from __future__ import annotations

import os
import secrets

os.environ["TWIN_S3_BUCKET"] = f"test-catalog-{secrets.token_hex(4)}"
os.environ.setdefault("TWIN_S3_ENDPOINT", os.environ.get("TWIN_TEST_S3_ENDPOINT", "http://127.0.0.1:9002"))

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from twin_chassis.client import ServiceClient  # noqa: E402
from twin_chassis.testing import Tokens, running, scratch_database, test_settings  # noqa: E402

from app import storage  # noqa: E402
from app.main import SERVICE, build  # noqa: E402

API = "/api/catalog/v1"


@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    bucket = storage.bucket()
    try:
        bucket.delete_prefix("")
        bucket._s3.delete_bucket(Bucket=bucket.name)
    except Exception:
        pass


@pytest.fixture(scope="session")
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


@pytest.fixture
def used() -> dict[str, int]:
    """property key -> how many objects have a value for it, as the assets service would say"""
    return {}


@pytest_asyncio.fixture
async def app(database_url, tokens, used):
    def assets(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"assets": 0, "with_value": used.get(request.url.params["prop"], 0)})

    settings = test_settings(SERVICE, database_url)
    client = ServiceClient(settings, {"assets": "http://assets.test"},
                           httpx.AsyncClient(transport=httpx.MockTransport(assets)))
    async with running(build(settings, tokens.verifier(), client)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
