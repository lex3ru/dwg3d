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

from fastapi import Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.orm import ORMExecuteState, Session  # noqa: E402

from app.core.db import get_session, transaction  # noqa: E402
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


# ---------------------------------------------------------------- страж журнала (R-011)

# Каждое изменение данных пишет запись журнала в той же транзакции (9.2 п. 3). Страж следит за
# транзакциями запросов всех тестов: изменила таблицы — должна записать и журнал. Здесь —
# таблицы, правка которых не изменение данных, и почему.
NOT_DATA = {
    "access.login_session": "сеанс: вход и выход пишутся сами, остальное — отметка «был»",
    "core.job": "очередь фоновых задач; что изменит задача, она запишет сама",
    "files.file": "файл до привязки: в журнал — то, к чему его привязали",
    "inventory.room_label": "код метки двери: заводится при первой печати и не меняется",
    # отметки обхода хранят автора и время сами; итог инвентаризации — в записи о проведении
    "inventory.count_mark": "отметка обхода",
    "inventory.count_extra": "найденное сверх ведомости",
    "inventory.count_stock": "пересчёт количества",
    "inventory.count_device": "номер последней отметки устройства — от повторов (ADR-0006)",
}
unjournaled: list[str] = []


def _touched(session: Session, table: str) -> None:
    session.info.setdefault("touched", set()).add(table)


@event.listens_for(Session, "after_flush")
def _flushed(session: Session, _: object) -> None:
    if "request" in session.info:
        for obj in [*session.new, *session.deleted,
                    *(o for o in session.dirty if session.is_modified(o))]:
            _touched(session, obj.__table__.fullname)


@event.listens_for(Session, "do_orm_execute")
def _executed(state: ORMExecuteState) -> None:
    if "request" in state.session.info and (state.is_insert or state.is_update
                                            or state.is_delete):
        _touched(state.session, state.statement.table.fullname)  # type: ignore[attr-defined]


@event.listens_for(Session, "after_commit")
def _committed(session: Session) -> None:
    if session.in_nested_transaction():
        return  # точка сохранения (проведение документа) — запись журнала будет дальше
    touched = session.info.pop("touched", set())
    if "journal.entry" not in touched and (data := touched - NOT_DATA.keys()):
        unjournaled.append(f"{session.info['request']}: {', '.join(sorted(data))}")


@event.listens_for(Session, "after_rollback")
def _rolled_back(session: Session) -> None:
    session.info.pop("touched", None)


def _request_session(request: Request) -> Iterator[Session]:
    with transaction() as session:
        session.info["request"] = f"{request.method} {request.url.path}"
        yield session


@pytest.fixture(autouse=True)
def journaled() -> Iterator[None]:
    unjournaled.clear()
    yield
    assert not unjournaled, "изменение без записи журнала (9.2 п. 3): " + "; ".join(unjournaled)


@pytest.fixture(scope="session")
def app():  # type: ignore[no-untyped-def]
    app = create_app()
    app.dependency_overrides[get_session] = _request_session
    return app


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
