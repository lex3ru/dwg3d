import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

S = {"schema": "planning"}


class Item(Base):
    """Предмет (3.3): тип (и модель), поставленный на план этажа. Координаты — мм плана
    (Y вверх), angle — градусы против часовой, z — высота низа предмета над полом этажа.
    Вложенный предмет (parent_id) своей точки не имеет и стоит там, где его вместилище."""

    __tablename__ = "item"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    building_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("building.building.id"), index=True
    )
    floor_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("building.floor.id"), index=True)
    room_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("building.room.id"), index=True
    )
    type_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("catalog.item_type.id"), index=True)
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("catalog.model.id"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("planning.item.id"), index=True
    )
    x: Mapped[float | None] = mapped_column(Float)
    y: Mapped[float | None] = mapped_column(Float)
    angle: Mapped[float] = mapped_column(Float, default=0)
    z: Mapped[float] = mapped_column(Float, default=0)
    label: Mapped[str] = mapped_column(String(100), default="")
    # связанная инвентарная единица (5.5): ключ из учёта, одна единица — не больше одного
    # предмета; что за единица, проверяет модуль связи
    unit_id: Mapped[uuid.UUID | None] = mapped_column(UUID, unique=True)
    # параметры для расчётов (5.3.4 п. 1): наклон, угол обзора камеры, наклон светильника —
    # «модуль.параметр» → значение; что в них, знает модуль расчёта
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1)
