"""outbox, inbox, persons

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from twin_chassis.migrate import create_chassis_tables

revision = "0001"
down_revision = None
NOW = sa.func.now()


def upgrade() -> None:
    create_chassis_tables()
    op.create_table(
        "persons",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("position", sa.Text, nullable=False, server_default=""),
        sa.Column("department", sa.Text, nullable=False, server_default=""),
        sa.Column("email", sa.Text),
        sa.Column("phone", sa.Text),
        sa.Column("user_sub", sa.Text, unique=True),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("left_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status in ('active', 'left')", name="status"),
    )
    op.create_index("ix_persons_email", "persons", ["email"])
    op.create_index("ix_persons_department", "persons", ["department"])


def downgrade() -> None:
    for table in ("persons", "inbox", "outbox"):
        op.drop_table(table)
