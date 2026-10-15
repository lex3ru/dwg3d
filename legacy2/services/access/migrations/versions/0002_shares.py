"""links for guests and the key their tokens are signed with

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
NOW = sa.func.now()


def upgrade() -> None:
    op.create_table(
        "shares",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("building_id", sa.Uuid, nullable=False, index=True),
        sa.Column("scope_kind", sa.Text, nullable=False),
        sa.Column("scope_id", sa.Uuid, nullable=False),
        sa.Column("floor_id", sa.Uuid),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("opened", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_opened_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "signing_keys",
        sa.Column("kid", sa.Text, primary_key=True),
        sa.Column("private_pem", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )


def downgrade() -> None:
    op.drop_table("signing_keys")
    op.drop_table("shares")
