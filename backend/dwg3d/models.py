"""ORM tables. The schema itself is changed only through Alembic migrations
(dwg3d/migrations/versions); keep these classes in step with them."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
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


class Project(Base):
    """A building: the uploaded drawing and everything the user set on it.
    Model files live on disk in <DWG3D_DATA>/jobs/<id>/ (see Build.out_dir)."""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)        # 12 hex chars, as in data/jobs/<id>
    name: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)                     # original upload name
    input_path: Mapped[str] = mapped_column(Text)                   # relative to the project dir
    size: Mapped[int] = mapped_column(BigInteger, server_default="0")
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))   # overrides for the next build
    site: Mapped[dict | None] = mapped_column(JSONB)                # map binding
    detail: Mapped[dict | None] = mapped_column(JSONB)              # detailed model alignment
    # floor-bound viewer data (furniture, markers, comments) until they get their own tables
    view: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    current_build: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Build(Base):
    """Result of one successful pipeline run (build numbers start at 1)."""
    __tablename__ = "builds"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    n: Mapped[int] = mapped_column(Integer, primary_key=True)
    result: Mapped[dict] = mapped_column(JSONB)                     # floors, rooms, entrances, warnings...
    config: Mapped[dict] = mapped_column(JSONB)                     # overrides as re-anchored by this build
    out_dir: Mapped[str] = mapped_column(Text)                      # model.glb, plans/, exports
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


JOB_ACTIVE = ("queued", "running")


class Job(Base):
    """Build queue: workers claim queued rows with SELECT ... FOR UPDATE SKIP LOCKED."""
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'done', 'error')", name="jobs_status"),
        # at most one queued/running build per project
        Index("jobs_one_active", "project_id", unique=True, postgresql_where=text("status IN ('queued', 'running')")),
        Index("jobs_queue", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    stage: Mapped[str] = mapped_column(Text, server_default="queued")
    progress: Mapped[float] = mapped_column(Float, server_default="0")
    message: Mapped[str] = mapped_column(Text, server_default="")
    error: Mapped[str | None] = mapped_column(Text)
    trace: Mapped[str | None] = mapped_column(Text)                 # server log only, never sent to the client
    worker: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Floor(Base):
    """A floor that keeps its identity across builds: `anchor` (sheet + alignment,
    see edits.py) is matched to each new build; `candidate` is its id there
    (c0, c3...) or NULL when its sheet is no longer found."""
    __tablename__ = "floors"
    __table_args__ = (UniqueConstraint("project_id", "candidate"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    anchor: Mapped[dict] = mapped_column(JSONB)
    candidate: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    level: Mapped[int | None] = mapped_column(Integer)
    elevation: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
