"""Приём загружаемого файла (ADR-0012): тело запроса читается только после проверки входа и
прав и не больше лимита своего вида (7.3 п. 4, R-014, R-040).

FastAPI разбирает параметры `UploadFile`, `File` и `Form` раньше зависимостей: тело ложится во
временный файл и без входа. Поэтому маршрут загрузки объявляет сначала вход (`actor: Admin`),
а файл — зависимостью `receive(...)` после него. Она отказывает по `Content-Length` до чтения,
считает байты при приёме и обрывает его на лимите — так и у тела без `Content-Length`.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, BinaryIO

from fastapi import Depends, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.db import DB
from app.core.errors import AppError

MB = 1024 * 1024
MAX_FILE = 300 * MB  # общий предел файла; лимиты видов в настройках — не больше
FORM_OVERHEAD = MB  # заголовки частей формы и её поля сверх самого файла

# что за файл («Чертёж») и наибольший размер в байтах — по настройкам модуля
Limit = Callable[[Session, Request], tuple[str, int]]


@dataclass
class Upload:
    """Принятый файл и поля формы рядом с ним."""

    file: BinaryIO
    name: str
    size: int
    limit: int
    fields: dict[str, str]


class _TooLarge(MultiPartException):
    pass


def too_large(what: str, limit: int) -> AppError:
    return AppError(f"{what} больше {limit // MB} МБ. Наибольший размер меняет администратор "
                    "в «Настройках».", code="too_large", status=413)


def receive(limit: Limit) -> Any:
    """Зависимость маршрута загрузки — файл из поля `file` формы:
    `file: Annotated[Upload, receive(...)]` после зависимости входа."""

    async def dependency(request: Request, session: DB) -> AsyncIterator[Upload]:
        what, most = await run_in_threadpool(limit, session, request)
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > most + FORM_OVERHEAD:
            raise too_large(what, most)
        if not request.headers.get("content-type", "").startswith("multipart/form-data"):
            raise AppError("Нужна форма с файлом.", code="bad_form")

        async def counted() -> AsyncIterator[bytes]:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > most + FORM_OVERHEAD:
                    raise _TooLarge("too large")
                yield chunk

        # при ошибке разбора парсер сам закрывает начатые файлы
        parser = MultiPartParser(request.headers, counted(), max_files=1, max_fields=20)
        try:
            form = await parser.parse()
        except _TooLarge:
            raise too_large(what, most) from None
        except MultiPartException as e:
            raise AppError(f"Форма с файлом повреждена: {e.message}", code="bad_form") from None
        try:
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise AppError("Выберите файл.", code="no_file", field="file")
            size = file.size or 0
            if size > most:
                raise too_large(what, most)
            fields = {k: v for k, v in form.multi_items() if isinstance(v, str)}
            yield Upload(file=file.file, name=file.filename or "", size=size, limit=most,
                         fields=fields)
        finally:
            await form.close()

    # как у сессии базы: файл закрывается, когда маршрут отработал
    return Depends(dependency, scope="function")


def form(**fields: str) -> dict[str, Any]:
    """Описание формы загрузки для OpenAPI (`openapi_extra`): тело читает зависимость, и FastAPI
    его не видит. fields — прочие поля формы и их тип JSON Schema."""
    properties: dict[str, Any] = {"file": {"type": "string", "format": "binary"}}
    properties.update({k: {"type": v} for k, v in fields.items()})
    schema = {"type": "object", "properties": properties, "required": ["file"]}
    return {"requestBody": {"required": True,
                            "content": {"multipart/form-data": {"schema": schema}}}}
