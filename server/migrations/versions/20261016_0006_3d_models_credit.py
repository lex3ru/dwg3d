"""3D-модели каталога: откуда модель и на каких условиях (автор, лицензия).

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('item_type', sa.Column('model_credit', sa.String(length=300), nullable=True), schema='catalog')


def downgrade() -> None:
    op.drop_column('item_type', 'model_credit', schema='catalog')
