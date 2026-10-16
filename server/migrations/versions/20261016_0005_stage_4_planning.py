"""Этап 4: расстановка — предметы на планах этажей.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS planning")
    op.create_table('item',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=False),
    sa.Column('floor_id', sa.UUID(), nullable=False),
    sa.Column('room_id', sa.UUID(), nullable=True),
    sa.Column('type_id', sa.UUID(), nullable=False),
    sa.Column('model_id', sa.UUID(), nullable=True),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('x', sa.Float(), nullable=True),
    sa.Column('y', sa.Float(), nullable=True),
    sa.Column('angle', sa.Float(), nullable=False),
    sa.Column('z', sa.Float(), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['building_id'], ['building.building.id'], name=op.f('fk_item_building_id_building')),
    sa.ForeignKeyConstraint(['floor_id'], ['building.floor.id'], name=op.f('fk_item_floor_id_floor')),
    sa.ForeignKeyConstraint(['model_id'], ['catalog.model.id'], name=op.f('fk_item_model_id_model')),
    sa.ForeignKeyConstraint(['parent_id'], ['planning.item.id'], name=op.f('fk_item_parent_id_item')),
    sa.ForeignKeyConstraint(['room_id'], ['building.room.id'], name=op.f('fk_item_room_id_room')),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_item_type_id_item_type')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_item')),
    schema='planning'
    )
    op.create_index(op.f('ix_planning_item_building_id'), 'item', ['building_id'], unique=False, schema='planning')
    op.create_index(op.f('ix_planning_item_floor_id'), 'item', ['floor_id'], unique=False, schema='planning')
    op.create_index(op.f('ix_planning_item_model_id'), 'item', ['model_id'], unique=False, schema='planning')
    op.create_index(op.f('ix_planning_item_parent_id'), 'item', ['parent_id'], unique=False, schema='planning')
    op.create_index(op.f('ix_planning_item_room_id'), 'item', ['room_id'], unique=False, schema='planning')
    op.create_index(op.f('ix_planning_item_type_id'), 'item', ['type_id'], unique=False, schema='planning')


def downgrade() -> None:
    op.drop_index(op.f('ix_planning_item_type_id'), table_name='item', schema='planning')
    op.drop_index(op.f('ix_planning_item_room_id'), table_name='item', schema='planning')
    op.drop_index(op.f('ix_planning_item_parent_id'), table_name='item', schema='planning')
    op.drop_index(op.f('ix_planning_item_model_id'), table_name='item', schema='planning')
    op.drop_index(op.f('ix_planning_item_floor_id'), table_name='item', schema='planning')
    op.drop_index(op.f('ix_planning_item_building_id'), table_name='item', schema='planning')
    op.drop_table('item', schema='planning')
    op.execute("DROP SCHEMA IF EXISTS planning")
