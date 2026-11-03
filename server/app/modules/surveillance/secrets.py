"""Ключ установки хранится отдельно от БД в APP_DATA_DIR (ADR-0027)."""

import os
import tempfile

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import config
from app.core.errors import AppError


def cipher() -> Fernet:
    directory = config().data_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "surveillance.key"
    if not path.exists():
        fd, temporary = tempfile.mkstemp(dir=directory, prefix=".camera-key-")
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(Fernet.generate_key())
            try:
                os.link(temporary, path)  # публикуем целый ключ, не заменяя ключ другого worker
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    try:
        return Fernet(path.read_bytes())
    except (ValueError, OSError):
        raise AppError("Недоступен ключ подключений камер на сервере.", status=503) from None


def encrypt(value: str) -> bytes:
    return cipher().encrypt(value.encode()) if value else b""


def decrypt(value: bytes) -> str:
    try:
        return cipher().decrypt(value).decode() if value else ""
    except InvalidToken:
        raise AppError("Не удалось расшифровать пароль камеры. Проверьте ключ установки.",
                       status=503) from None
