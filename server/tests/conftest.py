"""Тесты идут на настоящем PostgreSQL. Адрес сервера — TEST_DATABASE_URL (по умолчанию
база разработки из server/README.md); для тестов создаётся отдельная база app_test."""

import functools
import os
import tempfile
from collections.abc import Iterator

import psycopg
import pytest

# 127.0.0.1, а не localhost: база проброшена только на IPv4, а на Windows localhost — сначала
# ::1, и подключение ждёт ~2 мин таймаута, прежде чем перейти на IPv4 (R-006, R-034)
ADMIN_URL = os.environ.get("TEST_DATABASE_URL",
                           "postgresql+psycopg://app:app@127.0.0.1:55432/app")
TEST_DB = "app_test"
base, _, _ = ADMIN_URL.rpartition("/")
os.environ["APP_DATABASE_URL"] = f"{base}/{TEST_DB}"
os.environ["APP_SECURE_COOKIES"] = "false"
os.environ["APP_STATIC_DIR"] = "/nonexistent"
os.environ["APP_DATA_DIR"] = tempfile.mkdtemp(prefix="app-data-")
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
                       "access.share_link, "
                       "building.building, files.file, catalog.layer, catalog.char_set, "
                       "catalog.item_type, catalog.purpose, inventory.document, "
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


@functools.cache
def _weasyprint_error() -> str | None:
    """Почему не загружается WeasyPrint (нет Pango — Windows без GTK); None — загружается."""
    try:
        import weasyprint  # noqa: F401
    except OSError as e:
        return str(e).split(".  ")[0]
    return None


@pytest.fixture
def pdf() -> None:
    """Тест печатает PDF. Без WeasyPrint он пропускается, а в CI это ошибка: там Pango ставит
    задание (ADR-0001), и пропуск спрятал бы дефект печати (R-006)."""
    error = _weasyprint_error()
    if error is None:
        return
    if os.environ.get("CI"):
        pytest.fail(f"WeasyPrint не загружается: {error}", pytrace=False)
    pytest.skip(f"нет Pango для WeasyPrint (на Windows — GTK): {error}")
