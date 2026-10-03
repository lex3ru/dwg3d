"""what open viewer windows show, for AI agents

Each window of the viewer reports what it shows (drawing, floor, 2D/3D, the
selection) while it is open; an agent with a token of the same user reads
it to understand "this", "here". Rows of closed or silent windows go away.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ui_contexts",
        sa.Column("client", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ui_contexts_project", "ui_contexts", ["project_id", "user_id"])


def downgrade():
    op.drop_table("ui_contexts")
