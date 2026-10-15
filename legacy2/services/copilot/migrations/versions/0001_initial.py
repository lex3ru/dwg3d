"""outbox, inbox, settings, chats, messages, usage, proposals

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from twin_chassis.migrate import create_chassis_tables

revision = "0001"
down_revision = None


def upgrade() -> None:
    create_chassis_tables()
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("value", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.Text),
    )
    op.create_table(
        "chats",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("user_sub", sa.Text, nullable=False),
        sa.Column("building_id", sa.Uuid),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chats_user_sub", "chats", ["user_sub"])
    op.create_table(
        "messages",
        sa.Column("chat_id", sa.Uuid, primary_key=True),
        sa.Column("n", sa.Integer, primary_key=True),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text),
        sa.Column("tool_calls", sa.JSON),
        sa.Column("tool_call_id", sa.Text),
        sa.Column("name", sa.Text),
        sa.Column("shown", sa.JSON),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "usage",
        sa.Column("user_sub", sa.Text, primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("requests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.create_table(
        "proposals",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("chat_id", sa.Uuid, nullable=False),
        sa.Column("user_sub", sa.Text, nullable=False),
        sa.Column("building_id", sa.Uuid),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("actions", sa.JSON, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("result", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.Text),
    )
    op.create_index("ix_proposals_chat_id", "proposals", ["chat_id"])
    op.create_index("ix_proposals_building_id", "proposals", ["building_id"])


def downgrade() -> None:
    for t in ("proposals", "usage", "messages", "chats", "settings", "inbox", "outbox"):
        op.drop_table(t)
