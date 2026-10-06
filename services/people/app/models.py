"""The tables of the people service (docs/DATA_MODEL.md, section 7)."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Table, Text, Uuid, func
from twin_chassis import metadata

persons = Table(
    "persons", metadata,
    Column("id", Uuid, primary_key=True),
    Column("full_name", Text, nullable=False),
    Column("position", Text, nullable=False, server_default=""),
    Column("department", Text, nullable=False, server_default=""),
    Column("email", Text),                                   # lower case; links the account on the first sign-in
    Column("phone", Text),
    Column("user_sub", Text, unique=True),                   # the Keycloak account, once linked
    Column("status", Text, nullable=False, server_default="active"),      # active | left
    Column("left_at", DateTime(timezone=True)),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("created_by", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

assignments = Table(
    "assignments", metadata,                                 # a person works in a room, maybe at a workplace
    Column("person_id", Uuid, ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True),
    Column("room_id", Uuid, primary_key=True),               # → buildings
    Column("building_id", Uuid, nullable=False),
    Column("floor_id", Uuid, nullable=False),
    Column("workplace_asset_id", Uuid),                      # → assets, in that room
    Column("created_by", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_assignments_room", "room_id"),
    Index("ix_assignments_building", "building_id"),
)
