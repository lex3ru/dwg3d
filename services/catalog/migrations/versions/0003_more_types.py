"""more types in the catalog: the furniture and the medical equipment of the old program's catalog

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app import seed

revision = "0003"
down_revision = "0002"

types = sa.table(
    "types",
    *(sa.column(c) for c in ("id", "category_id", "name", "w", "d", "h", "shape", "color", "container", "portable",
                             "sort", "elevation", "wall_mounted")),
    sa.column("sets", ARRAY(sa.Uuid)), sa.column("properties", JSONB), sa.column("values", JSONB),
)
COLUMNS = ("id", "category_id", "name", "w", "d", "h", "shape", "color", "container", "portable", "sort",
           "elevation", "wall_mounted", "sets", "properties", "values")


categories = sa.table("categories", *(sa.column(c) for c in ("id", "name", "color", "sort")))
sets = sa.table("property_sets", *(sa.column(c) for c in ("id", "name", "description")),
                sa.column("properties", JSONB))


def _missing(table: str, rows: list[dict]) -> list[dict]:
    have = {row[0] for row in op.get_bind().execute(sa.text(f"SELECT id FROM {table}"))}
    return [r for r in rows if r["id"] not in have]


def upgrade() -> None:
    if rows := _missing("categories", seed.EXTRA_CATEGORIES):
        op.bulk_insert(categories, rows)
    if rows := _missing("property_sets", seed.EXTRA_SETS):
        op.bulk_insert(sets, rows)
    have = {row[0] for row in op.get_bind().execute(sa.text("SELECT id FROM types"))}
    rows = [{c: t[c] for c in COLUMNS} for t in seed.MORE_TYPES if t["id"] not in have]
    if rows:
        op.bulk_insert(types, rows)


def downgrade() -> None:
    pass
