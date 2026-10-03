"""no tokens of external AI agents

External agents (MCP with a token) are gone: the built-in copilot acts for
the signed-in user. Proposals no longer point to a token (their `agent` and
`user_id` say who proposed).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("proposals", "token_id")
    op.drop_table("agent_tokens")


def downgrade():
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
    op.add_column("proposals", sa.Column("token_id", sa.Text(), sa.ForeignKey("agent_tokens.id", ondelete="SET NULL")))
