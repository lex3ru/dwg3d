"""The tables of the catalog (docs/DATA_MODEL.md, section 5).

Properties of a set and of a type are kept with their owner, as an ordered
list: a property is never looked up apart from the schema it belongs to.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from twin_chassis import metadata

NOW = func.now()

categories = Table(
    "categories", metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("color", Text, nullable=False, server_default="#868e96"),
    Column("sort", Integer, nullable=False, server_default="0"),
)

property_sets = Table(
    "property_sets", metadata,                     # properties shared by several types: «Учёт», «Мебель»…
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("properties", JSONB, nullable=False, server_default="[]"),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=NOW),
)

types = Table(
    "types", metadata,
    Column("id", Uuid, primary_key=True),
    Column("category_id", Uuid, ForeignKey("categories.id"), nullable=False, index=True),
    Column("name", Text, nullable=False),
    Column("w", Float, nullable=False),            # size, metres: width, depth, height
    Column("d", Float, nullable=False),
    Column("h", Float, nullable=False),
    Column("elevation", Float),                    # mounting height by default
    Column("wall_mounted", Boolean, nullable=False, server_default="false"),
    Column("ceiling_mounted", Boolean, nullable=False, server_default="false"),   # hangs under the ceiling of its floor
    Column("shape", Text, nullable=False, server_default="box"),      # the stand-in figure in 3D
    Column("color", Text),
    Column("model", JSONB),                        # a GLB: its key, size, turn, warnings
    Column("container", Boolean, nullable=False, server_default="false"),   # other objects may be put inside
    Column("portable", Boolean, nullable=False, server_default="false"),    # whoever answers for it may move it
    Column("sets", ARRAY(Uuid), nullable=False, server_default="{}"),       # property sets, in order
    Column("properties", JSONB, nullable=False, server_default="[]"),       # its own properties
    Column("values", JSONB, nullable=False, server_default="{}"),           # values of properties stored with the type
    Column("article", Text),
    Column("supplier", Text),
    Column("price", Numeric(12, 2)),
    Column("currency", Text, nullable=False, server_default="RUB"),
    Column("active", Boolean, nullable=False, server_default="true"),
    Column("schema_version", Integer, nullable=False, server_default="1"),  # grows when the schema of the type changes
    Column("version", Integer, nullable=False, server_default="1"),
    Column("sort", Integer, nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=NOW),
)

products = Table(
    "products", metadata,                          # a make and model of a type: «Монитор 27″» → Dell P2723DE
    Column("id", Uuid, primary_key=True),
    Column("type_id", Uuid, ForeignKey("types.id"), nullable=False, index=True),
    Column("vendor", Text, nullable=False, server_default=""),
    Column("name", Text, nullable=False),          # the model as the vendor names it
    Column("article", Text),
    Column("supplier", Text),
    Column("price", Numeric(12, 2)),               # the list price; the type's price is the estimate without a model
    Column("currency", Text, nullable=False, server_default="RUB"),
    Column("note", Text, nullable=False, server_default=""),
    Column("active", Boolean, nullable=False, server_default="true"),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("sort", Integer, nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    UniqueConstraint("type_id", "vendor", "name", name="uq_products_type_vendor_name"),
)
