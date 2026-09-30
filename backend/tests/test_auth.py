"""Sign-in through OpenID Connect (a fake Keycloak), project members, share links."""
import base64
import hashlib
import time
import urllib.parse
import uuid
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text

from conftest import add_drawing
from dwg3d import auth, db, store
from dwg3d.models import Build

ISSUER = "http://kc.test/auth/realms/dwg3d"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeKeycloak:
    """The token endpoint of a Keycloak realm: codes issued by `sign_in`, refresh tokens."""

    def __init__(self):
        self.codes: dict[str, tuple] = {}
        self.refresh: dict[str, dict] = {}
        self.revoked: set[str] = set()

    def tokens(self, user: dict, nonce: str | None) -> dict:
        now = int(time.time())
        base = {"iss": ISSUER, "sub": user["sub"], "iat": now, "exp": now + 300,
                "preferred_username": user["login"], "name": user.get("name", user["login"]),
                "email": user.get("email")}
        idt = jwt.encode({**base, "aud": "dwg3d", "nonce": nonce}, KEY, algorithm="RS256")
        acc = jwt.encode({**base, "aud": "account", "realm_access": {"roles": user.get("roles", [])}}, KEY,
                         algorithm="RS256")
        rt = uuid.uuid4().hex
        self.refresh[rt] = user
        return {"access_token": acc, "id_token": idt, "refresh_token": rt}

    def post(self, url: str, data: dict) -> dict:
        assert url.startswith(ISSUER) and url.endswith("/token")
        if data["grant_type"] == "authorization_code":
            got = self.codes.pop(data["code"], None)
            if got is None:
                raise auth.OIDCError("invalid_grant")
            user, nonce, challenge = got
            want = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).decode().rstrip("=")
            assert want == challenge, "PKCE"
            return self.tokens(user, nonce)
        user = self.refresh.get(data["refresh_token"])
        if user is None or user["sub"] in self.revoked:
            raise auth.OIDCError("Session not active")
        return self.tokens(user, None)


@pytest.fixture
def kc(monkeypatch, pg):
    fake = FakeKeycloak()
    monkeypatch.setenv("DWG3D_AUTH", "oidc")
    monkeypatch.setenv("DWG3D_OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(auth, "_post_form", fake.post)
    monkeypatch.setattr(auth, "_signing_key", lambda token: KEY.public_key())
    return fake


@pytest.fixture
def api(pg):
    from dwg3d import api as module
    return module


def sign_in(api, kc, login, roles=(), email=None, next_="/"):
    """A client signed in as `login` through the whole code flow."""
    c = TestClient(api.app)
    r = c.get(f"/api/auth/login?next={urllib.parse.quote(next_)}", follow_redirects=False)
    assert r.status_code == 303
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
    assert r.headers["location"].startswith(ISSUER + "/protocol/openid-connect/auth")
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"] == ["http://testserver/api/auth/callback"]
    code = uuid.uuid4().hex
    kc.codes[code] = ({"sub": f"sub-{login}", "login": login, "name": f"Имя {login}", "email": email,
                       "roles": list(roles)}, q["nonce"][0], q["code_challenge"][0])
    r = c.get(f"/api/auth/callback?code={code}&state={q['state'][0]}", follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"] == next_
    return c


def _drawing() -> str:
    """A project (no members) with one drawing and one floor."""
    pid = uuid.uuid4().hex[:12]
    floor = {"id": "c0", "space": "Model", "owner": None, "bbox": [0, 0, 30, 20], "offset": [0, 0], "name": "1 этаж"}
    with db.session() as s:
        add_drawing(s, pid, current_build=1)
        s.add(Build(drawing_id=pid, n=1, result={"floors": [floor]}, config={}, out_dir="out"))
        store.sync_floors(s, pid, {"floors": [floor]})
    return pid


def test_nothing_opens_without_sign_in(kc, api):
    c = TestClient(api.app)
    assert c.get("/api/health").status_code == 200
    pid = _drawing()
    for url in ("/api/projects", f"/api/drawings/{pid}", f"/api/drawings/{pid}/files/model.glb", "/api/catalog",
                f"/api/drawings/{pid}/objects", f"/api/projects/{pid}/audit", "/api/users"):
        r = c.get(url)
        assert r.status_code == 401 and r.json()["login"] is True, url
    assert c.get("/api/auth/me").status_code == 401


def test_sign_in_flow(kc, api):
    c = sign_in(api, kc, "anna", roles=["catalog_admin"], email="anna@example.com", next_="/#/p/x")
    me = c.get("/api/auth/me").json()
    assert me["login"] == "anna" and me["name"] == "Имя anna" and me["role"] == "catalog_admin"
    assert me["email"] == "anna@example.com"
    # the same Keycloak user signs in again: the same row, roles as Keycloak says now
    c2 = sign_in(api, kc, "anna", roles=[])
    assert c2.get("/api/auth/me").json()["id"] == me["id"] and c2.get("/api/auth/me").json()["role"] == "user"
    # a forged or replayed callback is refused
    r = c.get("/api/auth/login", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    assert TestClient(api.app).get(f"/api/auth/callback?code=x&state={state}").status_code == 400      # no state cookie
    assert c.get("/api/auth/callback?code=x&state=wrong").status_code == 400
    assert c.get("/api/auth/callback?error=access_denied").status_code == 400
    # only paths of this site to return to
    assert auth.safe_next("//evil.example/x") == "/" and auth.safe_next("https://evil.example") == "/"
    # sign-out: the session ends here and in Keycloak
    r = c.post("/api/auth/logout").json()
    assert r["logout_url"].startswith(ISSUER + "/protocol/openid-connect/logout") and "id_token_hint" in r["logout_url"]
    assert c.get("/api/projects").status_code == 401


def test_session_ends_when_keycloak_ends_it(kc, api, monkeypatch):
    c = sign_in(api, kc, "boris")
    monkeypatch.setattr(auth, "REFRESH_EVERY", timedelta(0))
    assert c.get("/api/projects").status_code == 200          # refreshed fine
    kc.revoked.add("sub-boris")
    assert c.get("/api/projects").status_code == 401
    # roles follow Keycloak on refresh
    c = sign_in(api, kc, "vera")
    for u in kc.refresh.values():
        if u["sub"] == "sub-vera":
            u["roles"] = ["admin"]
    c.get("/api/projects")
    assert c.get("/api/auth/me").json()["role"] == "admin"


def test_project_members(kc, api):
    owner = sign_in(api, kc, "olga", email="olga@example.com")
    other = sign_in(api, kc, "petr", email="petr@example.com")
    admin = sign_in(api, kc, "root", roles=["admin"])
    p = owner.post("/api/projects", json={"name": "Клиника"}).json()
    assert p["my_role"] == "owner"
    pid = p["id"]
    did = owner.post(f"/api/projects/{pid}/drawings", files={"file": ("a.dxf", b"0")}).json()["id"]
    # not a member: the project does not exist for him
    assert pid not in {x["id"] for x in other.get("/api/projects").json()}
    for url in (f"/api/projects/{pid}", f"/api/drawings/{did}", f"/api/projects/{pid}/layers"):
        assert other.get(url).status_code == 404, url
    assert other.patch(f"/api/projects/{pid}", json={"name": "x"}).status_code == 404
    # an admin sees every project
    assert pid in {x["id"] for x in admin.get("/api/projects").json()}
    assert admin.get(f"/api/projects/{pid}").json()["my_role"] == "owner"

    m = owner.post(f"/api/projects/{pid}/members", json={"who": "petr", "role": "viewer"})
    assert m.status_code == 201 and m.json()["user"]["login"] == "petr"
    mid = m.json()["id"]
    assert other.get(f"/api/projects/{pid}").json()["my_role"] == "viewer"
    assert other.get(f"/api/drawings/{did}").status_code == 200
    r = other.post(f"/api/projects/{pid}/layers", json={"kind": "furniture"})
    assert r.status_code == 403 and "редактор" in r.json()["detail"]
    assert other.post(f"/api/projects/{pid}/members", json={"who": "x@example.com", "role": "viewer"}).status_code == 403
    assert owner.patch(f"/api/projects/{pid}/members/{mid}", json={"role": "editor"}).json()["role"] == "editor"
    assert other.post(f"/api/projects/{pid}/layers", json={"kind": "furniture"}).status_code == 201
    assert other.delete(f"/api/projects/{pid}").status_code == 403          # only an owner
    # members: errors and the last owner
    assert owner.post(f"/api/projects/{pid}/members", json={"who": "petr", "role": "viewer"}).status_code == 400
    assert owner.post(f"/api/projects/{pid}/members", json={"who": "nobody", "role": "viewer"}).status_code == 400
    assert owner.post(f"/api/projects/{pid}/members", json={"who": "root", "role": "boss"}).status_code == 400
    members = owner.get(f"/api/projects/{pid}/members").json()
    me_row = next(x for x in members if x["user"] and x["user"]["login"] == "olga")
    assert members[0]["role"] == "owner"
    r = owner.patch(f"/api/projects/{pid}/members/{me_row['id']}", json={"role": "viewer"})
    assert r.status_code == 400 and "владелец" in r.json()["detail"]
    assert owner.delete(f"/api/projects/{pid}/members/{me_row['id']}").status_code == 400
    assert owner.delete(f"/api/projects/{pid}/members/{mid}").status_code == 204
    assert other.get(f"/api/projects/{pid}").status_code == 404
    # author recorded; catalog changes need the catalog role
    log = owner.get(f"/api/projects/{pid}/audit").json()
    assert {("member", "create"), ("member", "update"), ("member", "delete")} <= {(a["entity"], a["action"]) for a in log}
    assert "olga" in {a["actor"] for a in log}
    assert owner.patch("/api/catalog/items/doc.couch", json={"price": 1}).status_code == 403
    assert [u["login"] for u in owner.get("/api/users?q=pet").json()] == ["petr"]


def test_invitation_by_email(kc, api):
    owner = sign_in(api, kc, "ivan")
    pid = owner.post("/api/projects", json={"name": "Приглашение"}).json()["id"]
    r = owner.post(f"/api/projects/{pid}/members", json={"who": "Nina@Example.com", "role": "editor"})
    assert r.status_code == 201 and r.json()["pending"] and r.json()["user"] is None
    nina = sign_in(api, kc, "nina", email="nina@example.com")
    assert nina.get(f"/api/projects/{pid}").json()["my_role"] == "editor"
    rows = owner.get(f"/api/projects/{pid}/members").json()
    assert {(x["user"]["login"] if x["user"] else None, x["pending"]) for x in rows} == {("ivan", False), ("nina", False)}


def test_share_links(kc, api):
    owner = sign_in(api, kc, "sofia")
    pid = owner.post("/api/projects", json={"name": "Для заказчика"}).json()["id"]
    other_pid = owner.post("/api/projects", json={"name": "Другой"}).json()["id"]
    d1 = owner.post(f"/api/projects/{pid}/drawings", files={"file": ("a.dxf", b"0")}).json()["id"]
    d2 = owner.post(f"/api/projects/{pid}/drawings", files={"file": ("b.dxf", b"0")}).json()["id"]
    furn = owner.post(f"/api/projects/{pid}/layers", json={"kind": "furniture"}).json()["id"]
    cctv = owner.post(f"/api/projects/{pid}/layers", json={"kind": "cctv"}).json()["id"]
    assert owner.post(f"/api/projects/{pid}/shares", json={"drawings": ["nope"]}).status_code == 400
    assert owner.post(f"/api/projects/{pid}/shares", json={"days": 0}).status_code == 400
    sh = owner.post(f"/api/projects/{pid}/shares", json={"name": "Заказчик", "days": 30, "drawings": [d1],
                                                         "layers": [furn]}).json()
    assert sh["url"].endswith(f"/#/s/{sh['token']}") and sh["active"]
    assert "token" not in owner.get(f"/api/projects/{pid}/shares").json()[0]

    guest = TestClient(api.app)
    assert guest.post("/api/share/wrong-token").status_code == 404
    me = guest.post(f"/api/share/{sh['token']}").json()
    assert me["guest"]["project_id"] == pid
    assert guest.get("/api/auth/me").json()["guest"]["drawings"] == [d1]
    # read-only, one project, the drawings and layers of the link
    assert [p["id"] for p in guest.get("/api/projects").json()] == [pid]
    assert [d["id"] for d in guest.get(f"/api/projects/{pid}").json()["drawings"]] == [d1]
    assert guest.get(f"/api/drawings/{d1}").json()["my_role"] == "viewer"
    assert guest.get(f"/api/drawings/{d2}").status_code == 404
    assert guest.get(f"/api/projects/{other_pid}").status_code == 404
    assert [x["id"] for x in guest.get(f"/api/projects/{pid}/layers").json()] == [furn]
    assert cctv not in {x["id"] for x in guest.get(f"/api/drawings/{d1}").json()["layers"]}
    assert guest.post(f"/api/projects/{pid}/layers", json={"kind": "furniture"}).status_code == 403
    assert guest.patch(f"/api/projects/{pid}", json={"name": "x"}).status_code == 403
    assert guest.get(f"/api/projects/{pid}/audit").status_code == 403
    assert guest.get(f"/api/projects/{pid}/shares").status_code == 403
    # revoked: the guest is out
    assert owner.delete(f"/api/projects/{pid}/shares/{sh['id']}").json()["revoked"] is True
    assert guest.get(f"/api/drawings/{d1}").status_code == 401
    # expired
    sh2 = owner.post(f"/api/projects/{pid}/shares", json={}).json()
    with db.session() as s:
        s.execute(text("UPDATE share_links SET expires_at = now() - interval '1 minute' WHERE id = :i"), {"i": sh2["id"]})
    assert TestClient(api.app).post(f"/api/share/{sh2['token']}").status_code == 404
