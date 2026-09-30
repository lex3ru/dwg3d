"""ORM tables. The schema itself is changed only through Alembic migrations
(dwg3d/migrations/versions); keep these classes in step with them."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class CatalogCategory(Base):
    __tablename__ = "catalog_categories"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text, server_default="#868e96")
    sort: Mapped[int] = mapped_column(Integer, server_default="0")


class CatalogItem(Base):
    """One piece of furniture / equipment. Ids ('diag.mri') are referenced by
    placed items, so an item is deactivated rather than deleted."""
    __tablename__ = "catalog_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("catalog_categories.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    w: Mapped[float] = mapped_column(Float)
    d: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    elev: Mapped[float | None] = mapped_column(Float)
    clear: Mapped[float | None] = mapped_column(Float)
    wall: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    kind: Mapped[str] = mapped_column(Text)                 # procedural model
    color: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)         # GLB under frontend/public/catalog/
    model_rot: Mapped[float | None] = mapped_column(Float)
    camera: Mapped[dict | None] = mapped_column(JSONB)      # {fov, range, ident}
    tags: Mapped[str | None] = mapped_column(Text)
    article: Mapped[str | None] = mapped_column(Text)
    supplier: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="RUB")
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
