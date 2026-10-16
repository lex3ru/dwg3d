"""Вход, сеанс, смена пароля, блокировка после неудачных попыток (5.7.1, 8.4 п. 2)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.db import transaction
from app.modules.access import api as access
from app.modules.access.models import Account, LoginSession
from app.modules.journal.models import Entry
from tests.conftest import ADMIN_PASSWORD, login, make_client


def _actions() -> list[str]:
    with transaction() as s:
        return list(s.scalars(select(Entry.action).order_by(Entry.id)))


def test_first_login_requires_a_new_password(app) -> None:
    with transaction() as s:
        temporary = access.create_first_admin(s, "admin", "Андреева Н. В.")
        assert access.create_first_admin(s, "admin2", "Другой") is None
    with make_client(app) as c:
        me = login(c, "ADMIN", temporary)  # имя — без учёта регистра
        assert me["must_change_password"] is True
        r = c.get("/api/users")
        assert r.status_code == 403 and r.json()["error"]["code"] == "must_change_password"
        r = c.post("/api/auth/password", json={"current": temporary, "new": "short"})
        assert r.status_code == 400 and r.json()["error"]["field"] == "new"
        r = c.post("/api/auth/password", json={"current": "wrong", "new": ADMIN_PASSWORD})
        assert r.json()["error"]["field"] == "current"
        r = c.post("/api/auth/password", json={"current": temporary, "new": ADMIN_PASSWORD})
        assert r.status_code == 200 and r.json()["must_change_password"] is False
        assert c.get("/api/users").status_code == 200
    assert _actions() == ["user.create", "auth.login", "user.password_change"]


def test_wrong_password_and_unknown_login_are_journaled(admin, app) -> None:
    with make_client(app) as c:
        r = c.post("/api/auth/login", json={"login": "admin", "password": "nope-nope-nope"})
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Неверное имя или пароль."
        r = c.post("/api/auth/login", json={"login": "ghost", "password": "nope-nope-nope"})
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Неверное имя или пароль."
    with transaction() as s:
        failed = list(s.scalars(select(Entry).where(Entry.action == "auth.login_failed")))
    assert [e.summary for e in failed] == ["Неверный пароль при входе «admin»",
                                          "Неудачная попытка входа: имени «ghost» нет"]


def test_ten_failures_lock_the_login_for_15_minutes(admin, app) -> None:
    with make_client(app) as c:
        for _ in range(9):
            assert c.post("/api/auth/login", json={"login": "admin", "password": "x" * 10}
                          ).json()["error"]["code"] == "bad_credentials"
        r = c.post("/api/auth/login", json={"login": "admin", "password": "x" * 10})
        assert r.json()["error"]["code"] == "locked"
        assert "15 мин" in r.json()["error"]["message"]
        # во время блокировки не пускает и с верным паролем
        r = c.post("/api/auth/login", json={"login": "admin", "password": ADMIN_PASSWORD})
        assert r.json()["error"]["code"] == "locked"
        with transaction() as s:
            s.execute(update(Account).values(locked_until=datetime.now(UTC) - timedelta(1)))
        login(c, "admin", ADMIN_PASSWORD)


def test_session_ends_after_12_idle_hours(admin) -> None:
    assert admin.get("/api/auth/me").status_code == 200
    with transaction() as s:
        s.execute(update(LoginSession).values(
            last_seen_at=datetime.now(UTC) - timedelta(hours=12, minutes=1)))
    r = admin.get("/api/auth/me")
    assert r.status_code == 401 and "12 часов" in r.json()["error"]["message"]


def test_logout(admin) -> None:
    assert admin.post("/api/auth/logout").status_code == 204
    assert admin.get("/api/auth/me").status_code == 401


def test_changes_need_the_app_header(admin) -> None:
    r = admin.post("/api/auth/logout", headers={"X-Requested-With": ""})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"


def test_cookie_is_http_only(app) -> None:
    with transaction() as s:
        temporary = access.create_first_admin(s, "admin", "А")
    with make_client(app) as c:
        r = c.post("/api/auth/login", json={"login": "admin", "password": temporary})
        cookie = r.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie


def test_anonymous_gets_nothing(client) -> None:
    for path in ["/api/auth/me", "/api/users", "/api/journal", "/api/system/status"]:
        assert client.get(path).status_code == 401, path
