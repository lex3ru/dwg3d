"""users sessions

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30 15:38:02.155140
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('login', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), server_default='', nullable=False),
    sa.Column('role', sa.Text(), server_default='viewer', nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("role IN ('viewer', 'editor', 'catalog_admin')", name='users_role'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('users_login', 'users', [sa.literal_column('lower(login)')], unique=True)
    op.create_table('sessions',
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('user_agent', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.add_column('audit_log', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_foreign_key('audit_log_user_id_fkey', 'audit_log', 'users', ['user_id'], ['id'], ondelete='SET NULL')
    op.add_column('pins', sa.Column('updated_by', sa.Integer(), nullable=True))
    op.create_foreign_key('pins_updated_by_fkey', 'pins', 'users', ['updated_by'], ['id'], ondelete='SET NULL')
    op.add_column('placements', sa.Column('updated_by', sa.Integer(), nullable=True))
    op.create_foreign_key('placements_updated_by_fkey', 'placements', 'users', ['updated_by'], ['id'], ondelete='SET NULL')
    op.add_column('projects', sa.Column('created_by', sa.Integer(), nullable=True))
    op.create_foreign_key('projects_created_by_fkey', 'projects', 'users', ['created_by'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('projects_created_by_fkey', 'projects', type_='foreignkey')
    op.drop_column('projects', 'created_by')
    op.drop_constraint('placements_updated_by_fkey', 'placements', type_='foreignkey')
    op.drop_column('placements', 'updated_by')
    op.drop_constraint('pins_updated_by_fkey', 'pins', type_='foreignkey')
    op.drop_column('pins', 'updated_by')
    op.drop_constraint('audit_log_user_id_fkey', 'audit_log', type_='foreignkey')
    op.drop_column('audit_log', 'user_id')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index('users_login', table_name='users')
    op.drop_table('users')
