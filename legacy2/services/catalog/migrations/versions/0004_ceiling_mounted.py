"""what hangs on the ceiling: a type may be mounted on the ceiling, and hangs under the ceiling of its floor,
whatever the floor's height; the lights, ceiling cameras, detectors and access points of the starter catalog are

Revision ID: 0004
"""
import sqlalchemy as sa
from alembic import op

from app import seed

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.add_column("types", sa.Column("ceiling_mounted", sa.Boolean, nullable=False, server_default="false"))
    # the starter types, unless an administrator has hung one on a wall since
    ids = [t["id"] for t in seed.MORE_TYPES if t["ceiling_mounted"]]
    op.execute(sa.text("UPDATE types SET ceiling_mounted = true WHERE id = ANY(:ids) AND NOT wall_mounted")
               .bindparams(sa.bindparam("ids", ids, type_=sa.ARRAY(sa.Uuid))))


def downgrade() -> None:
    op.drop_column("types", "ceiling_mounted")
