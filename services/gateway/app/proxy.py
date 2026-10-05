"""Passing requests on: /api/<service>/v1/... goes to that service unchanged,
with the caller's token instead of the cookie."""
from __future__ import annotations

from urllib.parse import urlsplit

import httpx
from fastapi import Request
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse
from twin_chassis import Problem
from twin_chassis.log import request_id

from .sessions import Signed

# connection-level headers are not passed either way; the cookie and the host are the gateway's own
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding",
       "upgrade", "host", "content-length"}
DROP_REQUEST = HOP | {"cookie", "authorization", "x-request-id"}
DROP_RESPONSE = HOP | {"set-cookie", "x-request-id"}
SAFE = {"GET", "HEAD", "OPTIONS"}


def check_origin(request: Request, me: Signed) -> None:
    """A changing request made with the cookie must come from our own pages
    (the cookie is sent by the browser on its own; a token is not)."""
    if not me.by_cookie or request.method in SAFE:
        return
    origin = request.headers.get("origin")
    if origin is None:
        return
    ours = urlsplit(request.app.state.config.public_url)
    theirs = urlsplit(origin)
    if (theirs.scheme, theirs.netloc) != (ours.scheme, ours.netloc):
        raise Problem(403, "foreign_origin", "Запрос с чужой страницы отклонён")


async def forward(request: Request, service: str, path: str, me: Signed) -> StreamingResponse:
    upstream = request.app.state.config.services.get(service)
    if upstream is None:
        raise Problem(404, "not_found", f"Нет сервиса «{service}»")
    check_origin(request, me)
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in DROP_REQUEST]
    headers += [("authorization", f"Bearer {me.token}"), ("x-request-id", request_id.get() or "")]
    if request.client:
        headers.append(("x-forwarded-for", request.client.host))
    body = request.stream() if request.method not in SAFE else None
    http: httpx.AsyncClient = request.app.state.http
    try:
        upstream_request = http.build_request(request.method, f"{upstream}/api/{service}/v1/{path}",
                                              params=request.query_params, headers=headers, content=body)
        response = await http.send(upstream_request, stream=True)
    except httpx.HTTPError as ex:
        raise Problem(503, "service_unavailable", f"Сервис «{service}» недоступен", extra={"service": service}) from ex
    return StreamingResponse(
        response.aiter_raw(), status_code=response.status_code,
        headers={k: v for k, v in response.headers.items() if k.lower() not in DROP_RESPONSE},
        background=BackgroundTask(response.aclose))
