"""The tables of the journal (docs/DATA_MODEL.md, section 8): events as they came, nothing else."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Index, Table, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from twin_chassis import metadata

events = Table(
    "events", metadata,                                      # append-only
    Column("id", Uuid, primary_key=True),
    Column("type", Text, nullable=False),
    Column("time", DateTime(timezone=True), nullable=False),  # when it happened, by the service that saw it
    Column("actor_kind", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("actor_person_id", Uuid),
    Column("building_id", Uuid),                             # the area of the event — from the envelope
    Column("floor_id", Uuid),
    Column("room_id", Uuid),
    Column("asset_id", Uuid),
    Column("person_id", Uuid),
    Column("subject_kind", Text, nullable=False),
    Column("subject_id", Text, nullable=False),
    Column("data", JSONB, nullable=False, server_default="{}"),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_events_building_time", "building_id", "time"),
    Index("ix_events_room_time", "room_id", "time"),
    Index("ix_events_asset_time", "asset_id", "time"),
    Index("ix_events_person_time", "person_id", "time"),
    Index("ix_events_actor_time", "actor_person_id", "time"),
    Index("ix_events_type_time", "type", "time"),
)
