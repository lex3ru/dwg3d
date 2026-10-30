"""Масштаб чертежа (ADR-0025, R-057): масштаб листа, заданный администратором, и что нашёл
разбор — масштаб, откуда он, наибольшая часть листа.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('drawing', sa.Column('scale', sa.Float(), nullable=True), schema='building')
    # разобранные раньше чертежи — без сведений о масштабе: {} до следующего разбора
    op.add_column('drawing', sa.Column('sheet', postgresql.JSONB(astext_type=sa.Text()),
                                       nullable=False, server_default=sa.text("'{}'::jsonb")),
                  schema='building')
    op.alter_column('drawing', 'sheet', server_default=None, schema='building')


def downgrade() -> None:
    op.drop_column('drawing', 'sheet', schema='building')
    op.drop_column('drawing', 'scale', schema='building')
