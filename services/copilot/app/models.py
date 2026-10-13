"""The tables of the service (its own database; see migrations/versions)."""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Column, Date, DateTime, Integer, Table, Text, Uuid, func
from twin_chassis import metadata

# one row: the model and how to reach it (the key encrypted), the limits
settings = Table(
    "settings", metadata,
    Column("id", Integer, primary_key=True),
    Column("value", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_by", Text),
)

chats = Table(
    "chats", metadata,
    Column("id", Uuid, primary_key=True),
    Column("user_sub", Text, nullable=False, index=True),
    Column("building_id", Uuid),
    Column("title", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# the conversation as the model sees it: user / assistant (with tool_calls) / tool (tool_call_id, name),
# plus what the panel shows (`shown`: the user's own words, a proposal, a ui command, an error)
messages = Table(
    "messages", metadata,
    Column("chat_id", Uuid, primary_key=True),
    Column("n", Integer, primary_key=True),
    Column("role", Text, nullable=False),
    Column("content", Text),
    Column("tool_calls", JSON),
    Column("tool_call_id", Text),
    Column("name", Text),
    Column("shown", JSON),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

usage = Table(
    "usage", metadata,
    Column("user_sub", Text, primary_key=True),
    Column("day", Date, primary_key=True),
    Column("requests", Integer, nullable=False, server_default="0"),
    Column("prompt_tokens", BigInteger, nullable=False, server_default="0"),
    Column("completion_tokens", BigInteger, nullable=False, server_default="0"),
)

proposals = Table(
    "proposals", metadata,
    Column("id", Uuid, primary_key=True),
    Column("chat_id", Uuid, nullable=False, index=True),
    Column("user_sub", Text, nullable=False),
    Column("building_id", Uuid, index=True),
    Column("summary", Text, nullable=False),
    Column("actions", JSON, nullable=False),
    Column("status", Text, nullable=False, server_default="open"),     # open | applied | rejected | stale
    Column("result", JSON),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("decided_at", DateTime(timezone=True)),
    Column("decided_by", Text),
)
