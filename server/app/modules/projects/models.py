import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

S = {"schema": "projects"}


class Project(Base):
    """Проект (5.3.6): предлагаемые изменения расстановки здания. Пока не применён,
    расстановка не меняется."""

    __tablename__ = "project"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    building_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("building.building.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(150), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class Change(Base):
    """Одно изменение проекта над расстановкой: add — новый предмет (все поля), update —
    поля предмета расстановки, remove — убрать его. base — поля предмета расстановки, когда
    проект его тронул: по ним видно, что расстановку с тех пор меняли («устарел»)."""

    __tablename__ = "change"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("projects.project.id", ondelete="CASCADE"), index=True
    )
    floor_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("building.floor.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # add update remove
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    base: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
