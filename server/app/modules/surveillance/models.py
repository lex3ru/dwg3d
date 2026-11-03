"""Подключения камер отдельно от геометрии плана (ТЗ 9.2, ADR-0027)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CameraConnection(Base):
    __tablename__ = "connection"
    __table_args__ = {"schema": "surveillance"}

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("planning.item.id", ondelete="CASCADE"), primary_key=True
    )
    address: Mapped[str] = mapped_column(String(2048))
    username: Mapped[str] = mapped_column(String(200), default="")
    password: Mapped[bytes] = mapped_column(LargeBinary, default=b"")
    version: Mapped[int] = mapped_column(Integer, default=1)


class CountingConfig(Base):
    __tablename__ = "counting_config"
    __table_args__ = {"schema": "surveillance"}

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("surveillance.connection.item_id", ondelete="CASCADE"), primary_key=True
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str | None] = mapped_column(String(20))
    settings: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer)


class Passage(Base):
    __tablename__ = "passage"
    __table_args__ = {"schema": "surveillance"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("surveillance.connection.item_id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    door: Mapped[str] = mapped_column(String(100))
    direction: Mapped[str] = mapped_column(String(3))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
