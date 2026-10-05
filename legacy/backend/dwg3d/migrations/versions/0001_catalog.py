"""catalog

Revision ID: 0001
Revises: 
Create Date: 2026-09-30 12:31:48.646990
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('catalog_categories',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('color', sa.Text(), server_default='#868e96', nullable=False),
    sa.Column('sort', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('catalog_items',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('category_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('w', sa.Float(), nullable=False),
    sa.Column('d', sa.Float(), nullable=False),
    sa.Column('h', sa.Float(), nullable=False),
    sa.Column('elev', sa.Float(), nullable=True),
    sa.Column('clear', sa.Float(), nullable=True),
    sa.Column('wall', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('color', sa.Text(), nullable=True),
    sa.Column('model', sa.Text(), nullable=True),
    sa.Column('model_rot', sa.Float(), nullable=True),
    sa.Column('camera', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('tags', sa.Text(), nullable=True),
    sa.Column('article', sa.Text(), nullable=True),
    sa.Column('supplier', sa.Text(), nullable=True),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('currency', sa.CHAR(length=3), server_default='RUB', nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['catalog_categories.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_catalog_items_category_id'), 'catalog_items', ['category_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_catalog_items_category_id'), table_name='catalog_items')
    op.drop_table('catalog_items')
    op.drop_table('catalog_categories')
