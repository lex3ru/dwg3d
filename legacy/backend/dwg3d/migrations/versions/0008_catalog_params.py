"""catalog item parameters (Wi-Fi access points, fire detectors)

The new catalog categories (network, fire, access, Wi-Fi) are added from the
seed on start-up (catalog.ensure_seeded adds what is missing).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("catalog_items", sa.Column("params", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("catalog_items", "params")
