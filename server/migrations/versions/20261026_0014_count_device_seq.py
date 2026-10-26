"""Номера отметок обхода по устройствам (R-049, ADR-0006): сервер помнит последний принятый
номер пары «ведомость + устройство» и пропускает опоздавший запрос с номером не больше него.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('count_device',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('device', sa.UUID(), nullable=False),
    sa.Column('last_seq', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['inventory.document.id'], name=op.f('fk_count_device_document_id_document'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('document_id', 'device', name=op.f('pk_count_device')),
    schema='inventory'
    )


def downgrade() -> None:
    op.drop_table('count_device', schema='inventory')
