"""Этап 9: инвентаризация — места ведомости, отметки обхода, вещи без метки, пересчёт остатков.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('count_place',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('place', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['inventory.document.id'], name=op.f('fk_count_place_document_id_document'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('document_id', 'place', name=op.f('pk_count_place')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_count_place_place'), 'count_place', ['place'], unique=False, schema='inventory')
    op.create_table('count_mark',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('unit_id', sa.UUID(), nullable=False),
    sa.Column('place', sa.String(length=50), nullable=False),
    sa.Column('manual', sa.Boolean(), nullable=False),
    sa.Column('marked_by', sa.String(length=150), nullable=False),
    sa.Column('marked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['inventory.document.id'], name=op.f('fk_count_mark_document_id_document'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['unit_id'], ['inventory.unit.id'], name=op.f('fk_count_mark_unit_id_unit'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('document_id', 'unit_id', name=op.f('pk_count_mark')),
    schema='inventory'
    )
    op.create_table('count_extra',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('place', sa.String(length=50), nullable=False),
    sa.Column('type_id', sa.UUID(), nullable=False),
    sa.Column('model_id', sa.UUID(), nullable=True),
    sa.Column('serial', sa.String(length=100), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=False),
    sa.Column('photo_file_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['inventory.document.id'], name=op.f('fk_count_extra_document_id_document'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['model_id'], ['catalog.model.id'], name=op.f('fk_count_extra_model_id_model')),
    sa.ForeignKeyConstraint(['photo_file_id'], ['files.file.id'], name=op.f('fk_count_extra_photo_file_id_file')),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_count_extra_type_id_item_type')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_count_extra')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_count_extra_document_id'), 'count_extra', ['document_id'], unique=False, schema='inventory')
    op.create_table('count_stock',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('place', sa.String(length=50), nullable=False),
    sa.Column('type_id', sa.UUID(), nullable=False),
    sa.Column('counted', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['inventory.document.id'], name=op.f('fk_count_stock_document_id_document'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_count_stock_type_id_item_type')),
    sa.PrimaryKeyConstraint('document_id', 'place', 'type_id', name=op.f('pk_count_stock')),
    schema='inventory'
    )


def downgrade() -> None:
    op.drop_table('count_stock', schema='inventory')
    op.drop_table('count_extra', schema='inventory')
    op.drop_table('count_mark', schema='inventory')
    op.drop_table('count_place', schema='inventory')
