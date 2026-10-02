"""roles of users from the client roles of Keycloak

The roles of the application now come from resource_access.<client_id>.roles
(dwg3d.admin, dwg3d.catalog_admin, dwg3d.user, dwg3d.<role>); users keep the
list as of their last sign-in. Realm roles are no longer read: until a user
signs in again, the global role stays as it was.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("roles", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False))


def downgrade():
    op.drop_column("users", "roles")
