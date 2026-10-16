"""Миграции приводят базу в точности к тому, что описано в models.py."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.core.db import Base, engine
from app.models import load_all
from app.modules import TIERS


def test_migrations_match_models() -> None:
    load_all()
    with engine().connect() as conn:
        context = MigrationContext.configure(conn, opts={
            "include_schemas": True, "compare_type": True,
            "include_name": lambda name, type_, _: type_ != "schema"
            or name in {"core", *TIERS},
        })
        diff = [d for d in compare_metadata(context, Base.metadata)
                if not (isinstance(d, tuple) and d[0] in {"remove_table"}
                        and d[1].name == "alembic_version")]
    assert not diff, diff
