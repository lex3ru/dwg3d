"""outbox, inbox, categories, property sets, types — and what the catalog starts with

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from twin_chassis.migrate import create_chassis_tables

from app import seed

revision = "0001"
down_revision = None
NOW = sa.func.now()


def upgrade() -> None:
    create_chassis_tables()
    categories = op.create_table(
        "categories",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("color", sa.Text, nullable=False, server_default="#868e96"),
        sa.Column("sort", sa.Integer, nullable=False, server_default="0"),
    )
    sets = op.create_table(
        "property_sets",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("properties", JSONB, nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    types = op.create_table(
        "types",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("category_id", sa.Uuid, sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("w", sa.Float, nullable=False),
        sa.Column("d", sa.Float, nullable=False),
        sa.Column("h", sa.Float, nullable=False),
        sa.Column("elevation", sa.Float),
        sa.Column("wall_mounted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("shape", sa.Text, nullable=False, server_default="box"),
        sa.Column("color", sa.Text),
        sa.Column("model", JSONB),
        sa.Column("container", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("portable", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sets", ARRAY(sa.Uuid), nullable=False, server_default="{}"),
        sa.Column("properties", JSONB, nullable=False, server_default="[]"),
        sa.Column("values", JSONB, nullable=False, server_default="{}"),
        sa.Column("article", sa.Text),
        sa.Column("supplier", sa.Text),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("currency", sa.Text, nullable=False, server_default="RUB"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("sort", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_types_category_id", "types", ["category_id"])
    op.bulk_insert(categories, seed.CATEGORIES)
    op.bulk_insert(sets, seed.SETS)
    op.bulk_insert(types, seed.TYPES)


def downgrade() -> None:
    for table in ("types", "property_sets", "categories", "inbox", "outbox"):
        op.drop_table(table)
