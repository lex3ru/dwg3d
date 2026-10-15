"""outbox, inbox, subjects, grants

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
        "subjects",
        sa.Column("user_sub", sa.Text, primary_key=True),
        sa.Column("person_id", sa.Uuid, nullable=False, unique=True),
    )
    op.create_table(
        "grants",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("person_id", sa.Uuid, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("scope_kind", sa.Text, nullable=False),
        sa.Column("scope_id", sa.Uuid, nullable=False),
        sa.Column("building_id", sa.Uuid, nullable=False),
        sa.Column("origin", sa.Text, nullable=False, server_default="manual"),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("person_id", "role", "scope_kind", "scope_id", "origin", name="uq_grants_once"),
        sa.CheckConstraint("role in ('viewer', 'responsible', 'admin')", name="role"),
        sa.CheckConstraint("scope_kind in ('building', 'floor', 'room', 'asset')", name="scope_kind"),
    )
    op.create_index("ix_grants_person_id", "grants", ["person_id"])
    op.create_index("ix_grants_building_id", "grants", ["building_id"])
    op.create_index("ix_grants_scope", "grants", ["scope_kind", "scope_id"])


def downgrade() -> None:
    for table in ("grants", "subjects", "inbox", "outbox"):
        op.drop_table(table)
