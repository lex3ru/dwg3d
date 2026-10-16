"""Этап 7: параметры предметов для расчётов (наклон и угол камеры, наклон светильника).

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('item', sa.Column('params', postgresql.JSONB(astext_type=sa.Text()),
                                    nullable=False, server_default='{}'), schema='planning')


def downgrade() -> None:
    op.drop_column('item', 'params', schema='planning')
