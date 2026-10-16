import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Building(Base):
    __tablename__ = "building"
    __table_args__ = {"schema": "building"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(300), default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1)


class Floor(Base):
    """Этаж: отметка пола и высота — в мм; план — документ (plan.py) со своей версией."""

    __tablename__ = "floor"
    __table_args__ = {"schema": "building"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    building_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("building.building.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer)
    elevation: Mapped[float] = mapped_column(Float, default=0)
    height: Mapped[float] = mapped_column(Float, default=3300)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    plan_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class Room(Base):
    """Помещение — строка таблицы, потому что на него ссылаются предметы, инвентарные
    единицы и история (9.4 п. 1). Убранное помещение не удаляется, а уходит в архив;
    continued_by — какое помещение его продолжило (объединение, 5.1.6)."""

    __tablename__ = "room"
    __table_args__ = {"schema": "building"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    building_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("building.building.id", ondelete="CASCADE"), index=True)
    floor_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("building.floor.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(30), default="")
    name: Mapped[str] = mapped_column(String(200), default="")
    purpose_id: Mapped[str | None] = mapped_column(String(64))
    area: Mapped[float] = mapped_column(Float, default=0)  # м²
    outline: Mapped[list[list[float]]] = mapped_column(JSONB, default=list)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    continued_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("building.room.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())


class Lift(Base):
    """Лифт: шахта ставится один раз на все этажи, которые она пересекает (5.1.4 п. 3).
    (x, y) — центр шахты, w × d — её размеры, angle — поворот; двери — на этажах stops,
    со стороны door_side (0 — по оси +Y шахты, 1 — +X, 2 — −Y, 3 — −X)."""

    __tablename__ = "lift"
    __table_args__ = {"schema": "building"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    building_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("building.building.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50), default="")
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    w: Mapped[float] = mapped_column(Float, default=2000)
    d: Mapped[float] = mapped_column(Float, default=2000)
    angle: Mapped[float] = mapped_column(Float, default=0)
    door_side: Mapped[int] = mapped_column(Integer, default=0)
    floor_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID))
    stop_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID))
