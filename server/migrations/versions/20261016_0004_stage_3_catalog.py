"""Этап 3: каталог — слои, наборы, характеристики, типы, модели, значения, назначения.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS catalog")
    op.create_table('char_set',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_char_set')),
    schema='catalog'
    )
    op.create_table('layer',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('color', sa.String(length=9), nullable=False),
    sa.Column('icon', sa.String(length=40), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('visible', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_layer')),
    schema='catalog'
    )
    op.create_table('purpose',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('surface', sa.Float(), nullable=False),
    sa.Column('norm', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_purpose')),
    schema='catalog'
    )
    op.create_table('item_type',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('layer_id', sa.UUID(), nullable=True),
    sa.Column('width', sa.Float(), nullable=True),
    sa.Column('depth', sa.Float(), nullable=True),
    sa.Column('height', sa.Float(), nullable=True),
    sa.Column('mount', sa.String(length=10), nullable=False),
    sa.Column('mount_height', sa.Float(), nullable=True),
    sa.Column('model_file_id', sa.UUID(), nullable=True),
    sa.Column('model_transform', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('model_size', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('top_view', sa.String(length=10), nullable=False),
    sa.Column('icon', sa.String(length=40), nullable=False),
    sa.Column('price', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('accounting', sa.String(length=10), nullable=False),
    sa.Column('unit', sa.String(length=20), nullable=False),
    sa.Column('life_months', sa.Integer(), nullable=True),
    sa.Column('container', sa.Boolean(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['layer_id'], ['catalog.layer.id'], name=op.f('fk_item_type_layer_id_layer')),
    sa.ForeignKeyConstraint(['model_file_id'], ['files.file.id'], name=op.f('fk_item_type_model_file_id_file')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_item_type')),
    schema='catalog'
    )
    op.create_index(op.f('ix_catalog_item_type_layer_id'), 'item_type', ['layer_id'], unique=False, schema='catalog')
    op.create_table('characteristic',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('set_id', sa.UUID(), nullable=True),
    sa.Column('type_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('unit', sa.String(length=20), nullable=False),
    sa.Column('choices', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['set_id'], ['catalog.char_set.id'], name=op.f('fk_characteristic_set_id_char_set'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_characteristic_type_id_item_type'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_characteristic')),
    schema='catalog'
    )
    op.create_index(op.f('ix_catalog_characteristic_set_id'), 'characteristic', ['set_id'], unique=False, schema='catalog')
    op.create_index(op.f('ix_catalog_characteristic_type_id'), 'characteristic', ['type_id'], unique=False, schema='catalog')
    op.create_table('model',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('type_id', sa.UUID(), nullable=False),
    sa.Column('manufacturer', sa.String(length=150), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('article', sa.String(length=100), nullable=False),
    sa.Column('supplier', sa.String(length=200), nullable=False),
    sa.Column('price', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_model_type_id_item_type'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model')),
    schema='catalog'
    )
    op.create_index(op.f('ix_catalog_model_type_id'), 'model', ['type_id'], unique=False, schema='catalog')
    op.create_table('type_set',
    sa.Column('type_id', sa.UUID(), nullable=False),
    sa.Column('set_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['set_id'], ['catalog.char_set.id'], name=op.f('fk_type_set_set_id_char_set'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_type_set_type_id_item_type'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('type_id', 'set_id', name=op.f('pk_type_set')),
    schema='catalog'
    )
    op.create_table('value',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('characteristic_id', sa.UUID(), nullable=False),
    sa.Column('type_id', sa.UUID(), nullable=True),
    sa.Column('model_id', sa.UUID(), nullable=True),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['characteristic_id'], ['catalog.characteristic.id'], name=op.f('fk_value_characteristic_id_characteristic'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['model_id'], ['catalog.model.id'], name=op.f('fk_value_model_id_model'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['type_id'], ['catalog.item_type.id'], name=op.f('fk_value_type_id_item_type'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_value')),
    sa.UniqueConstraint('characteristic_id', 'type_id', 'model_id', name='value_owner'),
    schema='catalog'
    )
    op.create_index(op.f('ix_catalog_value_characteristic_id'), 'value', ['characteristic_id'], unique=False, schema='catalog')
    op.create_index(op.f('ix_catalog_value_model_id'), 'value', ['model_id'], unique=False, schema='catalog')
    op.create_index(op.f('ix_catalog_value_type_id'), 'value', ['type_id'], unique=False, schema='catalog')


def downgrade() -> None:
    op.drop_index(op.f('ix_catalog_value_type_id'), table_name='value', schema='catalog')
    op.drop_index(op.f('ix_catalog_value_model_id'), table_name='value', schema='catalog')
    op.drop_index(op.f('ix_catalog_value_characteristic_id'), table_name='value', schema='catalog')
    op.drop_table('value', schema='catalog')
    op.drop_table('type_set', schema='catalog')
    op.drop_index(op.f('ix_catalog_model_type_id'), table_name='model', schema='catalog')
    op.drop_table('model', schema='catalog')
    op.drop_index(op.f('ix_catalog_characteristic_type_id'), table_name='characteristic', schema='catalog')
    op.drop_index(op.f('ix_catalog_characteristic_set_id'), table_name='characteristic', schema='catalog')
    op.drop_table('characteristic', schema='catalog')
    op.drop_index(op.f('ix_catalog_item_type_layer_id'), table_name='item_type', schema='catalog')
    op.drop_table('item_type', schema='catalog')
    op.drop_table('purpose', schema='catalog')
    op.drop_table('layer', schema='catalog')
    op.drop_table('char_set', schema='catalog')
    op.execute("DROP SCHEMA IF EXISTS catalog")
