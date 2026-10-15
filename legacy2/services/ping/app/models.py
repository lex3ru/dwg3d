"""The tables of the service (its own database; see migrations/versions)."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, Table, Text, Uuid, func
from twin_chassis import metadata

# The sample entity of a new service: replace it with the real ones.
notes = Table(
    "notes", metadata,
    Column("id", Uuid, primary_key=True),
    Column("text", Text, nullable=False),
    Column("created_by", Text, nullable=False, index=True),      # the account (Keycloak sub)
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("echoed_at", DateTime(timezone=True)),                # set by the handler of the note's own event
    Column("echoes", Integer, nullable=False, server_default="0"),
)
