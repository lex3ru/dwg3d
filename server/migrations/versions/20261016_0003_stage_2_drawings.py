"""Этап 2: загруженные чертежи и откуда переведён план этажа.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('drawing',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=False),
    sa.Column('file_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.String(length=2000), nullable=True),
    sa.Column('parts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('job_id', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['building_id'], ['building.building.id'], name=op.f('fk_drawing_building_id_building'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['file_id'], ['files.file.id'], name=op.f('fk_drawing_file_id_file')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_drawing')),
    schema='building'
    )
    op.create_index(op.f('ix_building_drawing_building_id'), 'drawing', ['building_id'], unique=False, schema='building')
    op.add_column('floor', sa.Column('source_drawing_id', sa.UUID(), nullable=True), schema='building')
    op.add_column('floor', sa.Column('source_part', sa.String(length=20), nullable=True), schema='building')
    op.create_foreign_key(op.f('fk_floor_source_drawing_id_drawing'), 'floor', 'drawing', ['source_drawing_id'], ['id'], source_schema='building', referent_schema='building', ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_floor_source_drawing_id_drawing'), 'floor', schema='building', type_='foreignkey')
    op.drop_column('floor', 'source_part', schema='building')
    op.drop_column('floor', 'source_drawing_id', schema='building')
    op.drop_index(op.f('ix_building_drawing_building_id'), table_name='drawing', schema='building')
    op.drop_table('drawing', schema='building')
