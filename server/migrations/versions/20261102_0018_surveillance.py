"""Подключения физических камер (ADR-0027).

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA surveillance')
    op.create_table('connection',
                    sa.Column('item_id', postgresql.UUID(), nullable=False),
                    sa.Column('address', sa.String(2048), nullable=False),
                    sa.Column('username', sa.String(200), nullable=False),
                    sa.Column('password', sa.LargeBinary(), nullable=False),
                    sa.Column('version', sa.Integer(), nullable=False),
                    sa.ForeignKeyConstraint(['item_id'], ['planning.item.id'], ondelete='CASCADE'),
                    sa.PrimaryKeyConstraint('item_id'), schema='surveillance')


def downgrade() -> None:
    op.drop_table('connection', schema='surveillance')
    op.execute('DROP SCHEMA surveillance')
