"""Sign-in through Keycloak: authorization code flow with PKCE.

The browser is sent to the realm's public address; the gateway itself talks
to the realm by its internal one.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from twin_chassis import Problem, Settings

from .config import GatewayConfig

STATE_TTL = 600


class SignInFailed(Exception):
    """Keycloak refused: a wrong or reused code, an expired refresh token."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Oidc:
    def __init__(self, settings: Settings, config: GatewayConfig, http: httpx.AsyncClient):
        self.settings, self.config, self.http = settings, config, http
        self.redirect_uri = f"{config.public_url}/auth/callback"

    # ------------------------------------------- the signed sign-in state ---
    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self.config.secret.encode(), body.encode(), hashlib.sha256).digest())

    def pack(self, value: dict) -> str:
        body = _b64(json.dumps({**value, "exp": int(time.time()) + STATE_TTL}).encode())
        return f"{body}.{self._sign(body)}"

    def unpack(self, packed: str | None) -> dict | None:
        try:
            body, signature = (packed or "").split(".")
            if not hmac.compare_digest(signature, self._sign(body)):
                return None
            value = json.loads(_unb64(body))
            return value if value["exp"] >= time.time() else None
        except (ValueError, KeyError):
            return None

    # -------------------------------------------------------------- steps ---
    def begin(self, next_path: str) -> tuple[str, str]:
        """(where to send the browser, what to keep in its cookie meanwhile)."""
        state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        query = urlencode({"client_id": self.settings.oidc_client_id, "redirect_uri": self.redirect_uri,
                           "response_type": "code", "scope": "openid profile email", "state": state,
                           "code_challenge": challenge, "code_challenge_method": "S256"})
        url = f"{self.settings.oidc_issuer}/protocol/openid-connect/auth?{query}"
        return url, self.pack({"state": state, "verifier": verifier, "next": next_path})

    async def _token(self, form: dict) -> dict:
        try:
            r = await self.http.post(f"{self.settings.oidc_internal}/protocol/openid-connect/token", timeout=10, data={
                **form, "client_id": self.settings.oidc_client_id, "client_secret": self.config.client_secret})
        except httpx.HTTPError as ex:
            raise Problem(503, "auth_unavailable", "Сервис входа недоступен") from ex
        if r.status_code >= 500:
            raise Problem(503, "auth_unavailable", "Сервис входа недоступен")
        if r.status_code != 200:
            raise SignInFailed(r.text[:200])
        return r.json()

    async def exchange(self, code: str, verifier: str) -> dict:
        return await self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
                                  "code_verifier": verifier})

    async def refresh(self, refresh_token: str) -> dict:
        return await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def logout_url(self, id_token: str | None) -> str:
        query = {"post_logout_redirect_uri": f"{self.config.public_url}/", "client_id": self.settings.oidc_client_id}
        if id_token:
            query["id_token_hint"] = id_token
        return f"{self.settings.oidc_issuer}/protocol/openid-connect/logout?{urlencode(query)}"
