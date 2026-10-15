"""the office in the catalog: furniture of workplaces and meeting rooms, and a section of office equipment —
printers, computers, screens, the kitchen — with a property set of its own

Revision ID: 0005
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app import seed

revision = "0005"
down_revision = "0004"

COLUMNS = ("id", "category_id", "name", "w", "d", "h", "shape", "color", "container", "portable", "sort",
           "elevation", "wall_mounted", "ceiling_mounted")
types = sa.table("types", *(sa.column(c) for c in COLUMNS),
                 sa.column("sets", ARRAY(sa.Uuid)), sa.column("properties", JSONB), sa.column("values", JSONB))
categories = sa.table("categories", *(sa.column(c) for c in ("id", "name", "color", "sort")))
sets = sa.table("property_sets", *(sa.column(c) for c in ("id", "name", "description")), sa.column("properties", JSONB))


def _missing(table: str, rows: list[dict]) -> list[dict]:
    have = {row[0] for row in op.get_bind().execute(sa.text(f"SELECT id FROM {table}"))}
    return [r for r in rows if r["id"] not in have]


def upgrade() -> None:
    if rows := _missing("categories", seed.OFFICE_CATEGORIES):
        op.bulk_insert(categories, rows)
    if rows := _missing("property_sets", seed.OFFICE_SETS):
        op.bulk_insert(sets, rows)
    if rows := _missing("types", seed.OFFICE_TYPES):
        op.bulk_insert(types, [{c: t[c] for c in (*COLUMNS, "sets", "properties", "values")} for t in rows])


def downgrade() -> None:
    pass
