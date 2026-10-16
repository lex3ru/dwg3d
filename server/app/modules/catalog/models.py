import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

S = {"schema": "catalog"}


class Layer(Base):
    """Слой (5.2.1): группа по назначению; добавляется без доработки системы."""

    __tablename__ = "layer"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(9), default="#607D8B")
    icon: Mapped[str] = mapped_column(String(40), default="")
    note: Mapped[str] = mapped_column(String(300), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class CharSet(Base):
    """Набор характеристик (5.2.4): общие для нескольких типов."""

    __tablename__ = "char_set"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)

    characteristics: Mapped[list["Characteristic"]] = relationship(
        order_by="Characteristic.position", lazy="selectin", cascade="all, delete-orphan"
    )


class Characteristic(Base):
    """Характеристика: в наборе (set_id) или своя у типа (type_id). Уровень — где задаётся
    значение: у типа, у модели или у каждой вещи (3.2)."""

    __tablename__ = "characteristic"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("catalog.char_set.id", ondelete="CASCADE"), index=True
    )
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("catalog.item_type.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    kind: Mapped[str] = mapped_column(String(10), default="text")  # text number date bool choice
    unit: Mapped[str] = mapped_column(String(20), default="")
    choices: Mapped[list[str]] = mapped_column(JSONB, default=list)
    level: Mapped[str] = mapped_column(String(10), default="type")  # type model item
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(300), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class TypeSet(Base):
    __tablename__ = "type_set"
    __table_args__ = S

    type_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("catalog.item_type.id", ondelete="CASCADE"), primary_key=True
    )
    set_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("catalog.char_set.id", ondelete="CASCADE"), primary_key=True
    )


class ItemType(Base):
    """Тип (5.2.2): вид предмета. Размеры — мм, цена — руб."""

    __tablename__ = "item_type"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    layer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("catalog.layer.id"), index=True
    )
    width: Mapped[float | None] = mapped_column(Float)
    depth: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    mount: Mapped[str] = mapped_column(String(10), default="floor")  # floor wall ceiling none
    mount_height: Mapped[float | None] = mapped_column(Float)
    model_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("files.file.id"))
    # поворот и масштаб 3D-модели, чтобы она встала по габаритам: {rx, ry, rz, scale}
    model_transform: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model_size: Mapped[list[float] | None] = mapped_column(JSONB)  # м, как в файле
    top_view: Mapped[str] = mapped_column(String(10), default="box")  # box icon
    icon: Mapped[str] = mapped_column(String(40), default="")
    price: Mapped[float | None] = mapped_column(Numeric(14, 2))
    accounting: Mapped[str] = mapped_column(String(10), default="piece")  # piece quantity
    unit: Mapped[str] = mapped_column(String(20), default="шт.")
    life_months: Mapped[int | None] = mapped_column(Integer)
    container: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1)


class Model(Base):
    """Модель (5.2.3): конкретная марка типа со своей ценой."""

    __tablename__ = "model"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    type_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("catalog.item_type.id", ondelete="CASCADE"), index=True
    )
    manufacturer: Mapped[str] = mapped_column(String(150), default="")
    name: Mapped[str] = mapped_column(String(200))
    article: Mapped[str] = mapped_column(String(100), default="")
    supplier: Mapped[str] = mapped_column(String(200), default="")
    price: Mapped[float | None] = mapped_column(Numeric(14, 2))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class Value(Base):
    """Значение характеристики уровня типа (type_id) или модели (model_id). Значения уровня
    «вещь» хранит учёт имущества."""

    __tablename__ = "value"
    __table_args__ = (
        UniqueConstraint("characteristic_id", "type_id", "model_id", name="value_owner"),
        S,
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    characteristic_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("catalog.characteristic.id", ondelete="CASCADE"), index=True
    )
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("catalog.item_type.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("catalog.model.id", ondelete="CASCADE"), index=True
    )
    value: Mapped[Any] = mapped_column(JSONB)


class Purpose(Base):
    """Назначение помещения (5.3.5): высота рабочей поверхности (мм) и норма освещённости."""

    __tablename__ = "purpose"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150))
    surface: Mapped[float] = mapped_column(Float, default=800)
    norm: Mapped[int] = mapped_column(Integer, default=300)
    note: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
