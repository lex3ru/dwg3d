"""Фоновые задачи (ADR-0011): кто выполняет задачу и когда подавал голос — в очередь
возвращаются только задачи замолчавших обработчиков (R-013); просьба отменить задачу —
обработчик остановит её процесс (R-026). Статус `cancelled` — без изменения схемы.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('job', sa.Column('worker', sa.String(length=200), nullable=True), schema='core')
    op.add_column('job', sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
                  schema='core')
    op.add_column('job', sa.Column('cancel_requested_at', sa.DateTime(timezone=True),
                                   nullable=True), schema='core')


def downgrade() -> None:
    op.drop_column('job', 'cancel_requested_at', schema='core')
    op.drop_column('job', 'heartbeat_at', schema='core')
    op.drop_column('job', 'worker', schema='core')
