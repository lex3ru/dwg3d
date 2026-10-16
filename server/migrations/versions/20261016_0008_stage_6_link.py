"""Этап 6: связь планировки и учёта — единица у предмета, метки на дверях помещений.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('item', sa.Column('unit_id', sa.UUID(), nullable=True), schema='planning')
    op.create_unique_constraint(op.f('uq_item_unit_id'), 'item', ['unit_id'], schema='planning')
    op.create_table('room_label',
    sa.Column('room_id', sa.UUID(), nullable=False),
    sa.Column('label_code', sa.String(length=24), nullable=False),
    sa.ForeignKeyConstraint(['room_id'], ['building.room.id'], name=op.f('fk_room_label_room_id_room')),
    sa.PrimaryKeyConstraint('room_id', name=op.f('pk_room_label')),
    sa.UniqueConstraint('label_code', name=op.f('uq_room_label_label_code')),
    schema='inventory'
    )


def downgrade() -> None:
    op.drop_table('room_label', schema='inventory')
    op.drop_constraint(op.f('uq_item_unit_id'), 'item', schema='planning', type_='unique')
    op.drop_column('item', 'unit_id', schema='planning')
