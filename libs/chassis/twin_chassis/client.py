"""Calling another service: with the user's token when acting for a user,
with this service's own token when reacting to an event.

    client = ServiceClient(settings, {"import": "http://import:8000"})
    result = await client.get("import", f"/builds/{build_id}/result")

The service's own token comes from Keycloak (client credentials of the client
twin-svc-<service>) and is renewed before it expires.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from .errors import Problem
from .log import request_id
from .settings import Settings


class ServiceClient:
    def __init__(self, settings: Settings, services: dict[str, str], http: httpx.AsyncClient | None = None):
        self.settings, self.services = settings, {k: v.rstrip("/") for k, v in services.items()}
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(30, connect=3))
        self._token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def token(self) -> str:
        async with self._lock:
            if self._token and time.monotonic() < self._expires:
                return self._token
            s = self.settings
            if not s.service_secret:
                raise Problem(503, "service_account_missing", f"У сервиса {s.service} не задан TWIN_SERVICE_SECRET")
            try:
                r = await self.http.post(f"{s.oidc_internal}/protocol/openid-connect/token", timeout=10, data={
                    "grant_type": "client_credentials", "client_id": f"twin-svc-{s.service}",
                    "client_secret": s.service_secret})
            except httpx.HTTPError as ex:
                raise Problem(503, "auth_unavailable", "Сервис входа недоступен") from ex
            if r.status_code != 200:
                raise Problem(503, "auth_unavailable",
                              f"Keycloak не выдал токен сервису {s.service} ({r.status_code})")
            body = r.json()
            self._token = body["access_token"]
            self._expires = time.monotonic() + max(5, int(body.get("expires_in", 60)) - 20)
            return self._token

    async def request(self, method: str, service: str, path: str, *, token: str | None = None,
                      **kw) -> httpx.Response:
        """`path` is relative to /api/<service>/v1. Without `token` the service's own is used.
        A service that cannot be reached is Problem 503; its answers are returned as they are."""
        base = self.services.get(service)
        if base is None:
            raise Problem(503, "service_unavailable", f"Адрес сервиса «{service}» не настроен",
                          extra={"service": service})
        headers = {"Authorization": f"Bearer {token or await self.token()}", **(kw.pop("headers", None) or {})}
        if (rid := request_id.get()) is not None:
            headers["X-Request-ID"] = rid
        try:
            return await self.http.request(method, f"{base}/api/{service}/v1{path}", headers=headers, **kw)
        except httpx.HTTPError as ex:
            raise Problem(503, "service_unavailable", f"Сервис «{service}» недоступен",
                          extra={"service": service}) from ex

    async def get(self, service: str, path: str, **kw) -> httpx.Response:
        return await self.request("GET", service, path, **kw)

    async def close(self) -> None:
        await self.http.aclose()


def services_from_env(value: str | None) -> dict[str, str]:
    """"import=http://import:8000,buildings=http://buildings:8000" -> dict."""
    return dict(pair.strip().split("=", 1) for pair in (value or "").split(",") if "=" in pair)
