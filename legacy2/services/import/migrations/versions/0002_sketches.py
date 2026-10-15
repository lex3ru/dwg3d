"""plans drawn in the 2D editor: drawings of kind «sketch» keep the plan itself, builds a copy of it

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.add_column("drawings", sa.Column("kind", sa.Text, nullable=False, server_default="file"))
    op.create_check_constraint("kind", "drawings", "kind in ('file', 'sketch')")
    op.add_column("drawings", sa.Column("sketch", JSONB))
    op.add_column("drawings", sa.Column("sketch_version", sa.Integer, nullable=False, server_default="0"))
    op.alter_column("builds", "file_id", nullable=True)
    op.add_column("builds", sa.Column("sketch", JSONB))


def downgrade() -> None:
    op.drop_column("builds", "sketch")
    op.execute("DELETE FROM builds WHERE file_id IS NULL")
    op.alter_column("builds", "file_id", nullable=False)
    op.drop_column("drawings", "sketch_version")
    op.drop_column("drawings", "sketch")
    op.drop_constraint(op.f("ck_drawings_kind"), "drawings", type_="check")
    op.drop_column("drawings", "kind")
