"""drafts of revisions: the proposal and the build they wait to publish

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    for column in ("proposal", "result", "plans"):
        op.add_column("revisions", sa.Column(column, JSONB))
    op.add_column("revisions", sa.Column("decided_by", sa.Text))


def downgrade() -> None:
    for column in ("proposal", "result", "plans", "decided_by"):
        op.drop_column("revisions", column)
