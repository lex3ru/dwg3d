"""outbox, inbox, drawings, their files and builds

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from twin_chassis.migrate import create_chassis_tables

revision = "0001"
down_revision = None
NOW = sa.func.now()


def upgrade() -> None:
    create_chassis_tables()
    op.create_table(
        "drawings",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("building_id", sa.Uuid, nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("current_file_id", sa.Uuid),
        sa.Column("current_build_id", sa.Uuid),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_drawings_building_id", "drawings", ["building_id"])
    op.create_table(
        "drawing_files",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("drawing_id", sa.Uuid, sa.ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("n", sa.Integer, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("uploaded_by", sa.Text, nullable=False, server_default=""),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("drawing_id", "n", name="uq_drawing_files_drawing_id"),
    )
    op.create_index("ix_drawing_files_drawing_id", "drawing_files", ["drawing_id"])
    op.create_table(
        "builds",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("drawing_id", sa.Uuid, sa.ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", sa.Uuid, sa.ForeignKey("drawing_files.id"), nullable=False),
        sa.Column("n", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("stage", sa.Text, nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float, nullable=False, server_default="0"),
        sa.Column("message", sa.Text, nullable=False, server_default=""),
        sa.Column("error", sa.Text),
        sa.Column("trace", sa.Text),
        sa.Column("config", JSONB),
        sa.Column("result", JSONB),
        sa.Column("out_prefix", sa.Text),
        sa.Column("requested_by", sa.Text, nullable=False, server_default=""),
        sa.Column("worker", sa.Text),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status in ('queued', 'running', 'done', 'error')", name="status"),
    )
    op.create_index("ix_builds_drawing_id", "builds", ["drawing_id"])
    op.create_index("ix_builds_queue", "builds", ["created_at"], postgresql_where=sa.text("status = 'queued'"))


def downgrade() -> None:
    for table in ("builds", "drawing_files", "drawings", "inbox", "outbox"):
        op.drop_table(table)
