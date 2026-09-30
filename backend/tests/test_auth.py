"""Sign-in, roles and authorship (DWG3D_AUTH=on)."""
import uuid

import pytest
from fastapi.testclient import TestClient

from dwg3d import auth, db, store
from dwg3d.models import Build, Placement, Project

PASSWORD = "test-" + uuid.uuid4().hex[:12]     # generated per run, never a real password


@pytest.fixture
def on(monkeypatch, pg):
    monkeypatch.setenv("DWG3D_AUTH", "on")
    from dwg3d import api
    api._FAILS.clear()
    return api


def _user(role: str) -> str:
    login = f"{role}-{uuid.uuid4().hex[:6]}"
    auth.add_user(login, PASSWORD, role=role, name=f"Имя {role}")
    return login


def _client(api, login: str | None = None) -> TestClient:
    c = TestClient(api.app)
    if login:
        r = c.post("/api/auth/login", json={"login": login, "password": PASSWORD})
        assert r.status_code == 200, r.text
    return c


def _project() -> str:
    pid = uuid.uuid4().hex[:12]
    floor = {"id": "c0", "space": "Model", "owner": None, "bbox": [0, 0, 30, 20], "offset": [0, 0], "name": "1 этаж"}
    with db.session() as s:
        s.add(Project(id=pid, filename="p.dxf", input_path="input.dxf", current_build=1))
        s.flush()
        s.add(Build(project_id=pid, n=1, result={"floors": [floor]}, config={}, out_dir="out"))
        store.sync_floors(s, pid, {"floors": [floor]})
    return pid


def test_passwords_are_salted_hashes():
    h = auth.hash_password("correct horse")
    assert h.startswith("scrypt$") and "correct" not in h and h != auth.hash_password("correct horse")
    assert auth.check_password("correct horse", h) and not auth.check_password("wrong horse", h)
    assert not auth.check_password("x", None) and not auth.check_password("x", "md5$abc")


def test_nothing_opens_without_sign_in(on):
    c = _client(on)
    assert c.get("/api/health").status_code == 200
    pid = _project()
    for url in ("/api/jobs", f"/api/jobs/{pid}", f"/api/jobs/{pid}/files/model.glb", "/api/catalog",
                f"/api/projects/{pid}/placements", f"/api/projects/{pid}/audit"):
        r = c.get(url)
        assert r.status_code == 401 and r.json()["login"] is True, url
    assert c.post("/api/jobs", files={"file": ("a.dxf", b"0")}).status_code == 401
    assert c.get("/api/auth/me").status_code == 401


def test_login_logout_and_cookie(on):
    login = _user("viewer")
    c = TestClient(on.app)
    assert c.post("/api/auth/login", json={"login": login, "password": "wrong-password"}).status_code == 401
    assert c.post("/api/auth/login", json={"login": "nobody", "password": PASSWORD}).status_code == 401
    assert c.post("/api/auth/login", json={"login": login}).status_code == 400
    r = c.post("/api/auth/login", json={"login": login.upper(), "password": PASSWORD})    # login is case-insensitive
    assert r.status_code == 200 and r.json()["role"] == "viewer" and r.json()["name"] == "Имя viewer"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie   # plain http here
    assert c.get("/api/auth/me").json()["login"] == login
    assert c.get("/api/jobs").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/jobs").status_code == 401
    # a stolen old cookie does not work after logout either
    c2 = _client(on, login)
    token = c2.cookies.get(auth.COOKIE)
    c2.post("/api/auth/logout")
    c3 = TestClient(on.app, cookies={auth.COOKIE: token})
    assert c3.get("/api/jobs").status_code == 401


def test_repeated_failures_are_throttled(on):
    login = _user("viewer")
    c = TestClient(on.app)
    for _ in range(on.FAIL_LIMIT):
        assert c.post("/api/auth/login", json={"login": login, "password": "wrong-password"}).status_code == 401
    assert c.post("/api/auth/login", json={"login": login, "password": PASSWORD}).status_code == 429


def test_roles(on):
    pid = _project()
    viewer, editor, admin = _client(on, _user("viewer")), _client(on, _user("editor")), _client(on, _user("catalog_admin"))
    item = {"floor": "c0", "item": "doc.couch", "at": [1, 2], "build": 1}
    assert viewer.get(f"/api/projects/{pid}/placements").status_code == 200
    r = viewer.post(f"/api/projects/{pid}/placements", json=item)
    assert r.status_code == 403 and "редактор" in r.json()["detail"]
    assert viewer.put(f"/api/jobs/{pid}/view", json={"name": "x"}).status_code == 403
    assert viewer.post(f"/api/jobs/{pid}/rebuild", json={}).status_code == 403
    assert editor.post(f"/api/projects/{pid}/placements", json=item).status_code == 201
    # catalog changes: only the catalog administrator gets past the check (405: no such method yet)
    assert editor.post("/api/catalog", json={}).status_code == 403
    assert admin.post("/api/catalog", json={}).status_code == 405
    assert admin.post(f"/api/projects/{pid}/placements", json=item).status_code == 201


def test_author_is_recorded(on):
    pid = _project()
    login = _user("editor")
    c = _client(on, login)
    r = c.post(f"/api/projects/{pid}/placements", json={"id": "a", "floor": "c0", "item": "doc.couch", "at": [1, 2]})
    assert r.status_code == 201
    r = c.post(f"/api/projects/{pid}/pins", json={"id": "k", "kind": "comment", "floor": "c0", "pos": [0, 0, 0], "text": "!"})
    assert r.json()["author"] == "Имя editor"
    assert c.put(f"/api/jobs/{pid}/view", json={"name": "Корпус Б"}).status_code == 200
    log = c.get(f"/api/projects/{pid}/audit").json()
    assert {a["actor"] for a in log} == {login}
    assert {(a["entity"], a["action"]) for a in log} == {("placement", "create"), ("pin", "create"), ("project", "update")}
    with db.session() as s:
        uid = s.get(Placement, (pid, "a")).updated_by
    assert uid is not None and {a["user_id"] for a in log} == {uid}


def test_disabled_user_and_new_password_sign_out(on):
    login = _user("editor")
    c = _client(on, login)
    auth.set_password(login, PASSWORD + "-new")
    assert c.get("/api/jobs").status_code == 401
    auth.set_password(login, PASSWORD)
    c = _client(on, login)
    auth.set_active(login, False)
    assert c.get("/api/jobs").status_code == 401
    assert TestClient(on.app).post("/api/auth/login", json={"login": login, "password": PASSWORD}).status_code == 401


def test_user_management_errors(pg):
    login = _user("viewer")
    with pytest.raises(auth.UserError, match="уже есть"):
        auth.add_user(login.upper(), PASSWORD)
    with pytest.raises(auth.UserError, match="не короче"):
        auth.add_user("new-" + login, "short")
    with pytest.raises(auth.UserError, match="роль"):
        auth.set_role(login, "root")
    auth.set_role(login, "editor")
    assert next(u for u in auth.list_users() if u["login"] == login)["role"] == "editor"


def test_auth_off_lets_everyone_edit(monkeypatch, pg):
    monkeypatch.setenv("DWG3D_AUTH", "off")
    from dwg3d import api
    c = TestClient(api.app)
    assert c.get("/api/auth/me").json()["role"] == "catalog_admin" and c.get("/api/auth/me").json()["auth"] is False
    assert c.get("/api/jobs").status_code == 200
