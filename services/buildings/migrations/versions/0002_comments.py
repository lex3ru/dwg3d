"""comments to a point of a floor, a room, an object

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
NOW = sa.func.now()


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("building_id", sa.Uuid, sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("floor_id", sa.Uuid, sa.ForeignKey("floors.id", ondelete="CASCADE")),
        sa.Column("room_id", sa.Uuid),
        sa.Column("target_kind", sa.Text, nullable=False),
        sa.Column("target_id", sa.Uuid),
        sa.Column("x", sa.Float(53)),
        sa.Column("y", sa.Float(53)),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("author_sub", sa.Text, nullable=False),
        sa.Column("author_person_id", sa.Uuid),
        sa.Column("author_name", sa.Text, nullable=False, server_default=""),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("ix_comments_target", "comments", ["target_kind", "target_id"])
    op.create_index("ix_comments_floor", "comments", ["building_id", "floor_id"])


def downgrade() -> None:
    op.drop_table("comments")
