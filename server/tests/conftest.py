"""Тесты идут на настоящем PostgreSQL. Адрес сервера — TEST_DATABASE_URL (по умолчанию
база разработки из server/README.md); для тестов создаётся отдельная база app_test."""

import os
from collections.abc import Iterator

import psycopg
import pytest

ADMIN_URL = os.environ.get("TEST_DATABASE_URL",
                           "postgresql+psycopg://app:app@localhost:55432/app")
TEST_DB = "app_test"
base, _, _ = ADMIN_URL.rpartition("/")
os.environ["APP_DATABASE_URL"] = f"{base}/{TEST_DB}"
os.environ["APP_SECURE_COOKIES"] = "false"
os.environ["APP_STATIC_DIR"] = "/nonexistent"
os.environ.setdefault("APP_DATA_DIR", "/tmp")
os.environ.setdefault("APP_BACKUP_DIR", "/nonexistent-backups")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import transaction  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.access import api as access  # noqa: E402

ADMIN_PASSWORD = "Admin-pass-123"


def _plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    with psycopg.connect(_plain(ADMIN_URL), autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    from app.__main__ import migrate

    migrate()
    yield


@pytest.fixture(autouse=True)
def clean() -> Iterator[None]:
    yield
    with transaction() as s:
        s.execute(text("SET LOCAL journal.purge = 'on'"))
        s.execute(text("DELETE FROM journal.entry"))
        s.execute(text("TRUNCATE access.account, access.login_session, access.building_grant, "
                       "core.job, core.schedule_run, core.worker_beat, system.setting CASCADE"))


@pytest.fixture(scope="session")
def app():  # type: ignore[no-untyped-def]
    return create_app()


def make_client(app) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(app, headers={"X-Requested-With": "app"})


@pytest.fixture
def client(app) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    with make_client(app) as c:
        yield c


def login(client: TestClient, name: str, password: str) -> dict:  # type: ignore[type-arg]
    r = client.post("/api/auth/login", json={"login": name, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin(app) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """Клиент вошедшего администратора, временный пароль уже сменён."""
    with transaction() as s:
        temporary = access.create_first_admin(s, "admin", "Андреева Н. В.")
    assert temporary
    with make_client(app) as c:
        login(c, "admin", temporary)
        r = c.post("/api/auth/password", json={"current": temporary, "new": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        yield c
