"""assignments: a person in a room, maybe at a workplace

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.create_table(
        "assignments",
        sa.Column("person_id", sa.Uuid, sa.ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("room_id", sa.Uuid, primary_key=True),
        sa.Column("building_id", sa.Uuid, nullable=False),
        sa.Column("floor_id", sa.Uuid, nullable=False),
        sa.Column("workplace_asset_id", sa.Uuid),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_assignments_room", "assignments", ["room_id"])
    op.create_index("ix_assignments_building", "assignments", ["building_id"])


def downgrade() -> None:
    op.drop_table("assignments")
