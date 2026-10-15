"""outbox, inbox and the sample table

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from twin_chassis.migrate import create_chassis_tables

revision = "0001"
down_revision = None


def upgrade() -> None:
    create_chassis_tables()
    op.create_table(
        "notes",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_by", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("echoed_at", sa.DateTime(timezone=True)),
        sa.Column("echoes", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_notes_created_by", "notes", ["created_by"])


def downgrade() -> None:
    op.drop_table("notes")
    op.drop_table("inbox")
    op.drop_table("outbox")
