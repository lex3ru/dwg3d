"""Остаточная стоимость (5.4.5 п. 4): одна и та же в Python и в базе (R-036, ADR-0017) —
итоги реестра и главной считает база, карточку и ведомость на дату — Python."""

import itertools
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, column, select, values

from app.core.db import transaction
from app.modules.inventory.rules import residual, residual_sql

D = date(2020, 1, 31)


def test_residual_rounds_half_up_to_kopecks() -> None:
    # 1 ₽ на 8 месяцев, прошло 7: осталось ровно 0,125 ₽ — «половина вверх», а не к чётному
    assert residual(Decimal("1.00"), D, 8, None, None, date(2020, 8, 31)) == 0.13
    assert residual(Decimal("100.00"), D, 3, None, None, date(2020, 3, 1)) == 66.67
    assert residual(Decimal("14500.00"), D, None, None, None, date(2030, 1, 1)) == 14500.0
    assert residual(Decimal("14500.00"), D, 60, None, None, date(2019, 12, 31)) == 0.0
    assert residual(Decimal("14500.00"), D, 60, None, None, date(2025, 1, 31)) == 0.0
    # месяц не прошёл: 31 января → 29 февраля — ноль полных месяцев
    assert residual(Decimal("12.00"), D, 12, None, None, date(2020, 2, 29)) == 12.0
    # после переоценки — от новой стоимости до конца срока службы: 60 − 12 = 48 месяцев
    revalued = residual(Decimal("14500.00"), D, 60, Decimal("9000.00"), date(2021, 1, 31),
                        date(2022, 1, 31))
    assert revalued == 6750.0


def test_r036_residual_in_database_equals_python() -> None:
    """Сетка случаев: цены с копейками и большие, сроки (нет, 0, короткие, длинные), даты на
    краях месяцев, переоценка до и после даты расчёта. База и Python — копейка в копейку."""
    prices = ["0", "0.01", "1.00", "2.68", "99.99", "100.00", "1234.56", "14500.00",
              "2500000.50", "999999999999.99"]
    lives = [None, 0, 1, 3, 7, 8, 12, 60, 120, 1200]
    starts = [date(2020, 1, 31), date(2020, 2, 29), date(2021, 6, 15)]
    ats = [date(2019, 12, 31), date(2020, 1, 31), date(2020, 2, 28), date(2020, 3, 31),
           date(2020, 8, 31), date(2021, 6, 14), date(2023, 7, 1), date(2120, 1, 1)]
    revaluations = [(None, None), ("777.77", date(2020, 6, 30)), ("5000.00", date(2022, 1, 1)),
                    (None, date(2020, 6, 30))]
    cases = [
        (Decimal(p), s, life, Decimal(vb) if vb else None, vd, at)
        for p, life, s, at, (vb, vd) in itertools.product(prices, lives, starts, ats, revaluations)
    ]
    table = values(
        column("price", Numeric(14, 2)), column("commissioned_on", Date),
        column("life_months", Integer), column("value_base", Numeric(14, 2)),
        column("value_date", Date), column("at", Date), name="cases",
    ).data(cases)
    c = table.c
    with transaction() as session:
        got = session.scalars(select(residual_sql(
            c.price, c.commissioned_on, c.life_months, c.value_base, c.value_date, c.at
        )).select_from(table)).all()
    want = [residual(*case) for case in cases]
    differ = [(case, w, float(g)) for case, w, g in zip(cases, want, got, strict=True)
              if Decimal(str(w)) != g]
    assert not differ, differ[:5]
    assert len(cases) > 3000
