"""The tables of the access service (docs/DATA_MODEL.md, section 2)."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Table, Text, UniqueConstraint, Uuid, func
from twin_chassis import metadata

subjects = Table(
    "subjects", metadata,                                  # which account is which person (a copy from people)
    Column("user_sub", Text, primary_key=True),
    Column("person_id", Uuid, nullable=False, unique=True),
)

grants = Table(
    "grants", metadata,                                    # a person — a role — an area
    Column("id", Uuid, primary_key=True),
    Column("person_id", Uuid, nullable=False, index=True),
    Column("role", Text, nullable=False),                  # viewer | responsible | admin
    Column("scope_kind", Text, nullable=False),            # building | floor | room | asset
    Column("scope_id", Uuid, nullable=False),
    Column("building_id", Uuid, nullable=False, index=True),   # the building the area is in
    Column("origin", Text, nullable=False, server_default="manual"),   # manual | assignment | responsible
    Column("created_by", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("person_id", "role", "scope_kind", "scope_id", "origin", name="uq_grants_once"),
)
