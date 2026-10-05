"""JSON log lines; every line of a request carries its id.

The id comes from X-Request-ID (the gateway sets it) or is made here, is sent
on to other services by whoever calls them, and returns in the response.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("twin_request_id", default=None)
_service = "?"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        o = {"time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname.lower(),
             "service": _service, "logger": record.name, "message": record.getMessage()}
        if (rid := request_id.get()) is not None:
            o["request_id"] = rid
        o.update(getattr(record, "fields", {}))
        if record.exc_info:
            o["trace"] = self.formatException(record.exc_info)
        return json.dumps(o, ensure_ascii=False, default=str)


def setup(service: str) -> None:
    global _service
    _service = service
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
    logging.getLogger("uvicorn.access").disabled = True     # replaced by RequestLog


class RequestLog:
    """ASGI middleware: the request id, and one line per request."""

    def __init__(self, app):
        self.app = app
        self.log = logging.getLogger("twin.request")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        rid = headers.get(b"x-request-id", b"").decode()[:64] or uuid.uuid4().hex
        token = request_id.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if scope["path"] != "/healthz":
                self.log.info("%s %s -> %s", scope["method"], scope["path"], status, extra={"fields": {
                    "method": scope["method"], "path": scope["path"], "status": status,
                    "ms": round((time.perf_counter() - started) * 1000, 1)}})
            request_id.reset(token)
