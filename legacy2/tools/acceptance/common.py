"""What the acceptance tools share: the stack's address, accounts in Keycloak, signing in as a browser does.

The stack is TWIN_URL (default http://localhost:8090); the bootstrap administrator of Keycloak and the
secrets come from deploy/.env. Accounts the tools make and what they seeded are kept in
tools/acceptance/.state.json (not in git): the passwords are new on every seeding.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("TWIN_URL", "http://localhost:8090").rstrip("/")
STATE = Path(__file__).with_name(".state.json")


def deploy_env() -> dict[str, str]:
    path = ROOT / "deploy" / ".env"
    if not path.exists():
        return {}
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if re.match(r"^[A-Z_]+=", line))


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


class Keycloak:
    """The realm's users through Keycloak's admin API, as the bootstrap administrator."""

    def __init__(self, http: httpx.AsyncClient):
        self.http, self.token = http, ""

    async def __aenter__(self) -> Keycloak:
        env = deploy_env()
        r = await self.http.post(f"{BASE}/kc/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli",
            "username": env.get("KEYCLOAK_ADMIN", "kcadmin"), "password": env.get("KEYCLOAK_ADMIN_PASSWORD", "kcadmin")})
        r.raise_for_status()
        self.token = r.json()["access_token"]
        return self

    async def __aexit__(self, *_) -> None:
        pass

    async def call(self, method: str, path: str, body=None) -> httpx.Response:
        r = await self.http.request(method, f"{BASE}/kc/admin/realms/twin{path}", json=body,
                                    headers={"Authorization": f"Bearer {self.token}"})
        if r.status_code >= 400 and r.status_code != 409:
            raise RuntimeError(f"Keycloak {method} {path}: {r.status_code} {r.text}")
        return r

    async def user(self, username: str, first: str, last: str, admin: bool = False) -> str:
        """Make (or find) the account; give it a new password and return it."""
        password = secrets.token_urlsafe(12)
        await self.call("POST", "/users", {"username": username, "firstName": first, "lastName": last,
                                           "email": f"{username}@example.test", "emailVerified": True, "enabled": True})
        uid = (await self.call("GET", f"/users?username={username}&exact=true")).json()[0]["id"]
        await self.call("PUT", f"/users/{uid}/reset-password", {"type": "password", "value": password, "temporary": False})
        if admin:
            client = (await self.call("GET", "/clients?clientId=twin")).json()[0]["id"]
            role = (await self.call("GET", f"/clients/{client}/roles/dwg3d.admin")).json()
            await self.call("POST", f"/users/{uid}/role-mappings/clients/{client}", [role])
        return password


async def sign_in(username: str, password: str, timeout: float = 60) -> httpx.AsyncClient:
    """A client with the gateway's session cookie, got through the Keycloak form as a browser gets it.
    Cookies are carried by hand: Python's cookie jar files those of the host `localhost` under
    `localhost.local` and never sends them back."""
    jar: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=timeout) as http:
        async def go(method: str, url: str, **kw) -> httpx.Response:
            for _ in range(10):
                r = await http.request(method, url, headers={"Cookie": "; ".join(f"{k}={v}" for k, v in jar.items())}, **kw)
                for line in r.headers.get_list("set-cookie"):
                    name, _, rest = line.partition("=")
                    value = rest.split(";", 1)[0]
                    if "max-age=0" in line.lower() or not value:
                        jar.pop(name.strip(), None)
                    else:
                        jar[name.strip()] = value
                if r.status_code not in (301, 302, 303, 307):
                    return r
                method, url, kw = "GET", str(r.url.join(r.headers["location"])), {}
            raise RuntimeError("слишком много переадресаций")

        page = await go("GET", f"{BASE}/auth/login?next=/")
        tag = next((t for t in re.findall(r"<form[^>]*>", page.text) if "kc-form-login" in t), "")
        form = re.search(r'action="([^"]+)"', tag)
        if form is None:
            raise RuntimeError(f"нет формы входа Keycloak для {username} ({page.status_code} {page.url})")
        await go("POST", html.unescape(form.group(1)), data={"username": username, "password": password})
    session = {k: v for k, v in jar.items() if not k.startswith(("KC_", "AUTH_SESSION", "KEYCLOAK"))}
    client = httpx.AsyncClient(base_url=BASE, timeout=timeout, limits=httpx.Limits(max_connections=20),
                               headers={"Origin": BASE, "Cookie": "; ".join(f"{k}={v}" for k, v in session.items())})
    me = await client.get("/api/me")
    if me.status_code != 200:
        await client.aclose()
        raise RuntimeError(f"вход {username} не удался: /api/me → {me.status_code}")
    return client


def check(r: httpx.Response, *ok: int) -> httpx.Response:
    if r.status_code not in (ok or (200, 201, 204)):
        raise RuntimeError(f"{r.request.method} {r.request.url.path} → {r.status_code}: {r.text[:400]}")
    return r
