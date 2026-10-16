"""Этап 9: ссылки на просмотр здания для гостей без учётной записи.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('share_link',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.LargeBinary(length=32), nullable=False),
    sa.Column('building_id', sa.UUID(), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=False),
    sa.Column('created_by', sa.String(length=150), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('opened', sa.Integer(), nullable=False),
    sa.Column('last_opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_share_link')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_share_link_token_hash')),
    schema='access'
    )
    op.create_index(op.f('ix_access_share_link_building_id'), 'share_link', ['building_id'], unique=False, schema='access')


def downgrade() -> None:
    op.drop_table('share_link', schema='access')
