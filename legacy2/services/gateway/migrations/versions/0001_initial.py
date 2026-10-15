"""outbox, inbox, sessions

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY
from twin_chassis.migrate import create_chassis_tables

revision = "0001"
down_revision = None


def upgrade() -> None:
    create_chassis_tables()
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column("user_sub", sa.Text, nullable=False),
        sa.Column("login", sa.Text, nullable=False, server_default=""),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("email", sa.Text),
        sa.Column("roles", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text),
        sa.Column("id_token", sa.Text),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sessions_user_sub", "sessions", ["user_sub"])


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("inbox")
    op.drop_table("outbox")
