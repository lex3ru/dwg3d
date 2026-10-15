"""Every failure is application/problem+json (docs/CONTRACTS.md, 1.5).

Raise Problem from anywhere; a trace never reaches the client.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = logging.getLogger("twin.errors")
TITLES = {400: "Неверный запрос", 401: "Требуется вход", 403: "Действие запрещено", 404: "Не найдено",
          409: "Конфликт", 422: "Данные не прошли проверку", 500: "Внутренняя ошибка", 502: "Сервис ответил ошибкой",
          503: "Сервис недоступен"}


class Problem(Exception):
    def __init__(self, status: int, code: str, detail: str | None = None, *, title: str | None = None,
                 errors: list[dict] | None = None, headers: dict | None = None, extra: dict | None = None):
        super().__init__(detail or code)
        self.status, self.code, self.detail = status, code, detail
        self.title = title or TITLES.get(status, "Ошибка")
        self.errors, self.headers, self.extra = errors, headers, extra or {}

    def body(self) -> dict:
        o = {"type": f"about:blank#{self.code}", "title": self.title, "status": self.status, "code": self.code}
        if self.detail:
            o["detail"] = self.detail
        if self.errors:
            o["errors"] = self.errors
        return {**o, **self.extra}

    def response(self) -> JSONResponse:
        return JSONResponse(self.body(), self.status, headers=self.headers, media_type="application/problem+json")


def install(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def problem(_: Request, ex: Problem):
        return ex.response()

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, ex: RequestValidationError):
        errors = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
                  for e in ex.errors()]
        return Problem(422, "invalid", errors=errors).response()

    @app.exception_handler(HTTPException)
    async def http(_: Request, ex: HTTPException):
        codes = {401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}
        detail = ex.detail if isinstance(ex.detail, str) and ex.status_code != 404 else None
        return Problem(ex.status_code, codes.get(ex.status_code, "error"), detail,
                       headers=getattr(ex, "headers", None)).response()

    @app.exception_handler(Exception)
    async def crash(_: Request, ex: Exception):
        log.error("unhandled error", exc_info=ex)
        return Problem(500, "internal").response()
