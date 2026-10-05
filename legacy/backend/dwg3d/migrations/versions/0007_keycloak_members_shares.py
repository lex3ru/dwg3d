"""sign-in through Keycloak, project members, share links

Users come from Keycloak (OpenID Connect): a user row is keyed by the
token subject and keeps no password; the global role follows the realm
roles (admin, catalog_admin, else user). Sessions keep the refresh token.
Access to a project: project_members (owner, editor, viewer; an invitation
by e-mail waits with user_id NULL until that user signs in). Share links
give read-only access to a project without an account.

Also creates the schema of Keycloak's own tables (the keycloak service
starts after the API has migrated).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

TS = dict(server_default=sa.text("now()"), nullable=False)


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS keycloak")

    # ---- users from Keycloak
    op.execute("DELETE FROM sessions")                 # password sessions: everyone signs in again
    op.add_column("users", sa.Column("sub", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("email", sa.Text(), nullable=True))
    op.create_index("users_sub", "users", ["sub"], unique=True)
    op.drop_column("users", "password_hash")
    op.drop_constraint("users_role", "users", type_="check")
    op.execute("UPDATE users SET role = CASE role WHEN 'catalog_admin' THEN 'catalog_admin' ELSE 'user' END")
    op.alter_column("users", "role", server_default="user")
    op.create_check_constraint("users_role", "users", "role IN ('user', 'catalog_admin', 'admin')")
    op.add_column("sessions", sa.Column("id_token", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("refresh_token", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("refreshed_at", sa.DateTime(timezone=True), **TS))

    # ---- project members
    op.create_table(
        "project_members",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **TS),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="project_members_role"),
        sa.CheckConstraint("user_id IS NOT NULL OR email IS NOT NULL", name="project_members_who"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id"),
    )
    op.create_index("project_members_user", "project_members", ["user_id"])
    op.create_index("project_members_invite", "project_members", ["project_id", sa.text("lower(email)")],
                    unique=True, postgresql_where=sa.text("user_id IS NULL"))
    op.execute("""INSERT INTO project_members (project_id, user_id, role)
                  SELECT id, created_by, 'owner' FROM projects WHERE created_by IS NOT NULL""")

    # ---- share links
    op.create_table(
        "share_links",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), server_default="", nullable=False),
        sa.Column("drawings", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("layers", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **TS),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_share_links_project_id", "share_links", ["project_id"])


def downgrade():
    op.drop_table("share_links")
    op.drop_table("project_members")
    op.drop_column("sessions", "refreshed_at")
    op.drop_column("sessions", "refresh_token")
    op.drop_column("sessions", "id_token")
    op.execute("DELETE FROM sessions")
    op.drop_constraint("users_role", "users", type_="check")
    op.execute("UPDATE users SET role = CASE role WHEN 'user' THEN 'viewer' ELSE 'catalog_admin' END")
    op.alter_column("users", "role", server_default="viewer")
    op.create_check_constraint("users_role", "users", "role IN ('viewer', 'editor', 'catalog_admin')")
    # passwords are gone: users must get new ones (python -m dwg3d user passwd)
    op.add_column("users", sa.Column("password_hash", sa.Text(), server_default="!", nullable=False))
    op.drop_index("users_sub", table_name="users")
    op.drop_column("users", "email")
    op.drop_column("users", "sub")
