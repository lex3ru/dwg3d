"""Sign-in against the real Keycloak of docker-compose (skipped without it):
the login form, the code exchange, token checks and roles.

  docker compose up -d && uv run pytest tests/test_keycloak.py
"""
import os
import re
import secrets
import urllib.parse

import httpx
import pytest
from fastapi.testclient import TestClient

KC = os.environ.get("DWG3D_TEST_KEYCLOAK", "http://127.0.0.1:8180/auth")
PUBLIC = os.environ.get("DWG3D_TEST_PUBLIC_URL", "http://localhost:8088")     # KC_HOSTNAME is $PUBLIC/auth
ADMIN = (os.environ.get("KEYCLOAK_ADMIN", "kcadmin"), os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "kcadmin"))


@pytest.fixture
def kc_user():
    """A throwaway realm user with the client role dwg3d.catalog_admin: (login, password)."""
    try:
        tok = httpx.post(f"{KC}/realms/master/protocol/openid-connect/token", timeout=5,
                         data={"client_id": "admin-cli", "username": ADMIN[0], "password": ADMIN[1],
                               "grant_type": "password"}).json()["access_token"]
        httpx.get(f"{PUBLIC}/auth/realms/dwg3d", timeout=5).raise_for_status()
    except Exception as ex:
        pytest.skip(f"Keycloak недоступен ({KC}, {PUBLIC}): {ex.__class__.__name__}")
    h = {"Authorization": f"Bearer {tok}"}
    login, pw = f"test-{secrets.token_hex(4)}", secrets.token_urlsafe(12)
    r = httpx.post(f"{KC}/admin/realms/dwg3d/users", headers=h, json={
        "username": login, "enabled": True, "firstName": "Тест", "lastName": "Интеграция",
        "email": f"{login}@example.test", "emailVerified": True,
        "credentials": [{"type": "password", "value": pw, "temporary": False}]})
    assert r.status_code == 201, r.text
    uid = r.headers["location"].rsplit("/", 1)[1]
    client = httpx.get(f"{KC}/admin/realms/dwg3d/clients", headers=h, params={"clientId": "dwg3d"}).json()[0]["id"]
    role = httpx.get(f"{KC}/admin/realms/dwg3d/clients/{client}/roles/dwg3d.catalog_admin", headers=h)
    assert role.status_code == 200, "в Keycloak нет клиентской роли dwg3d.catalog_admin (realm из deploy/keycloak)"
    httpx.post(f"{KC}/admin/realms/dwg3d/users/{uid}/role-mappings/clients/{client}", headers=h, json=[role.json()])
    yield login, pw
    httpx.delete(f"{KC}/admin/realms/dwg3d/users/{uid}", headers=h)


def test_real_keycloak_sign_in(kc_user, pg, monkeypatch):
    from dwg3d import api, auth

    monkeypatch.setenv("DWG3D_AUTH", "oidc")
    monkeypatch.setenv("DWG3D_OIDC_ISSUER", f"{PUBLIC}/auth/realms/dwg3d")
    monkeypatch.setenv("DWG3D_OIDC_INTERNAL", f"{KC}/realms/dwg3d")
    monkeypatch.setenv("DWG3D_OIDC_CLIENT_SECRET", os.environ.get("DWG3D_OIDC_CLIENT_SECRET", "dev-client-secret"))
    monkeypatch.setenv("DWG3D_PUBLIC_URL", PUBLIC)             # a redirect URI the realm allows
    monkeypatch.setattr(auth, "_jwks", None)
    login, pw = kc_user
    c = TestClient(api.app)
    r = c.get("/api/auth/login?next=/", follow_redirects=False)
    # the browser's part: Keycloak's sign-in form
    with httpx.Client(follow_redirects=False, timeout=15) as browser:
        page = browser.get(r.headers["location"])
        assert page.status_code == 200
        action = re.search(r'action="([^"]+)"', page.text).group(1).replace("&amp;", "&")
        # Keycloak's cookies are Secure; browsers accept them on http://localhost, httpx does not keep them
        jar = "; ".join(f"{k.name}={k.value}" for k in page.cookies.jar)
        back = browser.post(action, data={"username": login, "password": pw, "credentialId": ""},
                            headers={"Cookie": jar})
        assert back.status_code == 302, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", back.text))[-600:]
    cb = urllib.parse.urlparse(back.headers["location"])
    assert f"{cb.scheme}://{cb.netloc}{cb.path}" == f"{PUBLIC}/api/auth/callback"
    r = c.get(f"/api/auth/callback?{cb.query}", follow_redirects=False)
    assert r.status_code == 303, r.text
    me = c.get("/api/auth/me").json()
    assert me["login"] == login and me["role"] == "catalog_admin" and me["name"] == "Тест Интеграция"
    assert c.get("/api/projects").status_code == 200
    out = c.post("/api/auth/logout").json()
    assert out["logout_url"].startswith(f"{PUBLIC}/auth/realms/dwg3d/protocol/openid-connect/logout")
