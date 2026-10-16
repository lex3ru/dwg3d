"""Миграции базы. Схема каждого модуля описана его models.py; миграции пишутся по ним
(`alembic revision --autogenerate`) и проверяются тестом tests/test_migrations.py."""

from alembic import context
from sqlalchemy import Connection, text

from app.core.db import Base, engine
from app.models import load_all

load_all()
target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    if type_ == "schema":
        return name in {"core", *__import__("app.modules", fromlist=["TIERS"]).TIERS}
    return True


def run() -> None:
    connection = context.config.attributes.get("connection")
    if connection is None:
        with engine().connect() as connection:
            _run(connection)
            connection.commit()
    else:
        _run(connection)


def _run(connection: Connection) -> None:
    # таблица версий лежит в схеме ядра; на пустой базе её ещё нет
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
    context.configure(connection=connection, target_metadata=target_metadata,
                      include_schemas=True, include_name=include_name,
                      version_table_schema="core", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run()
