"""outbox, inbox, assets, their history and files, the catalog's types as last seen

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from twin_chassis.migrate import create_chassis_tables

revision = "0001"
down_revision = None
NOW = sa.func.now()


def upgrade() -> None:
    create_chassis_tables()
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("type_id", sa.Uuid, nullable=False),
        sa.Column("type_name", sa.Text, nullable=False, server_default=""),
        sa.Column("category_id", sa.Uuid),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("building_id", sa.Uuid, nullable=False),
        sa.Column("floor_id", sa.Uuid, nullable=False),
        sa.Column("room_id", sa.Uuid, nullable=False),
        sa.Column("x", sa.Float(53)),
        sa.Column("y", sa.Float(53)),
        sa.Column("angle", sa.Float, nullable=False, server_default="0"),
        sa.Column("elevation", sa.Float),
        sa.Column("container_id", sa.Uuid, sa.ForeignKey("assets.id")),
        sa.Column("inventory_no", sa.Text, nullable=False, unique=True),
        sa.Column("serial_no", sa.Text),
        sa.Column("state", sa.Text, nullable=False, server_default="in_use"),
        sa.Column("responsible_id", sa.Uuid),
        sa.Column("props", JSONB, nullable=False, server_default="{}"),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("needs_placement", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("needs_fill", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("qr_code", sa.Text, nullable=False, unique=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("(container_id is null) = (x is not null)", name="placed_or_inside"),
    )
    op.create_index("ix_assets_type_id", "assets", ["type_id"])
    op.create_index("ix_assets_building_id", "assets", ["building_id"])
    op.create_index("ix_assets_floor_id", "assets", ["floor_id"])
    op.create_index("ix_assets_room_id", "assets", ["room_id"])
    op.create_index("ix_assets_container_id", "assets", ["container_id"])
    op.create_index("ix_assets_responsible_id", "assets", ["responsible_id"])
    op.create_table(
        "asset_history",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("asset_id", sa.Uuid, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("actor_kind", sa.Text, nullable=False),
        sa.Column("actor_id", sa.Text, nullable=False),
        sa.Column("actor_person_id", sa.Uuid),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("changes", JSONB, nullable=False, server_default="{}"),
        sa.Column("reverts", sa.Uuid),
        sa.Column("reason", sa.Text),
    )
    op.create_table(
        "asset_files",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("asset_id", sa.Uuid, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("mime", sa.Text, nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("uploaded_by", sa.Text, nullable=False, server_default=""),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_asset_files_asset_id", "asset_files", ["asset_id"])
    op.create_table(
        "type_schemas",
        sa.Column("type_id", sa.Uuid, primary_key=True),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("category_id", sa.Uuid),
        sa.Column("container", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("portable", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("archived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("schema", JSONB, nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_asset_history_asset", "asset_history", ["asset_id", "at"])
    op.create_index("ix_assets_props", "assets", ["props"], postgresql_using="gin")


def downgrade() -> None:
    for table in ("type_schemas", "asset_files", "asset_history", "assets", "inbox", "outbox"):
        op.drop_table(table)
