"""Целостность учёта держит и база (R-028, ADR-0009): состояния единиц, виды и статусы
документов, виды событий и файлов — только из перечня; движение остатка не нулевое; место —
ключ помещения, склада или ячейки («r:/w:/c:<uuid>»). Внешнего ключа у места нет — оно бывает
трёх видов; единицы в убранных и несуществующих местах показывает страница состояния.

Перед добавлением база проверяет имеющиеся строки: строка не по правилам остановит миграцию —
её нужно исправить (в рабочей установке таких строк быть не должно: всё пишет код).

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

STATES = "'in_use', 'broken', 'repair', 'storage', 'not_found', 'written_off'"
KINDS = "'opening', 'receipt', 'transfer', 'repair', 'writeoff', 'revaluation', 'inventory'"
PLACE = "'^[rwc]:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"

CHECKS = [
    ("unit", "state", f"state IN ({STATES})"),
    ("unit", "place", f"place ~ {PLACE}"),
    ("unit_file", "kind", "kind IN ('photo', 'doc')"),
    ("unit_event", "kind", f"kind IN ({KINDS}, 'room_merge', 'cancel')"),
    ("unit_event", "state", f"state IN ({STATES})"),
    ("unit_event", "place", f"place ~ {PLACE}"),
    ("document", "kind", f"kind IN ({KINDS})"),
    ("document", "status", "status IN ('draft', 'posted', 'cancelled')"),
    ("document", "from_place", f"from_place ~ {PLACE}"),
    ("document", "to_place", f"to_place ~ {PLACE}"),
    ("doc_line", "state", f"state IN ({STATES})"),
    ("doc_line", "from_place", f"from_place ~ {PLACE}"),
    ("doc_line", "to_place", f"to_place ~ {PLACE}"),
    ("stock_move", "place", f"place ~ {PLACE}"),
    ("stock_move", "qty", "qty <> 0"),
    ("count_place", "place", f"place ~ {PLACE}"),
    ("count_mark", "place", f"place ~ {PLACE}"),
    ("count_extra", "place", f"place ~ {PLACE}"),
    ("count_stock", "place", f"place ~ {PLACE}"),
]


def upgrade() -> None:
    for table, name, condition in CHECKS:
        op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition, schema='inventory')


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, schema='inventory', type_='check')
