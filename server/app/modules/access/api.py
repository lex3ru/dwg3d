"""Программный интерфейс доступа для других модулей и для сборки приложения.

Вход устроен в два шага: человек подтверждает, кто он (сейчас — паролем, `login`; позже —
через Keycloak), и получает сеанс (`_start_session`). Роли, выдачи зданий и проверка прав
от способа входа не зависят, поэтому Keycloak подключается добавлением второго способа
подтверждения, без переделки остального (2.4).
"""

import hashlib
import re
import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.config import config
from app.core.db import DB
from app.core.errors import AppError, Conflict, NotAuthenticated, NotFound, stale
from app.modules.access import passwords
from app.modules.access.models import Account, BuildingGrant, LoginSession
from app.modules.journal import api as journal

COOKIE = "sid"
COOKIE_MAX_AGE = 30 * 24 * 3600  # cookie живёт месяц; сеанс кончается раньше — по бездействию
LOCK_AFTER = 10  # неудачных попыток подряд (8.4 п. 2)
LOCK_FOR = timedelta(minutes=15)
ROLE_TITLES = {"admin": "администратор", "viewer": "просмотр"}
LOGIN_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9._-]{2,50}$")
# с временным паролем можно только это: узнать себя, сменить пароль, выйти (5.7.1)
_ALLOWED_BEFORE_CHANGE = {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}


# ---------------------------------------------------------------- здания

class BuildingDirectory(Protocol):
    """Справочник зданий. Подставляет модуль здания: доступ ниже него и о зданиях знает
    только через этот интерфейс."""

    def names(self, session: Session, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]: ...


_directory: BuildingDirectory | None = None


def set_building_directory(directory: BuildingDirectory | None) -> None:
    global _directory
    _directory = directory


def _building_names(session: Session, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = list(ids)
    if not ids or _directory is None:
        return {}
    return _directory.names(session, ids)


def revoke_building(session: Session, building_id: uuid.UUID) -> None:
    """Здание удалено — его выдачи больше не нужны."""
    session.execute(delete(BuildingGrant).where(BuildingGrant.building_id == building_id))


# ---------------------------------------------------------------- кто делает запрос

def actor_of(account: Account) -> Actor:
    return Actor(user_id=account.id, login=account.login, full_name=account.full_name,
                 role=account.role,  # type: ignore[arg-type]
                 building_ids=frozenset(account.building_ids))


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def resolve_actor(request: Request, session: DB
                  ) -> Actor:
    """Подставляется вместо app.core.auth.current_actor."""
    token = request.cookies.get(COOKIE)
    if not token:
        raise NotAuthenticated()
    row = session.get(LoginSession, _hash(token))
    if row is None:
        raise NotAuthenticated()
    now = datetime.now(UTC)
    if row.last_seen_at < now - timedelta(hours=config().session_idle_hours):
        raise NotAuthenticated(f"Сеанс завершён после {config().session_idle_hours} часов "
                               "бездействия. Войдите снова.")
    account = session.get(Account, row.account_id)
    if account is None or account.blocked:
        raise NotAuthenticated("Учётная запись заблокирована. Обратитесь к администратору.")
    if now - row.last_seen_at > timedelta(minutes=1):
        row.last_seen_at = now
    if account.must_change_password and request.url.path not in _ALLOWED_BEFORE_CHANGE:
        raise AppError("Сначала смените временный пароль.", code="must_change_password",
                       status=403)
    return actor_of(account)


def actor_for_token(session: Session, token: str | None) -> Actor | None:
    """Для WebSocket: действующий по ключу сеанса или None."""
    if not token:
        return None
    row = session.get(LoginSession, _hash(token))
    if row is None or row.last_seen_at < datetime.now(UTC) - timedelta(
            hours=config().session_idle_hours):
        return None
    account = session.get(Account, row.account_id)
    if account is None or account.blocked or account.must_change_password:
        return None
    return actor_of(account)


# ---------------------------------------------------------------- вход и выход

@dataclass
class LoginResult:
    token: str | None = None
    account: Account | None = None
    error: AppError | None = None


_BAD = "Неверное имя или пароль."


def login(session: Session, login_name: str, password: str, *, ip: str | None = None,
          user_agent: str | None = None) -> LoginResult:
    """Неудача — не исключение: попытка должна остаться в журнале и в счётчике, поэтому
    транзакция фиксируется и при отказе."""
    name = login_name.strip()
    account = session.scalars(select(Account).where(func.lower(Account.login) == name.lower())
                              .with_for_update()).first()
    now = datetime.now(UTC)
    if account is None:
        passwords.verify(None, password)
        journal.record(session, None, "auth.login_failed",
                       f"Неудачная попытка входа: имени «{name[:50]}» нет", entity="auth:login",
                       actor_name="—", after={"ip": ip})
        return LoginResult(error=AppError(_BAD, code="bad_credentials", status=401))

    def fail(summary: str, error: AppError) -> LoginResult:
        journal.record(session, None, "auth.login_failed", summary,
                       entity=f"user:{account.id}", actor_name=account.full_name,
                       after={"ip": ip})
        return LoginResult(error=error)

    if account.blocked:
        return fail(f"Попытка входа в заблокированную учётную запись «{account.login}»",
                    AppError("Учётная запись заблокирована. Обратитесь к администратору.",
                             code="blocked", status=401))
    if account.locked_until and account.locked_until > now:
        return fail(f"Попытка входа «{account.login}» во время блокировки",
                    _locked_error(account.locked_until - now))
    if not passwords.verify(account.password_hash, password):
        account.failed_attempts += 1
        if account.failed_attempts >= LOCK_AFTER:
            account.failed_attempts = 0
            account.locked_until = now + LOCK_FOR
            return fail(f"Вход «{account.login}» заблокирован на 15 минут после "
                        f"{LOCK_AFTER} неудачных попыток", _locked_error(LOCK_FOR))
        return fail(f"Неверный пароль при входе «{account.login}»",
                    AppError(_BAD, code="bad_credentials", status=401))

    account.failed_attempts = 0
    account.locked_until = None
    account.last_login_at = now
    token = _start_session(session, account, "password", ip, user_agent)
    journal.record(session, actor_of(account), "auth.login",
                   f"Вход «{account.login}»", entity=f"user:{account.id}", after={"ip": ip})
    return LoginResult(token=token, account=account)


def _locked_error(left: timedelta) -> AppError:
    minutes = max(1, int(left.total_seconds() + 59) // 60)
    return AppError(f"Слишком много неудачных попыток. Вход откроется через {minutes} мин.",
                    code="locked", status=401)


def _start_session(session: Session, account: Account, method: str, ip: str | None,
                   user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    session.add(LoginSession(token_hash=_hash(token), account_id=account.id, method=method,
                             ip=ip, user_agent=(user_agent or "")[:300] or None))
    return token


def logout(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(LoginSession).where(LoginSession.token_hash == _hash(token)))


def _end_sessions(session: Session, account_id: uuid.UUID, keep: str | None = None) -> None:
    query = delete(LoginSession).where(LoginSession.account_id == account_id)
    if keep:
        query = query.where(LoginSession.token_hash != _hash(keep))
    session.execute(query)


def purge_sessions(session: Session) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=config().session_idle_hours)
    result = session.execute(delete(LoginSession).where(LoginSession.last_seen_at < cutoff))
    return result.rowcount or 0  # type: ignore[attr-defined]


def change_password(session: Session, actor: Actor, current: str, new: str,
                    token: str | None) -> Account:
    account = _get(session, actor.user_id)
    if not passwords.verify(account.password_hash, current):
        raise AppError("Текущий пароль введён неверно.", field="current", code="bad_password")
    passwords.check_new(new, account.login, field="new")
    if new == current:
        raise AppError("Новый пароль должен отличаться от текущего.", field="new",
                       code="password_same")
    account.password_hash = passwords.hash_password(new)
    account.must_change_password = False
    account.version += 1
    _end_sessions(session, account.id, keep=token)
    journal.record(session, actor, "user.password_change", "Сменил свой пароль",
                   entity=f"user:{account.id}")
    return account


# ---------------------------------------------------------------- учётные записи

def view(session: Session, account: Account) -> dict[str, object]:
    names = _building_names(session, account.building_ids)
    return {
        "id": account.id, "login": account.login, "full_name": account.full_name,
        "role": account.role,
        "buildings": [{"id": b, "name": names.get(b, "здание удалено")}
                      for b in account.building_ids],
        "blocked": account.blocked,
        "locked_until": account.locked_until
        if account.locked_until and account.locked_until > datetime.now(UTC) else None,
        "must_change_password": account.must_change_password,
        "last_login_at": account.last_login_at, "created_at": account.created_at,
        "version": account.version,
    }


def accounts(session: Session) -> list[Account]:
    return list(session.scalars(select(Account).order_by(Account.full_name)))


def _get(session: Session, account_id: uuid.UUID) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise NotFound("Учётная запись не найдена.")
    return account


def get(session: Session, account_id: uuid.UUID) -> Account:
    return _get(session, account_id)


def _snapshot(session: Session, account: Account) -> dict[str, object]:
    names = _building_names(session, account.building_ids)
    return {"login": account.login, "full_name": account.full_name,
            "role": ROLE_TITLES[account.role],
            "buildings": sorted(names.get(b, str(b)) for b in account.building_ids),
            "blocked": account.blocked}


def _check_buildings(session: Session, role: str, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    if role == "admin":
        return []  # администратору доступны все здания (2.2)
    ids = list(dict.fromkeys(ids))
    known = _building_names(session, ids)
    if len(known) != len(ids):
        raise AppError("Такого здания нет — обновите страницу и выберите заново.",
                       field="building_ids", code="unknown_building")
    return ids


def _check_profile(full_name: str, role: str) -> None:
    if not full_name.strip():
        raise AppError("Укажите ФИО.", field="full_name", code="required")
    if role not in ROLE_TITLES:
        raise AppError("Роль — администратор или просмотр.", field="role", code="invalid")


def _active_admins(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Account)
                          .where(Account.role == "admin", Account.blocked.is_(False))) or 0


def create(session: Session, actor: Actor | None, *, login_name: str, full_name: str,
           role: str, building_ids: list[uuid.UUID], password: str | None = None
           ) -> tuple[Account, str]:
    """Новая учётная запись с временным паролем; возвращает её и этот пароль."""
    login_name = login_name.strip()
    if not LOGIN_RE.match(login_name):
        raise AppError("Имя для входа — от 2 до 50 букв, цифр, точек, дефисов и "
                       "подчёркиваний, без пробелов.", field="login", code="invalid")
    _check_profile(full_name, role)
    exists = session.scalar(select(Account.id).where(
        func.lower(Account.login) == login_name.lower()))
    if exists:
        raise Conflict(f"Имя для входа «{login_name}» уже занято.", field="login",
                       code="login_taken")
    temporary = password or passwords.temporary()
    passwords.check_new(temporary, login_name)
    account = Account(id=uuid.uuid4(), login=login_name, full_name=full_name.strip(),
                      role=role, password_hash=passwords.hash_password(temporary),
                      must_change_password=True, blocked=False, failed_attempts=0, version=1)
    account.grants = [BuildingGrant(building_id=b)
                      for b in _check_buildings(session, role, building_ids)]
    session.add(account)
    session.flush()
    journal.record(session, actor, "user.create",
                   f"Заведена учётная запись «{account.login}» ({account.full_name}), "
                   f"роль «{ROLE_TITLES[role]}»", entity=f"user:{account.id}",
                   after=_snapshot(session, account))
    return account, temporary


def update(session: Session, actor: Actor, account_id: uuid.UUID, *, version: int,
           full_name: str | None = None, role: str | None = None,
           building_ids: list[uuid.UUID] | None = None) -> Account:
    account = _get(session, account_id)
    if account.version != version:
        raise stale("Учётную запись")
    before = _snapshot(session, account)
    new_role = role or account.role
    _check_profile(full_name if full_name is not None else account.full_name, new_role)
    if new_role != "admin" and account.role == "admin":
        if account.id == actor.user_id:
            raise Conflict("Снять с себя роль администратора нельзя — это сделает другой "
                           "администратор.", field="role", code="self")
        if not account.blocked and _active_admins(session) <= 1:
            raise Conflict("Это последний администратор: сначала назначьте другого.",
                           field="role", code="last_admin")
    if full_name is not None:
        account.full_name = full_name.strip()
    account.role = new_role
    if building_ids is not None or new_role == "admin":
        ids = _check_buildings(session, new_role,
                               building_ids if building_ids is not None else [])
        account.grants = [BuildingGrant(building_id=b) for b in ids]
    after = _snapshot(session, account)
    was, became = journal.changes(before, after)
    if not became:
        return account
    account.version += 1
    session.flush()
    journal.record(session, actor, "user.update", f"Изменена учётная запись «{account.login}»",
                   entity=f"user:{account.id}", before=was, after=became)
    return account


def reset_password(session: Session, actor: Actor | None, account_id: uuid.UUID,
                   password: str | None = None) -> tuple[Account, str]:
    account = _get(session, account_id)
    temporary = password or passwords.temporary()
    passwords.check_new(temporary, account.login)
    account.password_hash = passwords.hash_password(temporary)
    account.must_change_password = True
    account.failed_attempts = 0
    account.locked_until = None
    account.version += 1
    _end_sessions(session, account.id)
    journal.record(session, actor, "user.password_reset",
                   f"Сброшен пароль «{account.login}»", entity=f"user:{account.id}")
    return account, temporary


def set_blocked(session: Session, actor: Actor, account_id: uuid.UUID, blocked: bool
                ) -> Account:
    account = _get(session, account_id)
    if account.blocked == blocked:
        return account
    if blocked:
        if account.id == actor.user_id:
            raise Conflict("Заблокировать самого себя нельзя.", code="self")
        if account.role == "admin" and _active_admins(session) <= 1:
            raise Conflict("Это последний администратор: его нельзя заблокировать.",
                           code="last_admin")
        _end_sessions(session, account.id)
    account.blocked = blocked
    account.failed_attempts = 0
    account.locked_until = None
    account.version += 1
    journal.record(session, actor, "user.block" if blocked else "user.unblock",
                   f"{'Заблокирована' if blocked else 'Разблокирована'} учётная запись "
                   f"«{account.login}»", entity=f"user:{account.id}",
                   before={"blocked": not blocked}, after={"blocked": blocked})
    return account


def find(session: Session, login_name: str) -> Account | None:
    return session.scalars(select(Account).where(
        func.lower(Account.login) == login_name.strip().lower())).first()


def create_first_admin(session: Session, login_name: str, full_name: str,
                       password: str | None = None) -> str | None:
    """Первый администратор при установке; None — администратор уже есть."""
    if session.scalar(select(func.count()).select_from(Account)
                      .where(Account.role == "admin")):
        return None
    _, temporary = create(session, None, login_name=login_name, full_name=full_name,
                          role="admin", building_ids=[], password=password)
    return temporary
