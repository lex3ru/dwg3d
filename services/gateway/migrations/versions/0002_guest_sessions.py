"""guest sessions: looking by a link

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.create_table(
        "guest_sessions",
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column("link", sa.Text, nullable=False),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("guest_sub", sa.Text, nullable=False),
        sa.Column("building_id", sa.Text, nullable=False),
        sa.Column("scope_kind", sa.Text, nullable=False),
        sa.Column("scope_id", sa.Text, nullable=False),
        sa.Column("floor_id", sa.Text),
        sa.Column("link_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_guest_sessions_link_expires_at", "guest_sessions", ["link_expires_at"])


def downgrade() -> None:
    op.drop_table("guest_sessions")
