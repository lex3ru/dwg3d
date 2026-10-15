"""The tables of the planning service (docs/DATA_MODEL.md, section 9): variants of placing the objects of a
building. A variant keeps not a copy of the objects but what it would do to them — operations, each made
against the version of the object it saw."""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, Table, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from twin_chassis import metadata

NOW = func.now()

variants = Table(
    "variants", metadata,
    Column("id", Uuid, primary_key=True),
    Column("building_id", Uuid, nullable=False, index=True),
    Column("name", Text, nullable=False),
    Column("based_on", Uuid),                                 # the variant it was copied from; null — the fact
    Column("status", Text, nullable=False, server_default="draft"),     # draft | applied
    Column("stale", Boolean, nullable=False, server_default="false"),   # the fact changed under its operations
    Column("stale_reasons", JSONB, nullable=False, server_default="[]"),
    Column("last_result", JSONB),                             # what the last application did and refused
    Column("created_by", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("applied_at", DateTime(timezone=True)),
    Column("version", Integer, nullable=False, server_default="1"),
)

variant_ops = Table(
    "variant_ops", metadata,
    Column("id", Uuid, primary_key=True),
    Column("variant_id", Uuid, ForeignKey("variants.id", ondelete="CASCADE"), nullable=False),
    Column("op", Text, nullable=False),                       # add | move | change | remove
    Column("asset_id", Uuid),                                 # the object, for all but `add`
    Column("base_version", Integer),                          # the object's version the operation was made against
    Column("data", JSONB, nullable=False, server_default="{}"),   # add: type, place, number; move: place; change: note
    Column("sort", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Index("ix_variant_ops_variant", "variant_id"),
    Index("ix_variant_ops_asset", "asset_id"),
)
