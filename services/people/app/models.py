"""The tables of the people service (docs/DATA_MODEL.md, section 7)."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, Table, Text, Uuid, func
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
