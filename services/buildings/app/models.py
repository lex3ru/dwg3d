"""The tables of the buildings service (docs/DATA_MODEL.md, section 3).

Geometry (plans, room outlines, pins on a floor) is in the plan coordinates of
the floor's drawing, metres; `drawings.placement` puts a drawing into the building.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, Table, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from twin_chassis import metadata

NOW = func.now()

buildings = Table(
    "buildings", metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("address", Text, nullable=False, server_default=""),
    Column("site", JSONB),                                   # the map: lat, lon, bearing, scale
    Column("facade", JSONB),                                 # a detailed GLB: its key and alignment
    Column("version", Integer, nullable=False, server_default="1"),
    Column("created_by", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("deleted_at", DateTime(timezone=True)),
)

drawings = Table(
    "drawings", metadata,                                    # the drawings a building is made of (files: import)
    Column("id", Uuid, primary_key=True),                    # the same id as in the import service
    Column("building_id", Uuid, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", Text, nullable=False, server_default=""),
    Column("placement", JSONB, nullable=False, server_default='{"dx": 0, "dy": 0, "dz": 0, "rotation": 0}'),
    Column("build_id", Uuid),                                # the published build (import)
    Column("build_n", Integer, nullable=False, server_default="0"),
    Column("result", JSONB),                                 # that build's result, floors and rooms carrying our ids
    Column("sort", Integer, nullable=False, server_default="0"),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=NOW),
)

revisions = Table(
    "revisions", metadata,
    Column("id", Uuid, primary_key=True),
    Column("building_id", Uuid, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("drawing_id", Uuid, ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("build_id", Uuid, nullable=False),
    Column("n", Integer, nullable=False),
    Column("status", Text, nullable=False, server_default="published"),      # draft (stage 7) | published | discarded
    Column("summary", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("published_at", DateTime(timezone=True)),
)

floors = Table(
    "floors", metadata,                                      # a floor keeps its row from revision to revision
    Column("id", Uuid, primary_key=True),
    Column("building_id", Uuid, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("drawing_id", Uuid, ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("anchor", JSONB, nullable=False),                 # the sheet it is recognised by in a new build
    Column("candidate", Text),                               # its id in the published build (c0, c3...)
    Column("name", Text, nullable=False, server_default=""),
    Column("level", Integer),
    Column("elevation", Float, nullable=False, server_default="0"),
    Column("height", Float, nullable=False, server_default="0"),
    Column("status", Text, nullable=False, server_default="active"),         # active | retired
    Column("manual", ARRAY(Text), nullable=False, server_default="{}"),     # fields set by hand: a revision keeps them
    Column("revision_id", Uuid),
    Column("version", Integer, nullable=False, server_default="1"),
)

floor_plans = Table(
    "floor_plans", metadata,                                 # walls, openings, room outlines: large, kept apart
    Column("floor_id", Uuid, ForeignKey("floors.id", ondelete="CASCADE"), primary_key=True),
    Column("revision_id", Uuid),
    Column("data", JSONB, nullable=False),
)

rooms = Table(
    "rooms", metadata,                                       # a room keeps its id too; others refer to it by that id
    Column("id", Uuid, primary_key=True),
    Column("building_id", Uuid, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("floor_id", Uuid, ForeignKey("floors.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("idx", Integer),                                  # its number in the published build's plan
    Column("name", Text, nullable=False, server_default=""),
    Column("number", Text),
    Column("type", Text),
    Column("area", Float, nullable=False, server_default="0"),
    Column("polygon", JSONB, nullable=False),                # rings: the outline, then holes
    Column("label", JSONB),                                  # where its name is written on the plan
    Column("manual", ARRAY(Text), nullable=False, server_default="{}"),
    Column("status", Text, nullable=False, server_default="active"),         # active | retired
    Column("retired_at", DateTime(timezone=True)),
    Column("merged_into", Uuid, ForeignKey("rooms.id")),
    Column("revision_id", Uuid),
    Column("version", Integer, nullable=False, server_default="1"),
)

pins = Table(
    "pins", metadata,                                        # marks on the model: the user's own
    Column("id", Uuid, primary_key=True),
    Column("building_id", Uuid, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("floor_id", Uuid, ForeignKey("floors.id", ondelete="SET NULL")),
    Column("kind", Text, nullable=False, server_default="marker"),
    Column("x", Float(53), nullable=False),                  # in the scene: glTF coordinates of the floor's drawing
    Column("y", Float(53), nullable=False),
    Column("z", Float(53), nullable=False),
    Column("title", Text, nullable=False, server_default=""),
    Column("note", Text, nullable=False, server_default=""),
    Column("auto", Boolean, nullable=False, server_default="false"),
    Column("created_by", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=NOW),
    Column("version", Integer, nullable=False, server_default="1"),
)
