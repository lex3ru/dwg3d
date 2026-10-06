"""Asking the services on behalf of the user: the token goes along, a silent service is a known answer."""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import Request
from twin_chassis import Problem

from .sessions import Signed


class Answer:
    """What a service said: `body` when it answered 2xx, else `status` and the problem (or None when away)."""

    def __init__(self, status: int | None, body: Any):
        self.status, self.body = status, body

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def away(self) -> bool:
        return self.status is None or self.status >= 500


async def ask(request: Request, who: Signed, service: str, path: str, *, method: str = "GET",
              params: dict | None = None, json: Any = None, wait: float = 30) -> Answer:
    base = request.app.state.config.services.get(service)
    if base is None:
        return Answer(None, None)
    try:
        r = await request.app.state.http.request(method, f"{base}/api/{service}/v1{path}", params=params, json=json,
                                                 timeout=wait, headers={"Authorization": f"Bearer {who.token}"})
    except httpx.HTTPError:
        return Answer(None, None)
    try:
        body = r.json() if r.content else None
    except ValueError:
        body = None
    return Answer(r.status_code, body)


def required(answer: Answer, service: str) -> Any:
    """The body of an answer the request cannot do without; the service's refusal is passed on as it is."""
    if answer.ok:
        return answer.body
    if answer.away:
        raise Problem(503, "service_unavailable", f"Сервис «{service}» недоступен", extra={"service": service})
    body = answer.body if isinstance(answer.body, dict) else {}
    raise Problem(answer.status, body.get("code", "error"), body.get("detail", f"Сервис «{service}» отказал"))


async def every(request: Request, who: Signed, service: str, path: str, params: dict | None = None,
                *, limit: int = 20000) -> list[dict]:
    """All items of a paged list (`items`, `next`), up to `limit`."""
    items: list[dict] = []
    cursor: int | None = 0
    while cursor is not None and len(items) < limit:
        params_ = {**(params or {}), "limit": 500, "cursor": cursor}
        page = required(await ask(request, who, service, path, params=params_), service)
        items.extend(page.get("items") or [])
        cursor = page.get("next")
    return items
