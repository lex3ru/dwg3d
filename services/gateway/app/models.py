"""The gateway's only table: sign-in sessions."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Table, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from twin_chassis import metadata

sessions = Table(
    "sessions", metadata,
    Column("token_hash", Text, primary_key=True),             # sha256 of the cookie; the cookie itself is not stored
    Column("user_sub", Text, nullable=False, index=True),
    Column("login", Text, nullable=False, server_default=""),
    Column("name", Text, nullable=False, server_default=""),
    Column("email", Text),
    Column("roles", ARRAY(Text), nullable=False, server_default="{}"),
    Column("access_token", Text, nullable=False),             # the three tokens are encrypted (TWIN_SECRET)
    Column("refresh_token", Text),
    Column("id_token", Text),
    Column("access_expires_at", DateTime(timezone=True), nullable=False),
    Column("user_agent", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
