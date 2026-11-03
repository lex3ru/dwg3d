"""Конфигурация подсчёта и события проходов (ADR-0028)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("counting_config",
                    sa.Column("item_id", pg.UUID(), nullable=False),
                    sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
                    sa.Column("state", sa.String(20), nullable=True),
                    sa.Column("settings", pg.JSONB(), nullable=False),
                    sa.Column("version", sa.Integer(), nullable=False),
                    sa.ForeignKeyConstraint(["item_id"], ["surveillance.connection.item_id"],
                                            ondelete="CASCADE"),
                    sa.PrimaryKeyConstraint("item_id"), schema="surveillance")
    op.create_table("passage",
                    sa.Column("id", pg.UUID(), nullable=False),
                    sa.Column("camera_id", pg.UUID(), nullable=False),
                    sa.Column("version", sa.Integer(), nullable=False),
                    sa.Column("door", sa.String(100), nullable=False),
                    sa.Column("direction", sa.String(3), nullable=False),
                    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False,
                              server_default=sa.func.now()),
                    sa.ForeignKeyConstraint(["camera_id"], ["surveillance.connection.item_id"],
                                            ondelete="CASCADE"),
                    sa.PrimaryKeyConstraint("id"), schema="surveillance")
    op.create_index("ix_surveillance_passage_camera_id", "passage", ["camera_id"], schema="surveillance")


def downgrade():
    op.drop_table("passage", schema="surveillance")
    op.drop_table("counting_config", schema="surveillance")
