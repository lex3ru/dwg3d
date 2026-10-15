"""outbox, inbox, buildings, drawings, revisions, floors with plans, rooms, pins

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from twin_chassis.migrate import create_chassis_tables

revision = "0001"
down_revision = None
NOW = sa.func.now()


def upgrade() -> None:
    create_chassis_tables()
    op.create_table(
        "buildings",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("address", sa.Text, nullable=False, server_default=""),
        sa.Column("site", JSONB),
        sa.Column("facade", JSONB),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "drawings",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("building_id", sa.Uuid, sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("placement", JSONB, nullable=False, server_default='{"dx": 0, "dy": 0, "dz": 0, "rotation": 0}'),
        sa.Column("build_id", sa.Uuid),
        sa.Column("build_n", sa.Integer, nullable=False, server_default="0"),
        sa.Column("result", JSONB),
        sa.Column("sort", sa.Integer, nullable=False, server_default="0"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_drawings_building_id", "drawings", ["building_id"])
    op.create_table(
        "revisions",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("building_id", sa.Uuid, sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drawing_id", sa.Uuid, sa.ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("build_id", sa.Uuid, nullable=False),
        sa.Column("n", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="published"),
        sa.Column("summary", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_revisions_building_id", "revisions", ["building_id"])
    op.create_index("ix_revisions_drawing_id", "revisions", ["drawing_id"])
    op.create_table(
        "floors",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("building_id", sa.Uuid, sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drawing_id", sa.Uuid, sa.ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("anchor", JSONB, nullable=False),
        sa.Column("candidate", sa.Text),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("level", sa.Integer),
        sa.Column("elevation", sa.Float, nullable=False, server_default="0"),
        sa.Column("height", sa.Float, nullable=False, server_default="0"),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("manual", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("revision_id", sa.Uuid),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("ix_floors_building_id", "floors", ["building_id"])
    op.create_index("ix_floors_drawing_id", "floors", ["drawing_id"])
    op.create_table(
        "floor_plans",
        sa.Column("floor_id", sa.Uuid, sa.ForeignKey("floors.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision_id", sa.Uuid),
        sa.Column("data", JSONB, nullable=False),
    )
    op.create_table(
        "rooms",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("building_id", sa.Uuid, sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor_id", sa.Uuid, sa.ForeignKey("floors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idx", sa.Integer),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("number", sa.Text),
        sa.Column("type", sa.Text),
        sa.Column("area", sa.Float, nullable=False, server_default="0"),
        sa.Column("polygon", JSONB, nullable=False),
        sa.Column("label", JSONB),
        sa.Column("manual", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("merged_into", sa.Uuid, sa.ForeignKey("rooms.id")),
        sa.Column("revision_id", sa.Uuid),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("ix_rooms_building_id", "rooms", ["building_id"])
    op.create_index("ix_rooms_floor_id", "rooms", ["floor_id"])
    op.create_table(
        "pins",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("building_id", sa.Uuid, sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor_id", sa.Uuid, sa.ForeignKey("floors.id", ondelete="SET NULL")),
        sa.Column("kind", sa.Text, nullable=False, server_default="marker"),
        sa.Column("x", sa.Float(53), nullable=False),
        sa.Column("y", sa.Float(53), nullable=False),
        sa.Column("z", sa.Float(53), nullable=False),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("auto", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("ix_pins_building_id", "pins", ["building_id"])


def downgrade() -> None:
    for table in ("pins", "rooms", "floor_plans", "floors", "revisions", "drawings", "buildings", "inbox", "outbox"):
        op.drop_table(table)
