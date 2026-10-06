"""The import service under test: a scratch database, a bucket of its own in
the dev stack's S3, tokens signed here, and the worker run by hand — one build
per call. No other service is needed: access and buildings are stand-ins."""
from __future__ import annotations

import os
import secrets
import tempfile

# before the service's modules are imported: they read these once
os.environ["TWIN_S3_BUCKET"] = f"test-import-{secrets.token_hex(4)}"
os.environ["TWIN_DATA"] = tempfile.mkdtemp(prefix="twin-import-test-")
os.environ.setdefault("TWIN_S3_ENDPOINT", os.environ.get("TWIN_TEST_S3_ENDPOINT", "http://127.0.0.1:9002"))

import shutil  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from twin_chassis.client import ServiceClient  # noqa: E402
from twin_chassis.testing import Tokens, running, scratch_database, test_settings  # noqa: E402

from app import storage  # noqa: E402
from app.main import SERVICE, build  # noqa: E402
from app.worker import Worker  # noqa: E402

from .make_sample import make  # noqa: E402

BUILDING = "0192f000-0000-7000-8000-000000000001"


@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    bucket = storage.bucket()
    try:
        bucket.delete_prefix("")
        bucket._s3.delete_bucket(Bucket=bucket.name)
    except Exception:
        pass
    shutil.rmtree(os.environ["TWIN_DATA"], ignore_errors=True)


@pytest.fixture(scope="session")
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture(scope="session")
def sample(tmp_path_factory) -> bytes:
    """A small two-storey plan as DXF (tests/make_sample.py)."""
    return make(tmp_path_factory.mktemp("dxf") / "sample.dxf").read_bytes()


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


@pytest.fixture
def grants() -> dict[str, list[dict]]:
    """account -> its grants, as the access service would say"""
    return {}


@pytest.fixture
def buildings() -> dict[str, dict]:
    """What the buildings service answers, by path (relative to /api/buildings/v1); the rest is 404.
    Asked for the model of a guest of a floor: the floor's plan and the drawings placed in the building."""
    return {}


@pytest_asyncio.fixture
async def app(database_url, tokens, grants, buildings):
    def neighbours(request: httpx.Request) -> httpx.Response:
        if request.url.host == "buildings.test":
            found = buildings.get(request.url.path.removeprefix("/api/buildings/v1"))
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"code": "not_found"})
        me = tokens.verifier().identity(request.headers["authorization"].removeprefix("Bearer "))
        mine = grants.get(me.sub, [])
        return httpx.Response(200, json={"admin": False, "service": False, "person_id": None, "grants": mine,
                                         "buildings": sorted({g["building_id"] for g in mine})})

    settings = test_settings(SERVICE, database_url)
    client = ServiceClient(settings, {"access": "http://access.test", "buildings": "http://buildings.test"},
                           httpx.AsyncClient(transport=httpx.MockTransport(neighbours)))
    async with running(build(settings, tokens.verifier(), client)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def worker(app) -> Worker:
    return Worker(app.state.db, app.state.bus)


async def upload(client, tokens, data: bytes, name: str = "plan.dxf", **form) -> httpx.Response:
    return await client.post("/api/import/v1/drawings", headers=tokens.admin(),
                             files={"file": (name, data, "application/octet-stream")},
                             data={"building_id": BUILDING, **form})
