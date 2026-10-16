"""Учётные записи (5.7.1, С20 в части этапа 0) и права на сервере (8.4 п. 3)."""

import uuid

from tests.conftest import login, make_client


def _create(admin, **fields) -> dict:  # type: ignore[no-untyped-def,type-arg]
    body = {"login": "petrova", "full_name": "Петрова Е. А.", "role": "viewer",
            "building_ids": []} | fields
    r = admin.post("/api/users", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_admin_creates_a_viewer_who_logs_in_and_sees_no_admin_data(admin, app) -> None:
    created = _create(admin)
    temporary = created["temporary_password"]
    assert len(temporary) >= 10
    assert created["user"]["role"] == "viewer" and created["user"]["must_change_password"]

    with make_client(app) as viewer:
        me = login(viewer, "petrova", temporary)
        assert me["role"] == "viewer" and me["buildings"] == []
        r = viewer.post("/api/auth/password", json={"current": temporary,
                                                     "new": "Viewer-pass-1"})
        assert r.status_code == 200
        for path in ["/api/users", "/api/journal", "/api/system/status",
                     "/api/system/settings"]:
            r = viewer.get(path)
            assert r.status_code == 403, path
            assert r.json()["error"]["message"] == "Это действие вам недоступно."
        assert viewer.post("/api/users", json={"login": "x", "full_name": "x",
                                               "role": "admin"}).status_code == 403

    items = admin.get("/api/users").json()["items"]
    assert [u["login"] for u in items] == ["admin", "petrova"]
    assert items[1]["last_login_at"] is not None


def test_login_must_be_unique_and_valid(admin) -> None:
    _create(admin)
    r = admin.post("/api/users", json={"login": "Petrova", "full_name": "Другая",
                                       "role": "viewer"})
    assert r.status_code == 409 and r.json()["error"] == {
        "code": "login_taken", "message": "Имя для входа «Petrova» уже занято.",
        "field": "login"}
    r = admin.post("/api/users", json={"login": "с пробелом", "full_name": "Х",
                                       "role": "viewer"})
    assert r.status_code == 400 and r.json()["error"]["field"] == "login"
    r = admin.post("/api/users", json={"login": "x2", "full_name": " ", "role": "viewer"})
    assert r.json()["error"]["field"] == "full_name"


def test_admin_may_set_the_temporary_password(admin, app) -> None:
    _create(admin, password="Temporary-1")
    with make_client(app) as c:
        assert login(c, "petrova", "Temporary-1")["must_change_password"]


def test_unknown_building_is_refused(admin) -> None:
    r = admin.post("/api/users", json={"login": "petrova", "full_name": "П",
                                       "role": "viewer", "building_ids": [str(uuid.uuid4())]})
    assert r.status_code == 400 and r.json()["error"]["field"] == "building_ids"


def test_edit_with_a_stale_version_is_refused(admin) -> None:
    user = _create(admin)["user"]
    r = admin.patch(f"/api/users/{user['id']}", json={"version": user["version"],
                                                       "full_name": "Петрова Е. Б."})
    assert r.status_code == 200 and r.json()["version"] == user["version"] + 1
    r = admin.patch(f"/api/users/{user['id']}", json={"version": user["version"],
                                                       "full_name": "Иное"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"


def test_reset_password_ends_sessions_and_requires_a_change(admin, app) -> None:
    user = _create(admin, password="Temporary-1")["user"]
    with make_client(app) as c:
        login(c, "petrova", "Temporary-1")
        r = admin.post(f"/api/users/{user['id']}/reset-password", json={})
        new = r.json()["temporary_password"]
        assert c.get("/api/auth/me").status_code == 401
        assert login(c, "petrova", new)["must_change_password"]


def test_block_ends_sessions_and_refuses_login(admin, app) -> None:
    user = _create(admin, password="Temporary-1")["user"]
    with make_client(app) as c:
        login(c, "petrova", "Temporary-1")
        assert admin.post(f"/api/users/{user['id']}/block").json()["blocked"] is True
        assert c.get("/api/auth/me").status_code == 401
        r = c.post("/api/auth/login", json={"login": "petrova", "password": "Temporary-1"})
        assert r.json()["error"]["code"] == "blocked"
        admin.post(f"/api/users/{user['id']}/unblock")
        login(c, "petrova", "Temporary-1")


def test_the_last_admin_cannot_be_lost(admin) -> None:
    me = admin.get("/api/auth/me").json()
    r = admin.post(f"/api/users/{me['id']}/block")
    assert r.status_code == 409 and r.json()["error"]["code"] == "self"
    r = admin.patch(f"/api/users/{me['id']}", json={"version": me["version"],
                                                     "role": "viewer"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "self"

    other = _create(admin, login="second", role="admin")["user"]
    # второй администратор может снять роль с первого, но не с последнего
    assert admin.patch(f"/api/users/{other['id']}",
                       json={"version": other["version"], "role": "viewer"}).status_code == 200


def test_changes_are_journaled_with_before_and_after(admin) -> None:
    user = _create(admin)["user"]
    admin.patch(f"/api/users/{user['id']}", json={"version": user["version"],
                                                   "full_name": "Петрова Е. Б."})
    feed = admin.get("/api/journal", params={"ref": f"user:{user['id']}"}).json()["items"]
    assert [e["action"] for e in feed] == ["user.update", "user.create"]
    assert feed[0]["before"] == {"full_name": "Петрова Е. А."}
    assert feed[0]["after"] == {"full_name": "Петрова Е. Б."}
    assert feed[0]["actor_name"] == "Андреева Н. В."
    assert feed[1]["after"]["role"] == "просмотр"
