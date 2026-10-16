"""Отчёты (5.6): каждый отчёт — отдельный шаблон (1.5): что спрашивает (параметры), в каких
форматах выдаётся, как строится. Новый отчёт — ещё одно описание, страница «Отчёты» его
покажет сама. Все отчёты — у администратора.

Модуль — над всеми (уровень 6): берёт данные у здания, каталога, планировки, учёта, связи,
расчётов и проектов только через их api.
"""

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core import report
from app.core.actor import Actor
from app.core.errors import AppError, Forbidden, NotFound
from app.modules.building import api as building
from app.modules.calc import api as calc
from app.modules.catalog import api as catalog
from app.modules.inventory import api as inventory
from app.modules.link import api as link
from app.modules.planning import api as planning
from app.modules.projects import api as projects
from app.modules.system import api as system

PDF, XLSX, DXF = "pdf", "xlsx", "dxf"


@dataclass
class Param:
    key: str
    title: str
    kind: str  # building floor place date project count document choice layers
    required: bool = True
    choices: list[tuple[str, str]] = field(default_factory=list)
    multiple: bool = False


@dataclass
class Definition:
    key: str
    title: str
    about: str
    formats: list[str]
    params: list[Param]
    build: Callable[["Ctx"], tuple[bytes, str]]
    scenarios: str = ""


@dataclass
class Ctx:
    session: Session
    actor: Actor
    params: dict[str, str]
    fmt: str
    base_url: str

    def get(self, key: str) -> str:
        v = (self.params.get(key) or "").strip()
        return v

    def id(self, key: str) -> uuid.UUID | None:
        v = self.get(key)
        if not v:
            return None
        try:
            return uuid.UUID(v)
        except ValueError:
            raise AppError("Неверный параметр.", field=key) from None

    def need_uuid(self, key: str, what: str) -> uuid.UUID:
        v = self.id(key)
        if v is None:
            raise AppError(f"Выберите {what}.", field=key)
        return v

    def date(self, key: str, default: date | None = None) -> date:
        v = self.get(key)
        if not v:
            if default is None:
                raise AppError("Укажите дату.", field=key)
            return default
        try:
            return date.fromisoformat(v)
        except ValueError:
            raise AppError("Дата — в виде ГГГГ-ММ-ДД.", field=key) from None

    def org(self) -> str:
        return str(system.get(self.session, "organization_name") or "")


def _out(ctx: Ctx, r: report.Report, name: str) -> tuple[bytes, str]:
    if ctx.fmt == PDF:
        return report.pdf(r), f"{name}.pdf"
    return report.xlsx(r), f"{name}.xlsx"


# ---------------------------------------------------------------- отчёты


def _registry(ctx: Ctx) -> tuple[bytes, str]:
    filters: dict[str, Any] = {}
    if ctx.id("building_id"):
        filters["building_id"] = ctx.id("building_id")
    if ctx.get("place"):
        filters["place"] = ctx.get("place")
    if ctx.get("state"):
        filters["state"] = ctx.get("state")
    return inventory.registry_xlsx(ctx.session, ctx.actor, **filters), "Реестр имущества.xlsx"


def _balances(ctx: Ctx) -> tuple[bytes, str]:
    at = ctx.date("at", date.today())
    rows = inventory.balance_rows(
        ctx.session,
        ctx.actor,
        at=at,
        place=ctx.get("place") or None,
        building_id=ctx.id("building_id"),
    )
    r = report.Report(
        title="Остатки по местам хранения",
        subtitle=f"на {at:%d.%m.%Y}",
        organization=ctx.org(),
        sections=[
            report.Section(
                "Остатки",
                ["Место", "Тип", "Модель", "Ед.", "Количество", "Средняя цена", "Сумма"],
                [
                    [
                        x["place_title"],
                        x["type_name"],
                        x["model_name"],
                        x["unit"],
                        x["qty"],
                        x.get("avg_price", 0.0),
                        x.get("amount", 0.0),
                    ]
                    for x in rows
                ],
                total=[
                    "Итого",
                    "",
                    "",
                    "",
                    "",
                    "",
                    round(sum(x.get("amount", 0.0) for x in rows), 2),
                ],
                numeric={4, 5, 6},
            )
        ],
    )
    return _out(ctx, r, f"Остатки на {at:%d.%m.%Y}")


def _movement(ctx: Ctx) -> tuple[bytes, str]:
    since, until = ctx.date("since"), ctx.date("until", date.today())
    if since > until:
        raise AppError("Начало периода — позже конца.", field="since")
    rows = inventory.movement_rows(ctx.session, ctx.actor, since, until, ctx.id("building_id"))
    r = report.Report(
        title="Движение имущества за период",
        subtitle=f"с {since:%d.%m.%Y} по {until:%d.%m.%Y}",
        organization=ctx.org(),
        sections=[
            report.Section(
                "Движение",
                [
                    "Дата",
                    "Документ",
                    "Что",
                    "Кол-во",
                    "Ед.",
                    "Откуда",
                    "Куда",
                    "Сумма",
                    "Примечание",
                ],
                [
                    [
                        x["date"].strftime("%d.%m.%Y"),
                        x["document"] + (f" ({x['status']})" if x["status"] else ""),
                        x["what"],
                        x["qty"],
                        x["unit"],
                        x["from"],
                        x["to"],
                        x["amount"],
                        x["note"],
                    ]
                    for x in rows
                ],
                numeric={3, 7},
            )
        ],
    )
    return _out(ctx, r, f"Движение {since:%d.%m.%Y}–{until:%d.%m.%Y}")


GROUPS = [
    ("building", "здание"),
    ("floor", "этаж"),
    ("place", "место"),
    ("layer", "слой"),
    ("type", "тип"),
    ("department", "подразделение"),
]


def _cost(ctx: Ctx) -> tuple[bytes, str]:
    at = ctx.date("at", date.today())
    group_by = [g for g in ctx.get("group_by").split(",") if g] or ["floor"]
    st = inventory.cost_statement(ctx.session, ctx.actor, at, group_by, ctx.id("building_id"))
    if ctx.fmt == XLSX:
        return inventory.cost_xlsx(st), f"Стоимость на {at:%d.%m.%Y}.xlsx"
    rows = [
        [*x["group"], x["units"], x["stock_positions"], x["initial"], x["value"]]
        for x in st["rows"]
    ]
    n = len(st["group_titles"])
    r = report.Report(
        title="Ведомость стоимости имущества",
        subtitle=f"на {at:%d.%m.%Y}",
        organization=ctx.org(),
        sections=[
            report.Section(
                "Стоимость",
                [
                    *st["group_titles"],
                    "Единиц",
                    "Позиций остатков",
                    "Первоначальная, ₽",
                    "Остаточная, ₽",
                ],
                rows,
                total=[
                    "Итого",
                    *[""] * (n - 1),
                    st["total"]["units"],
                    "",
                    st["total"]["initial"],
                    st["total"]["value"],
                ],
                numeric={n, n + 1, n + 2, n + 3},
            )
        ],
    )
    return report.pdf(r), f"Стоимость на {at:%d.%m.%Y}.pdf"


def _room(ctx: Ctx) -> tuple[bytes, str]:
    place = ctx.get("place")
    if not place:
        raise AppError("Выберите место.", field="place")
    title = inventory.place_title(ctx.session, ctx.actor, place)
    units = inventory.registry_rows(ctx.session, ctx.actor, place=place)
    stock = inventory.balance_rows(ctx.session, ctx.actor, place=place)
    r = report.Report(
        title=f"Ведомость помещения: {title}",
        subtitle=f"на {date.today():%d.%m.%Y}",
        organization=ctx.org(),
        landscape=False,
        sections=[
            report.Section(
                "Инвентарные единицы",
                ["№", "Наименование", "Инв. №", "Состояние", "Ответственный"],
                [
                    [
                        i + 1,
                        u["title"],
                        u["number"],
                        u.get("state_title", u["state"]),
                        u.get("responsible", ""),
                    ]
                    for i, u in enumerate(units)
                ],
            ),
            report.Section(
                "Остатки",
                ["Наименование", "Ед.", "Количество"],
                [[s["type_name"], s["unit"], s["qty"]] for s in stock],
                numeric={2},
            ),
        ],
        signatures=["Сдал", "Принял", "Материально ответственное лицо"],
    )
    return report.pdf(r), f"Ведомость — {title}.pdf"


def _count(ctx: Ctx) -> tuple[bytes, str]:
    return inventory.count_pdf(
        ctx.session,
        ctx.actor,
        ctx.need_uuid("count_id", "инвентаризацию"),
        ctx.get("what") or "statement",
    )


def _floors(ctx: Ctx) -> list[Any]:
    floor_id = ctx.id("floor_id")
    if floor_id:
        return [building.get_floor(ctx.session, ctx.actor, floor_id)]
    building_id = ctx.need_uuid("building_id", "здание или этаж")
    building.get_building(ctx.session, ctx.actor, building_id)
    return building.floors(ctx.session, building_id)


def _mismatch(ctx: Ctx) -> tuple[bytes, str]:
    unplaced, qty = [], []
    for f in _floors(ctx):
        view = link.floor_view(ctx.session, ctx.actor, f.id)
        units = {u["id"]: u for u in view["units"]}
        for uid in view["unplaced"]:
            u = units[uid]
            unplaced.append([f.name, u["room_title"], u["title"], u["number"]])
        for m in view["mismatch"]:
            qty.append(
                [f.name, m["room_title"], m["type_name"], m["on_plan"], m["in_stock"], m["unit"]]
            )
    r = report.Report(
        title="Расхождения плана и учёта",
        subtitle=f"на {date.today():%d.%m.%Y}",
        organization=ctx.org(),
        sections=[
            report.Section(
                "Числится, но не стоит на плане", ["Этаж", "Помещение", "Что", "Инв. №"], unplaced
            ),
            report.Section(
                "Количественный учёт: на плане и по учёту",
                ["Этаж", "Помещение", "Тип", "На плане", "По учёту", "Ед."],
                qty,
                numeric={3, 4},
            ),
        ],
    )
    return _out(ctx, r, "Расхождения плана и учёта")


def _project(ctx: Ctx) -> tuple[bytes, str]:
    pid = ctx.need_uuid("project_id", "проект")
    if ctx.fmt == PDF:
        return projects.export_pdf(ctx.session, ctx.actor, pid)
    return projects.export_xlsx(ctx.session, ctx.actor, pid)


def _calc_table(ctx: Ctx, key: str, title: str) -> tuple[bytes, str]:
    sections = []
    for f in _floors(ctx):
        result = calc.run(ctx.session, ctx.actor, key, f.id, None, {})
        t = result["table"]
        if not t:
            continue
        sections.append(report.Section(f"{f.name}: {t['title']}", t["columns"], t["rows"]))
        if result["missing"]:
            sections.append(
                report.Section(
                    f"{f.name}: не хватает данных",
                    ["Что"],
                    [[m["text"]] for m in result["missing"]],
                )
            )
    r = report.Report(
        title=title,
        subtitle=f"на {date.today():%d.%m.%Y}",
        organization=ctx.org(),
        sections=sections,
    )
    return _out(ctx, r, title)


def _plan(ctx: Ctx) -> tuple[bytes, str]:
    """План этажа с расстановкой по выбранным слоям (5.1.8): PDF листами, DXF по слоям."""
    floor_id = ctx.need_uuid("floor_id", "этаж")
    tree_layers = {str(k): v for k, v in catalog.layer_names(ctx.session).items()}
    chosen = {x for x in ctx.get("layers").split(",") if x} or set(tree_layers)
    items = planning.floor_items_raw(ctx.session, floor_id)
    types = catalog.types_by_id(ctx.session, [i.type_id for i in items])
    colors = catalog.layer_colors(ctx.session)
    overlays = []
    for i in items:
        t = types[i.type_id]
        if i.parent_id or i.x is None or str(t.layer_id) not in chosen:
            continue
        w, d = t.width or 500, t.depth or 500
        a = math.radians(i.angle or 0)
        ca, sa = math.cos(a), math.sin(a)
        pts = [
            [i.x + dx * ca - dy * sa, i.y + dx * sa + dy * ca]  # type: ignore[operator]
            for dx, dy in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))
        ]
        color = colors.get(t.layer_id, "#607D8B")
        overlays.append(
            {
                "points": pts,
                "fill": color,
                "stroke": color,
                "opacity": 0.3,
                "layer": tree_layers.get(str(t.layer_id), "Предметы"),
            }
        )
    return building.export_floor(ctx.session, ctx.actor, floor_id, ctx.fmt, overlays=overlays)


def _labels(ctx: Ctx) -> tuple[bytes, str]:
    place = ctx.get("place")
    if not place:
        raise AppError("Выберите место.", field="place")
    data = inventory.place_labels_pdf(ctx.session, ctx.actor, place, ctx.base_url)
    return data, f"Метки — {inventory.place_title(ctx.session, ctx.actor, place)}.pdf"


def _document(ctx: Ctx) -> tuple[bytes, str]:
    return inventory.document_pdf(ctx.session, ctx.actor, ctx.need_uuid("document_id", "документ"))


STATE_CHOICES = [
    ("", "любое"),
    ("in_use", "в работе"),
    ("broken", "неисправна"),
    ("repair", "в ремонте"),
    ("storage", "на хранении"),
    ("not_found", "не найдена"),
    ("written_off", "списана"),
]

DEFINITIONS: list[Definition] = [
    Definition(
        "registry",
        "Реестр инвентарных единиц",
        "Любая выборка со всеми характеристиками.",
        [XLSX],
        [
            Param("building_id", "Здание", "building", False),
            Param("place", "Место", "place", False),
            Param("state", "Состояние", "choice", False, STATE_CHOICES),
        ],
        _registry,
        "С17",
    ),
    Definition(
        "balances",
        "Остатки по местам хранения на дату",
        "Количество, средняя цена, сумма.",
        [XLSX, PDF],
        [
            Param("at", "На дату", "date", False),
            Param("building_id", "Здание", "building", False),
            Param("place", "Место", "place", False),
        ],
        _balances,
        "С11, С16",
    ),
    Definition(
        "movement",
        "Движение за период",
        "Строки проведённых документов: что, откуда, куда.",
        [XLSX],
        [
            Param("since", "С", "date"),
            Param("until", "По", "date", False),
            Param("building_id", "Здание", "building", False),
        ],
        _movement,
    ),
    Definition(
        "cost",
        "Ведомость стоимости на дату",
        "Первоначальная и остаточная стоимость с разбивкой.",
        [XLSX, PDF],
        [
            Param("at", "На дату", "date", False),
            Param("building_id", "Здание", "building", False),
            Param("group_by", "Разбивка", "choice", False, GROUPS, multiple=True),
        ],
        _cost,
        "С19",
    ),
    Definition(
        "room",
        "Ведомость помещения",
        "Единицы и остатки места, место для подписей.",
        [PDF],
        [Param("place", "Место", "place")],
        _room,
    ),
    Definition(
        "count",
        "Инвентаризационная ведомость и акт расхождений",
        "По ведомости инвентаризации.",
        [PDF],
        [
            Param("count_id", "Инвентаризация", "count"),
            Param(
                "what",
                "Что",
                "choice",
                False,
                [("statement", "ведомость"), ("act", "акт расхождений")],
            ),
        ],
        _count,
        "С18",
    ),
    Definition(
        "mismatch",
        "Расхождения плана и учёта",
        "Неразмещённые и количественный учёт: на плане и по учёту.",
        [XLSX],
        [Param("building_id", "Здание", "building"), Param("floor_id", "Этаж", "floor", False)],
        _mismatch,
    ),
    Definition(
        "project",
        "Спецификация и смета проекта",
        "Нужно, есть на складе, купить, сумма.",
        [XLSX, PDF],
        [Param("project_id", "Проект", "project")],
        _project,
        "С9",
    ),
    Definition(
        "cameras",
        "Камеры: параметры и дальности уровней",
        "Таблица камер по этажам.",
        [XLSX, PDF],
        [Param("building_id", "Здание", "building"), Param("floor_id", "Этаж", "floor", False)],
        lambda c: _calc_table(c, "camera", "Камеры — параметры и дальности уровней"),
        "С7",
    ),
    Definition(
        "light",
        "Освещённость помещений",
        "Норма, средняя и минимальная освещённость.",
        [XLSX, PDF],
        [Param("building_id", "Здание", "building"), Param("floor_id", "Этаж", "floor", False)],
        lambda c: _calc_table(c, "light", "Освещённость помещений"),
        "С8",
    ),
    Definition(
        "plan",
        "План этажа с расстановкой по слоям",
        "Листами в масштабе или DXF по слоям.",
        [PDF, DXF],
        [
            Param("floor_id", "Этаж", "floor"),
            Param("layers", "Слои", "layers", False, multiple=True),
        ],
        _plan,
    ),
    Definition(
        "labels",
        "QR-метки места",
        "Метки вещей места и метка на дверь помещения.",
        [PDF],
        [Param("place", "Место", "place")],
        _labels,
        "С11",
    ),
    Definition(
        "document",
        "Печатная форма документа",
        "Документ учёта с подписями.",
        [PDF],
        [Param("document_id", "Документ", "document")],
        _document,
    ),
]


def definitions(actor: Actor) -> list[dict[str, Any]]:
    if not actor.is_admin:
        raise Forbidden()
    return [
        {
            "key": d.key,
            "title": d.title,
            "about": d.about,
            "formats": d.formats,
            "scenarios": d.scenarios,
            "params": [p.__dict__ for p in d.params],
        }
        for d in DEFINITIONS
    ]


def build(
    session: Session, actor: Actor, key: str, fmt: str, params: dict[str, str], base_url: str
) -> tuple[bytes, str]:
    if not actor.is_admin:
        raise Forbidden()
    d = next((x for x in DEFINITIONS if x.key == key), None)
    if d is None:
        raise NotFound("Такого отчёта нет.")
    if fmt not in d.formats:
        raise AppError("Этот отчёт так не выгружается.")
    return d.build(Ctx(session, actor, params, fmt, base_url))
