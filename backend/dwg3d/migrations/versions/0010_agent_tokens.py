"""tokens of AI agents

An agent (an MCP client, a script) acts for the user who made the token, in
one project, with no more than the token's mode allows: read, propose
(read until proposals come), write (objects, pins, layers). The token is
shown once; the row keeps its SHA-256.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_tokens",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), server_default="", nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("mode IN ('read', 'propose', 'write')", name="agent_tokens_mode"),
    )
    op.create_index("agent_tokens_project", "agent_tokens", ["project_id"])


def downgrade():
    op.drop_table("agent_tokens")
