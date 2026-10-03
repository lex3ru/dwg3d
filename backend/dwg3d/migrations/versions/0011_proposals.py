"""proposals of AI agents

An agent proposes changes of layer objects on a drawing (the operations of
viewdata.apply); a person sees them on the plan and applies or rejects them.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "proposals",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drawing_id", sa.Text(), sa.ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_id", sa.Text(), sa.ForeignKey("agent_tokens.id", ondelete="SET NULL")),
        sa.Column("agent", sa.Text(), server_default="", nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("ops", postgresql.JSONB(), nullable=False),
        sa.Column("build", sa.Integer()),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.CheckConstraint("status IN ('open', 'applied', 'rejected', 'stale')", name="proposals_status"),
    )
    op.create_index("proposals_project", "proposals", ["project_id", "status"])


def downgrade():
    op.drop_table("proposals")
