"""The tables of the assets service (docs/DATA_MODEL.md, section 6)."""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Table,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from twin_chassis import metadata

NOW = func.now()
STATES = ("in_use", "faulty", "in_repair", "in_storage", "retired")

assets = Table(
    "assets", metadata,
    Column("id", Uuid, primary_key=True),
    Column("type_id", Uuid, nullable=False, index=True),              # -> catalog
    Column("type_name", Text, nullable=False, server_default=""),     # a copy, for search and lists
    Column("category_id", Uuid),
    Column("schema_version", Integer, nullable=False, server_default="0"),
    Column("building_id", Uuid, nullable=False, index=True),          # -> buildings
    Column("floor_id", Uuid, nullable=False, index=True),
    Column("room_id", Uuid, nullable=False, index=True),              # found by the point, never sent by a client
    Column("x", Float(53)),                                           # plan coordinates of the floor's drawing, m;
    Column("y", Float(53)),                                           # absent for an object inside another
    Column("angle", Float, nullable=False, server_default="0"),
    Column("elevation", Float),
    Column("container_id", Uuid, ForeignKey("assets.id"), index=True),
    Column("inventory_no", Text, nullable=False, unique=True),        # never reused, even after retiring
    Column("serial_no", Text),
    Column("state", Text, nullable=False, server_default="in_use"),
    Column("responsible_id", Uuid, index=True),                       # -> people
    Column("props", JSONB, nullable=False, server_default="{}"),      # values of the type's properties kept with objects
    Column("note", Text, nullable=False, server_default=""),
    Column("needs_placement", Boolean, nullable=False, server_default="false"),
    Column("needs_fill", Boolean, nullable=False, server_default="false"),
    Column("qr_code", Text, nullable=False, unique=True),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("created_by", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("retired_at", DateTime(timezone=True)),
    CheckConstraint("(container_id is null) = (x is not null)", name="placed_or_inside"),
)

asset_history = Table(
    "asset_history", metadata,                                        # append only
    Column("id", Uuid, primary_key=True),
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
    Column("at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("actor_kind", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("actor_person_id", Uuid),
    Column("action", Text, nullable=False),
    Column("changes", JSONB, nullable=False, server_default="{}"),    # {field: [was, is]}
    Column("reverts", Uuid),
    Column("reason", Text),
)

asset_files = Table(
    "asset_files", metadata,
    Column("id", Uuid, primary_key=True),
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("kind", Text, nullable=False),                             # photo | document
    Column("name", Text, nullable=False),
    Column("mime", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("uploaded_by", Text, nullable=False, server_default=""),
    Column("uploaded_at", DateTime(timezone=True), nullable=False, server_default=NOW),
)

type_schemas = Table(
    "type_schemas", metadata,                                         # the catalog's types as last seen
    Column("type_id", Uuid, primary_key=True),
    Column("schema_version", Integer, nullable=False),
    Column("name", Text, nullable=False),
    Column("category_id", Uuid),
    Column("container", Boolean, nullable=False, server_default="false"),
    Column("portable", Boolean, nullable=False, server_default="false"),
    Column("archived", Boolean, nullable=False, server_default="false"),
    Column("schema", JSONB, nullable=False, server_default="[]"),         # properties kept with objects
    Column("type_props", JSONB, nullable=False, server_default="[]"),     # properties kept with the type, with values
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=NOW),
)
