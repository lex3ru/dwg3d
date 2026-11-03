"""Подключения камер отдельно от геометрии плана (ТЗ 9.2, ADR-0027)."""

import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
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
