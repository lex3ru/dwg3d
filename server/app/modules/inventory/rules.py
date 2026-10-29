"""Справочные значения учёта и расчёт стоимости (5.4.5)."""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import ColumnElement, Date, Numeric, and_, case, cast, func, literal

CENT = Decimal("0.01")

STATES = {
    "in_use": "в работе",
    "broken": "неисправна",
    "repair": "в ремонте",
    "storage": "на хранении",
    "not_found": "не найдена",  # при инвентаризации — для разбирательства или списания (5.4.6)
    "written_off": "списана",
}
STATE_BY_TITLE = {v: k for k, v in STATES.items()}
# в карточке без документа меняется только это (5.4.2 п. 5)
CARD_STATES = ("in_use", "broken")

KINDS = {
    "opening": "Ввод остатков",
    "receipt": "Приход",
    "transfer": "Перемещение",
    "repair": "Ремонт",
    "writeoff": "Списание",
    "revaluation": "Переоценка",
    "inventory": "Инвентаризация",
}
# события единицы: документ, перенос из объединённого или убранного помещения, отмена
EVENTS = (*KINDS, "room_merge", "cancel")
STATUSES = ("draft", "posted", "cancelled")
# ключ места: помещение, склад или ячейка склада — проверяет и база (R-028)
PLACE_KEY = r"^[rwc]:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

PREFIX = {
    "opening": "ВО",
    "receipt": "ПР",
    "transfer": "ПМ",
    "repair": "РМ",
    "writeoff": "СП",
    "revaluation": "ПО",
    "inventory": "ИН",
}


def doc_title(kind: str, number: int) -> str:
    return f"{KINDS[kind]} {PREFIX[kind]}-{number:05d}"


def months_between(a: date, b: date) -> int:
    """Сколько полных месяцев прошло от a до b (не меньше нуля)."""
    months = (b.year - a.year) * 12 + b.month - a.month - (1 if b.day < a.day else 0)
    return max(0, months)


def _months_sql(a: Any, b: Any) -> Any:
    """months_between в базе."""
    months = (
        (func.extract("year", b) - func.extract("year", a)) * 12
        + func.extract("month", b) - func.extract("month", a)
        - case((func.extract("day", b) < func.extract("day", a), 1), else_=0)
    )
    return func.greatest(months, 0)


def _decimal(value: Decimal | float | None) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def residual(
    price: Decimal | float,
    commissioned_on: date,
    life_months: int | None,
    value_base: Decimal | float | None,
    value_date: date | None,
    at: date,
) -> float:
    """Остаточная стоимость на дату: равномерно по месяцам до нуля; после переоценки — от
    новой стоимости до конца срока службы. Считается в Decimal, копейки — «половина вверх»,
    как round() в PostgreSQL: residual_sql в базе даёт копейка в копейку то же (ADR-0017)."""
    if at < commissioned_on:
        return 0.0
    base, since, life = _decimal(price), commissioned_on, life_months
    if value_base is not None and value_date is not None and value_date <= at:
        base, since = _decimal(value_base), value_date
        if life:
            life = life - months_between(commissioned_on, value_date)
    if not life:
        return float(base.quantize(CENT, ROUND_HALF_UP))
    if life <= 0:
        return 0.0
    left = max(0, life - months_between(since, at))
    return float((base * left / life).quantize(CENT, ROUND_HALF_UP))


def residual_sql(
    price: Any, commissioned_on: Any, life_months: Any, value_base: Any, value_date: Any, at: Any
) -> Any:
    """residual в базе — над столбцами (или значениями) запроса: итоги по 50 000 единиц — одним
    агрегатом, без чтения строк (8.1, R-036). Ветви — те же, что у residual."""
    at = at if isinstance(at, ColumnElement) else literal(at, Date)
    revalued = and_(value_base.is_not(None), value_date.is_not(None), value_date <= at)
    base = case((revalued, value_base), else_=func.coalesce(price, 0))
    since = case((revalued, value_date), else_=commissioned_on)
    life = case(
        (and_(revalued, life_months != 0), life_months - _months_sql(commissioned_on, value_date)),
        else_=life_months,
    )
    left = func.greatest(life - _months_sql(since, at), 0)
    # делимое — с 12 знаками после запятой: частное получит не меньше, и копейки совпадут с
    # Decimal, как бы PostgreSQL ни выбирал точность деления (сам он даёт ≥ 8 знаков)
    return case(
        (at < commissioned_on, 0),
        (func.coalesce(life, 0) == 0, func.round(base, 2)),
        (life < 0, 0),
        else_=func.round(cast(base * left, Numeric(32, 12)) / life, 2),
    )


# ---------------------------------------------------------------- инвентарные номера


def number_pattern(template: str) -> tuple[str, int]:
    """«000000» → ("", 6); «ИН-0000» → ("ИН-", 4)."""
    m = re.fullmatch(r"(.*?)(0+)", template.strip())
    if not m:
        return template.strip(), 6
    return m.group(1), len(m.group(2))


def format_number(template: str, n: int) -> str:
    prefix, digits = number_pattern(template)
    return f"{prefix}{n:0{digits}d}"


def number_value(template: str, number: str) -> int | None:
    prefix, digits = number_pattern(template)
    if not number.startswith(prefix):
        return None
    rest = number[len(prefix) :]
    return int(rest) if rest.isdigit() else None
