"""Этап 5: учёт имущества — склады, ячейки, инвентарные единицы, документы, остатки.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS inventory")
    op.create_table('document',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('from_place', sa.String(length=50), nullable=True),
    sa.Column('to_place', sa.String(length=50), nullable=True),
    sa.Column('basis', sa.String(length=300), nullable=False),
    sa.Column('supplier', sa.String(length=200), nullable=False),
    sa.Column('contractor', sa.String(length=200), nullable=False),
    sa.Column('repair', sa.String(length=10), nullable=True),
    sa.Column('repair_cost', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('reason', sa.String(length=300), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('cancels_id', sa.UUID(), nullable=True),
    sa.Column('cancelled_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=False),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('posted_by', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['cancels_id'], ['inventory.document.id'], name=op.f('fk_document_cancels_id_document')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document')),
    sa.UniqueConstraint('kind', 'number', name='document_number'),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_document_date'), 'document', ['date'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_document_kind'), 'document', ['kind'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_document_status'), 'document', ['status'], unique=False, schema='inventory')
    op.create_table('doc_file',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('file_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['inventory.document.id'], name=op.f('fk_doc_file_document_id_document'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['file_id'], ['files.file.id'], name=op.f('fk_doc_file_file_id_file')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_doc_file')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_doc_file_document_id'), 'doc_file', ['document_id'], unique=False, schema='inventory')
    op.create_table('stock_move',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=True),
    sa.Column('line_id', sa.UUID(), nullable=True),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('place', sa.String(length=50), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=True),
    sa.Column('floor_id', sa.UUID(), nullable=True),
    sa.Column('type_id', sa.UUID(), nullable=False),
    sa.Column('model_id', sa.UUID(), nullable=True),
    sa.Column('qty', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('amount', sa.Numeric(precision=16, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['model_id'], ['catalog.model.id'], name=op.f('fk_stock_move_model_id_model')),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_stock_move_type_id_item_type')),
    sa.PrimaryKeyConstraint('seq', name=op.f('pk_stock_move')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_stock_move_building_id'), 'stock_move', ['building_id'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_stock_move_date'), 'stock_move', ['date'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_stock_move_document_id'), 'stock_move', ['document_id'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_stock_move_place'), 'stock_move', ['place'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_stock_move_type_id'), 'stock_move', ['type_id'], unique=False, schema='inventory')
    op.create_table('unit',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('number', sa.String(length=40), nullable=False),
    sa.Column('type_id', sa.UUID(), nullable=False),
    sa.Column('model_id', sa.UUID(), nullable=True),
    sa.Column('serial', sa.String(length=100), nullable=False),
    sa.Column('place', sa.String(length=50), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=True),
    sa.Column('floor_id', sa.UUID(), nullable=True),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('responsible', sa.String(length=150), nullable=False),
    sa.Column('department', sa.String(length=150), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('values', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('commissioned_on', sa.Date(), nullable=False),
    sa.Column('life_months', sa.Integer(), nullable=True),
    sa.Column('value_base', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('value_date', sa.Date(), nullable=True),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('photo_file_id', sa.UUID(), nullable=True),
    sa.Column('label_code', sa.String(length=24), nullable=False),
    sa.Column('written_off_on', sa.Date(), nullable=True),
    sa.Column('writeoff_reason', sa.String(length=300), nullable=False),
    sa.Column('created_doc_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['model_id'], ['catalog.model.id'], name=op.f('fk_unit_model_id_model')),
    sa.ForeignKeyConstraint(['parent_id'], ['inventory.unit.id'], name=op.f('fk_unit_parent_id_unit')),
    sa.ForeignKeyConstraint(['photo_file_id'], ['files.file.id'], name=op.f('fk_unit_photo_file_id_file')),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_unit_type_id_item_type')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_unit')),
    sa.UniqueConstraint('label_code', name=op.f('uq_unit_label_code')),
    sa.UniqueConstraint('number', name=op.f('uq_unit_number')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_unit_building_id'), 'unit', ['building_id'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_unit_floor_id'), 'unit', ['floor_id'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_unit_model_id'), 'unit', ['model_id'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_unit_parent_id'), 'unit', ['parent_id'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_unit_place'), 'unit', ['place'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_unit_state'), 'unit', ['state'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_unit_type_id'), 'unit', ['type_id'], unique=False, schema='inventory')
    op.create_table('doc_line',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('unit_id', sa.UUID(), nullable=True),
    sa.Column('type_id', sa.UUID(), nullable=True),
    sa.Column('model_id', sa.UUID(), nullable=True),
    sa.Column('qty', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('price', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('number', sa.String(length=40), nullable=False),
    sa.Column('serial', sa.String(length=100), nullable=False),
    sa.Column('responsible', sa.String(length=150), nullable=False),
    sa.Column('department', sa.String(length=150), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=True),
    sa.Column('commissioned_on', sa.Date(), nullable=True),
    sa.Column('life_months', sa.Integer(), nullable=True),
    sa.Column('note', sa.String(length=300), nullable=False),
    sa.Column('values', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('from_place', sa.String(length=50), nullable=True),
    sa.Column('to_place', sa.String(length=50), nullable=True),
    sa.Column('reason', sa.String(length=300), nullable=False),
    sa.Column('new_value', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('created_units', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['inventory.document.id'], name=op.f('fk_doc_line_document_id_document'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['model_id'], ['catalog.model.id'], name=op.f('fk_doc_line_model_id_model')),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_doc_line_type_id_item_type')),
    sa.ForeignKeyConstraint(['unit_id'], ['inventory.unit.id'], name=op.f('fk_doc_line_unit_id_unit')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_doc_line')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_doc_line_document_id'), 'doc_line', ['document_id'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_doc_line_unit_id'), 'doc_line', ['unit_id'], unique=False, schema='inventory')
    op.create_table('unit_change',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('unit_id', sa.UUID(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_name', sa.String(length=200), nullable=False),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rolled_back', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['unit_id'], ['inventory.unit.id'], name=op.f('fk_unit_change_unit_id_unit'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_unit_change')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_unit_change_unit_id'), 'unit_change', ['unit_id'], unique=False, schema='inventory')
    op.create_table('unit_event',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('unit_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=True),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('place', sa.String(length=50), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=True),
    sa.Column('floor_id', sa.UUID(), nullable=True),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('value_base', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('value_date', sa.Date(), nullable=True),
    sa.Column('undone', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['unit_id'], ['inventory.unit.id'], name=op.f('fk_unit_event_unit_id_unit'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('seq', name=op.f('pk_unit_event')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_unit_event_date'), 'unit_event', ['date'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_unit_event_document_id'), 'unit_event', ['document_id'], unique=False, schema='inventory')
    op.create_index(op.f('ix_inventory_unit_event_unit_id'), 'unit_event', ['unit_id'], unique=False, schema='inventory')
    op.create_table('unit_file',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('unit_id', sa.UUID(), nullable=False),
    sa.Column('file_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['files.file.id'], name=op.f('fk_unit_file_file_id_file')),
    sa.ForeignKeyConstraint(['unit_id'], ['inventory.unit.id'], name=op.f('fk_unit_file_unit_id_unit'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_unit_file')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_unit_file_unit_id'), 'unit_file', ['unit_id'], unique=False, schema='inventory')
    op.create_table('warehouse',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=True),
    sa.Column('room_id', sa.UUID(), nullable=True),
    sa.Column('note', sa.String(length=300), nullable=False),
    sa.Column('label_code', sa.String(length=24), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['building_id'], ['building.building.id'], name=op.f('fk_warehouse_building_id_building')),
    sa.ForeignKeyConstraint(['room_id'], ['building.room.id'], name=op.f('fk_warehouse_room_id_room')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_warehouse')),
    sa.UniqueConstraint('label_code', name=op.f('uq_warehouse_label_code')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_warehouse_building_id'), 'warehouse', ['building_id'], unique=False, schema='inventory')
    op.create_table('cell',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('warehouse_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('label_code', sa.String(length=24), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['warehouse_id'], ['inventory.warehouse.id'], name=op.f('fk_cell_warehouse_id_warehouse'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cell')),
    sa.UniqueConstraint('label_code', name=op.f('uq_cell_label_code')),
    schema='inventory'
    )
    op.create_index(op.f('ix_inventory_cell_warehouse_id'), 'cell', ['warehouse_id'], unique=False, schema='inventory')


def downgrade() -> None:
    op.drop_index(op.f('ix_inventory_cell_warehouse_id'), table_name='cell', schema='inventory')
    op.drop_table('cell', schema='inventory')
    op.drop_index(op.f('ix_inventory_warehouse_building_id'), table_name='warehouse', schema='inventory')
    op.drop_table('warehouse', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_file_unit_id'), table_name='unit_file', schema='inventory')
    op.drop_table('unit_file', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_event_unit_id'), table_name='unit_event', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_event_document_id'), table_name='unit_event', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_event_date'), table_name='unit_event', schema='inventory')
    op.drop_table('unit_event', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_change_unit_id'), table_name='unit_change', schema='inventory')
    op.drop_table('unit_change', schema='inventory')
    op.drop_index(op.f('ix_inventory_doc_line_unit_id'), table_name='doc_line', schema='inventory')
    op.drop_index(op.f('ix_inventory_doc_line_document_id'), table_name='doc_line', schema='inventory')
    op.drop_table('doc_line', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_type_id'), table_name='unit', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_state'), table_name='unit', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_place'), table_name='unit', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_parent_id'), table_name='unit', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_model_id'), table_name='unit', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_floor_id'), table_name='unit', schema='inventory')
    op.drop_index(op.f('ix_inventory_unit_building_id'), table_name='unit', schema='inventory')
    op.drop_table('unit', schema='inventory')
    op.drop_index(op.f('ix_inventory_stock_move_type_id'), table_name='stock_move', schema='inventory')
    op.drop_index(op.f('ix_inventory_stock_move_place'), table_name='stock_move', schema='inventory')
    op.drop_index(op.f('ix_inventory_stock_move_document_id'), table_name='stock_move', schema='inventory')
    op.drop_index(op.f('ix_inventory_stock_move_date'), table_name='stock_move', schema='inventory')
    op.drop_index(op.f('ix_inventory_stock_move_building_id'), table_name='stock_move', schema='inventory')
    op.drop_table('stock_move', schema='inventory')
    op.drop_index(op.f('ix_inventory_doc_file_document_id'), table_name='doc_file', schema='inventory')
    op.drop_table('doc_file', schema='inventory')
    op.drop_index(op.f('ix_inventory_document_status'), table_name='document', schema='inventory')
    op.drop_index(op.f('ix_inventory_document_kind'), table_name='document', schema='inventory')
    op.drop_index(op.f('ix_inventory_document_date'), table_name='document', schema='inventory')
    op.drop_table('document', schema='inventory')
    op.execute("DROP SCHEMA IF EXISTS inventory")
