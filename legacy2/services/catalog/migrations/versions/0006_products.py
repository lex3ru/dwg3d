"""makes and models of a type: a product — vendor, model, article, supplier, list price — an object may name;
the set «Оргтехника» loses the vendor and the model it kept with the type, which are the product's now

Revision ID: 0006
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app import seed

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("type_id", sa.Uuid, sa.ForeignKey("types.id"), nullable=False, index=True),
        sa.Column("vendor", sa.Text, nullable=False, server_default=""),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("article", sa.Text),
        sa.Column("supplier", sa.Text),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("currency", sa.Text, nullable=False, server_default="RUB"),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("sort", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("type_id", "vendor", "name", name="uq_products_type_vendor_name"),
    )
    # the starter set «Оргтехника» as first seeded (migration 0005), unless an administrator has changed it since:
    # the vendor and the model go, the types with the set get a new schema version
    (office,) = [s for s in seed.OFFICE_SETS if s["id"] == seed.EQUIPMENT]
    bind = op.get_bind()
    changed = bind.execute(
        sa.text("UPDATE property_sets SET properties = CAST(:props AS jsonb), version = version + 1, "
                "updated_at = now() WHERE id = :id AND version = 1 AND properties @> CAST(:had AS jsonb) RETURNING id")
        .bindparams(sa.bindparam("props", json.dumps(office["properties"]), type_=JSONB),
                    sa.bindparam("had", json.dumps([{"key": "vendor"}, {"key": "model_no"}]), type_=JSONB),
                    id=seed.EQUIPMENT)).first()
    if changed:
        bind.execute(sa.text("UPDATE types SET schema_version = schema_version + 1, version = version + 1, "
                             "updated_at = now() WHERE :id = ANY(sets)").bindparams(id=seed.EQUIPMENT))


def downgrade() -> None:
    op.drop_table("products")
