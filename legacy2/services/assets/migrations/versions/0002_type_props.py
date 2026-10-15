"""what the catalog says of a type as a whole: the values kept with the type, for the object's card

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.add_column("type_schemas", sa.Column("type_props", JSONB, nullable=False, server_default="[]"))
    op.execute("DELETE FROM type_schemas")      # asked of the catalog anew, now with the values of the type


def downgrade() -> None:
    op.drop_column("type_schemas", "type_props")
