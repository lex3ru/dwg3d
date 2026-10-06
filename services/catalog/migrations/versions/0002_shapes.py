"""the types of the first catalog are drawn in 3D as what they are: a CT scanner, a desk, a couch, a chair

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
SHAPES = {0x301: "ct", 0x302: "device", 0x303: "desk", 0x304: "couch", 0x305: "chair"}


def upgrade() -> None:
    for n, shape in SHAPES.items():
        op.execute(sa.text("UPDATE types SET shape = :shape WHERE id = CAST(:id AS uuid) AND shape = 'box'")
                   .bindparams(shape=shape, id=f"0192f000-0000-7000-8000-{n:012x}"))


def downgrade() -> None:
    pass
