"""Учёт имущества (5.4). Место хранения — строкой-ключом: «r:<помещение>», «w:<склад>»,
«c:<ячейка склада>». Текущее состояние единицы — в её строке; как она менялась (место,
состояние, оценка) — событиями документов: по ним — состояние и стоимость на любую дату.
Остатки количественного учёта — только движениями документов."""

import datetime as dt
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

S = {"schema": "inventory"}


class Warehouse(Base):
    """Склад (5.4.1): в здании и помещении или вне здания."""

    __tablename__ = "warehouse"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150))
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("building.building.id"), index=True
    )
    room_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("building.room.id"))
    note: Mapped[str] = mapped_column(String(300), default="")
    label_code: Mapped[str] = mapped_column(String(24), unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class Cell(Base):
    """Ячейка склада: стеллаж, полка — один уровень, своя метка."""

    __tablename__ = "cell"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("inventory.warehouse.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer, default=0)
    label_code: Mapped[str] = mapped_column(String(24), unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Unit(Base):
    """Инвентарная единица (3.4, 5.4.2)."""

    __tablename__ = "unit"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(40), unique=True)
    type_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("catalog.item_type.id"), index=True)
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("catalog.model.id"), index=True
    )
    serial: Mapped[str] = mapped_column(String(100), default="")
    place: Mapped[str] = mapped_column(String(50), index=True)
    # здание и этаж места — для фильтров, прав «просмотра» и итогов
    building_id: Mapped[uuid.UUID | None] = mapped_column(UUID, index=True)
    floor_id: Mapped[uuid.UUID | None] = mapped_column(UUID, index=True)
    # in_use, broken, repair, storage, written_off
    state: Mapped[str] = mapped_column(String(20), default="in_use", index=True)
    responsible: Mapped[str] = mapped_column(String(150), default="")
    department: Mapped[str] = mapped_column(String(150), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    commissioned_on: Mapped[dt.date] = mapped_column(Date)
    life_months: Mapped[int | None] = mapped_column(Integer)
    # переоценка (5.4.5 п. 2): новая стоимость на дату
    value_base: Mapped[float | None] = mapped_column(Numeric(14, 2))
    value_date: Mapped[dt.date | None] = mapped_column(Date)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("inventory.unit.id"), index=True
    )
    photo_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("files.file.id"))
    label_code: Mapped[str] = mapped_column(String(24), unique=True)
    written_off_on: Mapped[dt.date | None] = mapped_column(Date)
    writeoff_reason: Mapped[str] = mapped_column(String(300), default="")
    created_doc_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1)


class UnitFile(Base):
    """Фото и документы единицы (5.4.2 п. 3)."""

    __tablename__ = "unit_file"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("inventory.unit.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("files.file.id"))
    kind: Mapped[str] = mapped_column(String(10), default="doc")  # photo doc
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UnitEvent(Base):
    """Что стало с единицей после документа: место, состояние, оценка — на дату."""

    __tablename__ = "unit_event"
    __table_args__ = S

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("inventory.unit.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID, index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # документ или room_merge
    place: Mapped[str] = mapped_column(String(50))
    building_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    floor_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    state: Mapped[str] = mapped_column(String(20))
    value_base: Mapped[float | None] = mapped_column(Numeric(14, 2))
    value_date: Mapped[dt.date | None] = mapped_column(Date)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)


class UnitChange(Base):
    """Правка карточки без документа (5.4.2 п. 5): было → стало, с откатом."""

    __tablename__ = "unit_change"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("inventory.unit.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_name: Mapped[str] = mapped_column(String(200), default="")
    before: Mapped[dict[str, Any]] = mapped_column(JSONB)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rolled_back: Mapped[bool] = mapped_column(Boolean, default=False)


class Document(Base):
    """Документ учёта (5.4.4): черновик → проведён; отменённый остаётся со ссылкой на
    обратный документ."""

    __tablename__ = "document"
    __table_args__ = (UniqueConstraint("kind", "number", name="document_number"), S)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    # opening receipt transfer repair writeoff revaluation
    kind: Mapped[str] = mapped_column(String(20), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="draft", index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    from_place: Mapped[str | None] = mapped_column(String(50))
    to_place: Mapped[str | None] = mapped_column(String(50))
    basis: Mapped[str] = mapped_column(String(300), default="")
    supplier: Mapped[str] = mapped_column(String(200), default="")
    contractor: Mapped[str] = mapped_column(String(200), default="")
    repair: Mapped[str | None] = mapped_column(String(10))  # send return
    repair_cost: Mapped[float | None] = mapped_column(Numeric(14, 2))
    reason: Mapped[str] = mapped_column(String(300), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    cancels_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("inventory.document.id"))
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(200), default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[str] = mapped_column(String(200), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class DocLine(Base):
    """Строка документа: существующая единица, новые единицы (приход, ввод остатков) или
    количество типа (модели)."""

    __tablename__ = "doc_line"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("inventory.document.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("inventory.unit.id"), index=True
    )
    type_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("catalog.item_type.id"))
    model_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("catalog.model.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3), default=1)
    price: Mapped[float | None] = mapped_column(Numeric(14, 2))
    # новые единицы: номер (если на вещи уже есть наклейка), серийный, ответственный…
    number: Mapped[str] = mapped_column(String(40), default="")
    serial: Mapped[str] = mapped_column(String(100), default="")
    responsible: Mapped[str] = mapped_column(String(150), default="")
    department: Mapped[str] = mapped_column(String(150), default="")
    state: Mapped[str | None] = mapped_column(String(20))
    commissioned_on: Mapped[dt.date | None] = mapped_column(Date)
    life_months: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(300), default="")
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    from_place: Mapped[str | None] = mapped_column(String(50))
    to_place: Mapped[str | None] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(String(300), default="")
    new_value: Mapped[float | None] = mapped_column(Numeric(14, 2))
    # после проведения: какие единицы строка завела
    created_units: Mapped[list[str]] = mapped_column(JSONB, default=list)


class DocFile(Base):
    """Основание и сканы документа."""

    __tablename__ = "doc_file"
    __table_args__ = S

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("inventory.document.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("files.file.id"))


class StockMove(Base):
    """Движение остатка: + поступление, − расход или уход; сумма — по средней цене."""

    __tablename__ = "stock_move"
    __table_args__ = S

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID, index=True)
    line_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    place: Mapped[str] = mapped_column(String(50), index=True)
    building_id: Mapped[uuid.UUID | None] = mapped_column(UUID, index=True)
    floor_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    type_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("catalog.item_type.id"), index=True)
    model_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("catalog.model.id"))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    amount: Mapped[float] = mapped_column(Numeric(16, 2))
