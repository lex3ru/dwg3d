"""Ошибки человеческим языком (6.1 п. 6): что не так, где и как исправить.

Ответ сервера на ошибку: {"error": {"code": "...", "message": "...", "field": "..."}}.
`code` — для программы, `message` — для человека, `field` — поле формы, если ошибка в нём.
"""

from typing import Any


class AppError(Exception):
    status = 400

    def __init__(self, message: str, *, code: str = "invalid", field: str | None = None,
                 status: int | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.field = field
        self.details = details
        if status is not None:
            self.status = status

    def body(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.field:
            error["field"] = self.field
        if self.details:
            error["details"] = self.details
        return {"error": error}


class NotAuthenticated(AppError):
    status = 401

    def __init__(self, message: str = "Нужно войти в систему."):
        super().__init__(message, code="not_authenticated")


class Forbidden(AppError):
    status = 403

    def __init__(self, message: str = "Это действие вам недоступно."):
        super().__init__(message, code="forbidden")


class NotFound(AppError):
    status = 404

    def __init__(self, message: str = "Не найдено."):
        super().__init__(message, code="not_found")


class Conflict(AppError):
    """Запись уже изменил кто-то другой (8.3 п. 2) или действие противоречит данным."""

    status = 409

    def __init__(self, message: str, *, code: str = "conflict", field: str | None = None):
        super().__init__(message, code=code, field=field)


def stale(what: str = "Запись") -> Conflict:
    return Conflict(f"{what} уже изменил другой пользователь. Обновите страницу и повторите.",
                    code="stale")
