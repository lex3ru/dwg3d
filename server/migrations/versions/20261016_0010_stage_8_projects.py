"""Этап 8: проекты расстановки — проект и его изменения над расстановкой.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS projects")
    op.create_table('project',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_by', sa.String(length=150), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['building_id'], ['building.building.id'], name=op.f('fk_project_building_id_building'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project')),
    schema='projects'
    )
    op.create_index(op.f('ix_projects_project_building_id'), 'project', ['building_id'], unique=False, schema='projects')
    op.create_table('change',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('floor_id', sa.UUID(), nullable=False),
    sa.Column('item_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('base', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['floor_id'], ['building.floor.id'], name=op.f('fk_change_floor_id_floor'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.project.id'], name=op.f('fk_change_project_id_project'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_change')),
    schema='projects'
    )
    op.create_index(op.f('ix_projects_change_floor_id'), 'change', ['floor_id'], unique=False, schema='projects')
    op.create_index(op.f('ix_projects_change_item_id'), 'change', ['item_id'], unique=False, schema='projects')
    op.create_index(op.f('ix_projects_change_project_id'), 'change', ['project_id'], unique=False, schema='projects')


def downgrade() -> None:
    op.drop_table('change', schema='projects')
    op.drop_table('project', schema='projects')
    op.execute("DROP SCHEMA IF EXISTS projects")
