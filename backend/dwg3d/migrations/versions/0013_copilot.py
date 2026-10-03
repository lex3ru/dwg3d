"""the built-in copilot: settings, chats, usage

app_settings keeps settings changed in the UI (the copilot's model endpoint,
key, model, limits); copilot_chats the conversations of a user in a project
(in the format of the model's API); copilot_usage the requests of a user a
day, for the daily limit.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_table(
        "copilot_chats",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("messages", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("copilot_chats_owner", "copilot_chats", ["project_id", "user_id", "updated_at"])
    op.create_table(
        "copilot_usage",
        sa.Column("user_key", sa.Text(), primary_key=True),          # user id, or "-" with sign-in off
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.BigInteger(), server_default="0", nullable=False),
    )


def downgrade():
    op.drop_table("copilot_usage")
    op.drop_table("copilot_chats")
    op.drop_table("app_settings")
