"""projects builds jobs floors

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30 13:27:25.981368
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('projects',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('filename', sa.Text(), nullable=False),
    sa.Column('input_path', sa.Text(), nullable=False),
    sa.Column('size', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('site', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('view', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('current_build', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('builds',
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('n', sa.Integer(), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('out_dir', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('project_id', 'n')
    )
    op.create_table('floors',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('anchor', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('candidate', sa.Text(), nullable=True),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('level', sa.Integer(), nullable=True),
    sa.Column('elevation', sa.Float(), nullable=True),
    sa.Column('height', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'candidate')
    )
    op.create_index(op.f('ix_floors_project_id'), 'floors', ['project_id'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('project_id', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='queued', nullable=False),
    sa.Column('stage', sa.Text(), server_default='queued', nullable=False),
    sa.Column('progress', sa.Float(), server_default='0', nullable=False),
    sa.Column('message', sa.Text(), server_default='', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('trace', sa.Text(), nullable=True),
    sa.Column('worker', sa.Text(), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'running', 'done', 'error')", name='jobs_status'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_project_id'), 'jobs', ['project_id'], unique=False)
    op.create_index('jobs_one_active', 'jobs', ['project_id'], unique=True, postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_index('jobs_queue', 'jobs', ['status', 'id'], unique=False)


def downgrade():
    op.drop_index('jobs_queue', table_name='jobs')
    op.drop_index('jobs_one_active', table_name='jobs', postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.drop_index(op.f('ix_jobs_project_id'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_floors_project_id'), table_name='floors')
    op.drop_table('floors')
    op.drop_table('builds')
    op.drop_table('projects')
