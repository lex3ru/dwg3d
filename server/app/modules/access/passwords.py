"""Пароли (8.4 п. 2): Argon2, не короче 10 знаков."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.errors import AppError

MIN_LENGTH = 10
_hasher = PasswordHasher()
# чтобы проверка несуществующего имени шла столько же, сколько существующего
_DUMMY = _hasher.hash("dummy-password-for-timing")
# без похожих знаков: 0/O, 1/l/I
_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def check_new(password: str, login: str, field: str = "password") -> None:
    if len(password) < MIN_LENGTH:
        raise AppError(f"Пароль должен быть не короче {MIN_LENGTH} знаков.", field=field,
                       code="password_short")
    if password.strip().lower() == login.strip().lower():
        raise AppError("Пароль не должен совпадать с именем для входа.", field=field,
                       code="password_weak")


def temporary() -> str:
    """Временный пароль для выдачи человеку: «Hk7m-Qp3x-Zr9t»."""
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3))
