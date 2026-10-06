"""outbox, inbox and the events

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from twin_chassis.migrate import create_chassis_tables

revision = "0001"
down_revision = None


def upgrade() -> None:
    create_chassis_tables()
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_kind", sa.Text, nullable=False),
        sa.Column("actor_id", sa.Text, nullable=False),
        sa.Column("actor_person_id", sa.Uuid),
        sa.Column("building_id", sa.Uuid),
        sa.Column("floor_id", sa.Uuid),
        sa.Column("room_id", sa.Uuid),
        sa.Column("asset_id", sa.Uuid),
        sa.Column("person_id", sa.Uuid),
        sa.Column("subject_kind", sa.Text, nullable=False),
        sa.Column("subject_id", sa.Text, nullable=False),
        sa.Column("data", JSONB, nullable=False, server_default="{}"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("building_id", "room_id", "asset_id", "person_id", "actor_person_id", "type"):
        op.create_index(f"ix_events_{column.removesuffix('_id')}_time", "events", [column, "time"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("inbox")
    op.drop_table("outbox")
