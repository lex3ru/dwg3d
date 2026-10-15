"""outbox, inbox, variants and their operations

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
        "variants",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("building_id", sa.Uuid, nullable=False, index=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("based_on", sa.Uuid),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("stale", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("stale_reasons", JSONB, nullable=False, server_default="[]"),
        sa.Column("last_result", JSONB),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_table(
        "variant_ops",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("variant_id", sa.Uuid, sa.ForeignKey("variants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("op", sa.Text, nullable=False),
        sa.Column("asset_id", sa.Uuid),
        sa.Column("base_version", sa.Integer),
        sa.Column("data", JSONB, nullable=False, server_default="{}"),
        sa.Column("sort", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_variant_ops_variant", "variant_ops", ["variant_id"])
    op.create_index("ix_variant_ops_asset", "variant_ops", ["asset_id"])


def downgrade() -> None:
    op.drop_table("variant_ops")
    op.drop_table("variants")
    op.drop_table("inbox")
    op.drop_table("outbox")
