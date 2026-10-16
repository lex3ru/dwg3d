import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Account(Base):
    """Учётная запись. Пароль — хеш Argon2; у записи, входящей только через Keycloak
    (2.4, позже), пароля нет."""

    __tablename__ = "account"
    __table_args__ = (
        Index("uq_account_login", text("lower(login)"), unique=True),
        CheckConstraint("role IN ('admin', 'viewer')", name="role"),
        {"schema": "access"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    login: Mapped[str] = mapped_column(String(50))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str | None] = mapped_column(Text)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    # растёт при каждом изменении; правка со старой версией отклоняется (8.3 п. 2)
    version: Mapped[int] = mapped_column(Integer, default=1)

    grants: Mapped[list["BuildingGrant"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin")

    @property
    def building_ids(self) -> list[uuid.UUID]:
        return sorted((g.building_id for g in self.grants), key=str)


class BuildingGrant(Base):
    """«Просмотр» выдаётся на здание (2.3). Ссылка на здание — без внешнего ключа: модуль
    здания выше доступа и сам отзывает выдачи удалённого здания."""

    __tablename__ = "building_grant"
    __table_args__ = {"schema": "access"}

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("access.account.id", ondelete="CASCADE"), primary_key=True)
    building_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, index=True)


class LoginSession(Base):
    """Сеанс входа. В cookie — случайный ключ, здесь — его SHA-256. Как человек вошёл
    (`method`: пароль, позже Keycloak), на права не влияет."""

    __tablename__ = "login_session"
    __table_args__ = {"schema": "access"}

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("access.account.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(20), default="password")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                   server_default=func.now())
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))
