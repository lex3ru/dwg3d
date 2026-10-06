"""The tables of the access service (docs/DATA_MODEL.md, section 2)."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, Table, Text, UniqueConstraint, Uuid, func
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

shares = Table(
    "shares", metadata,                                    # links for looking without an account
    Column("id", Uuid, primary_key=True),
    Column("token_hash", Text, nullable=False, unique=True),   # the link carries the token; only its hash is kept
    Column("building_id", Uuid, nullable=False, index=True),
    Column("scope_kind", Text, nullable=False),            # building | floor | room
    Column("scope_id", Uuid, nullable=False),
    Column("floor_id", Uuid),                              # the floor whose plan a guest of a floor or a room sees
    Column("note", Text, nullable=False, server_default=""),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("opened", Integer, nullable=False, server_default="0"),
    Column("last_opened_at", DateTime(timezone=True)),
    Column("created_by", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

signing_keys = Table(
    "signing_keys", metadata,                              # the key guest tokens are signed with
    Column("kid", Text, primary_key=True),
    Column("private_pem", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
