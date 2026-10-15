"""an object may stand on the plan without an inventory number: it is put on the books later, or never

Revision ID: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.alter_column("assets", "inventory_no", existing_type=sa.Text, nullable=True)


def downgrade() -> None:
    op.execute("delete from assets where inventory_no is null")
    op.alter_column("assets", "inventory_no", existing_type=sa.Text, nullable=False)
