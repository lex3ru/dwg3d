"""the make and model of an object: a product of the catalog it may name, and a copy of its name for lists

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.add_column("assets", sa.Column("product_id", sa.Uuid))
    op.add_column("assets", sa.Column("product_name", sa.Text, nullable=False, server_default=""))
    op.create_index("ix_assets_product_id", "assets", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_assets_product_id", "assets")
    op.drop_column("assets", "product_name")
    op.drop_column("assets", "product_id")
