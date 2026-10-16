"""Справочные значения учёта и расчёт стоимости (5.4.5)."""

import re
from datetime import date
from decimal import Decimal

STATES = {
    "in_use": "в работе",
    "broken": "неисправна",
    "repair": "в ремонте",
    "storage": "на хранении",
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
}
PREFIX = {
    "opening": "ВО",
    "receipt": "ПР",
    "transfer": "ПМ",
    "repair": "РМ",
    "writeoff": "СП",
    "revaluation": "ПО",
}


def doc_title(kind: str, number: int) -> str:
    return f"{KINDS[kind]} {PREFIX[kind]}-{number:05d}"


def months_between(a: date, b: date) -> int:
    """Сколько полных месяцев прошло от a до b (не меньше нуля)."""
    months = (b.year - a.year) * 12 + b.month - a.month - (1 if b.day < a.day else 0)
    return max(0, months)


def residual(
    price: Decimal | float,
    commissioned_on: date,
    life_months: int | None,
    value_base: Decimal | float | None,
    value_date: date | None,
    at: date,
) -> float:
    """Остаточная стоимость на дату: равномерно по месяцам до нуля; после переоценки — от
    новой стоимости до конца срока службы."""
    if at < commissioned_on:
        return 0.0
    base, since, life = float(price or 0), commissioned_on, life_months
    if value_base is not None and value_date is not None and value_date <= at:
        base, since = float(value_base), value_date
        if life:
            life = life - months_between(commissioned_on, value_date)
    if not life:
        return round(base, 2)
    if life <= 0:
        return 0.0
    left = max(0.0, 1 - months_between(since, at) / life)
    return round(base * left, 2)


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
