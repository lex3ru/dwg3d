"""Расчёты на плане как модули (5.3.7).

Расчёт объявляет, какие характеристики каталога ему нужны (5.2.5), свои настройки,
параметры предмета (наклон, угол) и то, что рисует, — простыми фигурами: многоугольники,
клетки с раскраской, подписи, линии в 3D. Редактор рисует фигуры, не зная, какой это расчёт:
новый расчёт добавляется без изменения редактора.

Считает сервер. Редактор присылает расстановку как есть на экране (и пока предмет тащат),
поэтому зона обзора пересчитывается на ходу (8.2: 0,2 с).
"""

import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, NotFound
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.planning import api as planning
from app.modules.system import api as system

# ---------------------------------------------------------------- описание расчёта


@dataclass
class Param:
    """Параметр предмета для расчёта (хранится у предмета как «модуль.ключ»)."""

    key: str
    title: str
    unit: str = ""
    low: float | None = None
    high: float | None = None
    hint: str = ""


@dataclass
class Option:
    """Выбор при расчёте (уровень для «непросматриваемых мест»)."""

    key: str
    title: str
    choices: list[tuple[str, str]]
    default: str


@dataclass
class Calculation:
    key: str
    title: str
    about: str
    needs: list[str]  # характеристики каталога, без которых предмет не считается
    params: list[Param]
    options: list[Option]
    compute: Callable[["Ctx", dict[str, str]], "Result"]
    settings: dict[str, system.SettingDef] = field(default_factory=dict)


_calcs: dict[str, Calculation] = {}


def register(calc: Calculation) -> None:
    _calcs[calc.key] = calc
    for key, definition in calc.settings.items():
        system.register(key, definition)


# ---------------------------------------------------------------- результат


@dataclass
class Result:
    draw: list[dict[str, Any]] = field(default_factory=list)  # 2D: polygon, cells, label
    draw3d: list[dict[str, Any]] = field(default_factory=list)  # 3D: lines
    summary: list[str] = field(default_factory=list)
    legend: list[dict[str, Any]] = field(default_factory=list)
    table: dict[str, Any] | None = None
    issues: dict[str, Any] | None = None  # «ниже нормы», «не просматривается»: с переходом
    missing: list[dict[str, Any]] = field(default_factory=list)  # нет нужных характеристик

    def view(self, took: float) -> dict[str, Any]:
        return {
            "draw": self.draw,
            "draw3d": self.draw3d,
            "summary": self.summary,
            "legend": self.legend,
            "table": self.table,
            "issues": self.issues,
            "missing": self.missing,
            "took_ms": round(took * 1000),
        }


def rings(geom: BaseGeometry, digits: int = 0) -> list[list[list[list[float]]]]:
    """Многоугольники фигуры как кольца (внешнее и дыры) — для рисования."""
    polys = [geom] if isinstance(geom, Polygon) else list(getattr(geom, "geoms", []))
    out = []
    for p in polys:
        if not isinstance(p, Polygon) or p.is_empty:
            continue
        out.append(
            [
                np.round(np.asarray(ring.coords)[:-1], digits).tolist()
                for ring in [p.exterior, *p.interiors]
            ]
        )
    return out


# ---------------------------------------------------------------- данные этажа


@dataclass
class Thing:
    """Предмет на плане с тем, что нужно расчёту."""

    id: str
    type: Any
    model: Any
    x: float
    y: float
    z: float
    angle: float
    room_id: uuid.UUID | None
    params: dict[str, Any]
    values: dict[str, Any]
    label: str
    note: str = ""  # «модель не выбрана — взята …»

    @property
    def name(self) -> str:
        model = f" {self.model.manufacturer} {self.model.name}" if self.model else ""
        return f"{self.type.name}{model}{f' «{self.label}»' if self.label else ''}"

    def number(self, key: str) -> float | None:
        v = self.values.get(key)
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def param(self, calc: str, key: str, default: float) -> float:
        v = self.params.get(f"{calc}.{key}")
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else default


@dataclass
class Ctx:
    session: Session
    actor: Actor
    floor: Any
    rooms: list[Any]  # building.Room: id, number, name, purpose_id, outline, x, y
    obstacles: list[BaseGeometry]
    things: list[Thing]
    setting: Callable[[str], Any]


def _num(v: Any, low: float, high: float, what: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise AppError(f"{what}: нужно число.") from None
    if not math.isfinite(f) or f < low or f > high:
        raise AppError(f"{what}: вне допустимых пределов.")
    return f


def _scalars(value: Any) -> dict[str, Any]:
    """Параметры из присланной расстановки: только простые значения."""
    if not isinstance(value, dict):
        return {}
    return {
        str(k)[:40]: v
        for k, v in list(value.items())[:30]
        if v is None or isinstance(v, bool | int | float) or (isinstance(v, str) and len(v) <= 100)
    }


def _things(
    session: Session,
    floor: Any,
    calc: Calculation,
    sent: list[dict[str, Any]] | None,
) -> tuple[list[Thing], list[dict[str, Any]]]:
    """Предметы этажа тех типов, что нужны расчёту: из присланной расстановки (как на экране)
    или сохранённой. И те, у кого нет нужных характеристик."""
    wanted = {t.id: t for t in catalog.types_with(session, calc.needs)}
    rows: list[dict[str, Any]] = []
    if sent is None:
        for i in planning.floor_items_raw(session, floor.id):
            if i.type_id in wanted and i.parent_id is None and i.x is not None:
                rows.append(
                    {
                        "id": str(i.id),
                        "type_id": i.type_id,
                        "model_id": i.model_id,
                        "x": i.x,
                        "y": i.y,
                        "z": i.z,
                        "angle": i.angle,
                        "params": i.params or {},
                        "label": i.label,
                        "room_id": i.room_id,
                    }
                )
    else:
        rooms = planning.Rooms(session, floor.id)
        for v in sent[:3000]:
            try:
                type_id = uuid.UUID(str(v.get("type_id")))
            except ValueError:
                continue
            if type_id not in wanted or v.get("parent_id") or v.get("x") is None:
                continue
            x = _num(v.get("x"), -1e8, 1e8, "x")
            y = _num(v.get("y"), -1e8, 1e8, "y")
            model = v.get("model_id")
            rows.append(
                {
                    "id": str(v.get("id", "")),
                    "type_id": type_id,
                    "model_id": uuid.UUID(str(model)) if model else None,
                    "x": x,
                    "y": y,
                    "z": _num(v.get("z", 0), -1e5, 1e5, "z"),
                    "angle": _num(v.get("angle", 0), -1e6, 1e6, "angle"),
                    "params": _scalars(v.get("params")),
                    "label": str(v.get("label") or "")[:100],
                    "room_id": rooms.at(x, y),
                }
            )
    models = catalog.models_by_id(session, [r["model_id"] for r in rows if r["model_id"]])
    first: dict[uuid.UUID, Any] = {}
    values: dict[tuple[uuid.UUID, uuid.UUID | None], dict[str, Any]] = {}
    out, missing = [], []
    for r in rows:
        t = wanted[r["type_id"]]
        model = models.get(r["model_id"]) if r["model_id"] else None
        note = ""
        if model is None:
            # модель не выбрана — берём первую из каталога, если она есть, и говорим об этом
            if t.id not in first:
                live = sorted(
                    (m for m in catalog.models_of(session, t.id) if m.archived_at is None),
                    key=lambda m: (m.manufacturer, m.name),
                )
                # первая модель, у которой нужное заполнено, иначе просто первая
                full = [
                    m
                    for m in live
                    if all(
                        catalog.named_values(session, t, m.id).get(n) not in (None, "")
                        for n in calc.needs
                    )
                ]
                first[t.id] = (full or live or [None])[0]
            model = first[t.id]
            if model is not None:
                note = f"модель не выбрана — взята {model.manufacturer} {model.name}"
        key = (t.id, model.id if model else None)
        if key not in values:
            values[key] = catalog.named_values(session, t, model.id if model else None)
        thing = Thing(
            id=r["id"],
            type=t,
            model=model,
            x=r["x"],
            y=r["y"],
            z=r["z"],
            angle=r["angle"],
            room_id=r["room_id"],
            params=r["params"],
            values=values[key],
            label=r["label"],
            note=note,
        )
        lacking = [n for n in calc.needs if values[key].get(n) in (None, "")]
        if lacking:
            missing.append(
                {
                    "item_id": thing.id,
                    "x": thing.x,
                    "y": thing.y,
                    "text": f"{thing.name}: не заполнено — {', '.join(lacking)}"
                    + ("" if model else " (у типа нет моделей)"),
                }
            )
            continue
        out.append(thing)
    return out, missing


# ---------------------------------------------------------------- для маршрутов


def calculations(session: Session) -> list[dict[str, Any]]:
    """Расчёты, которые есть, — для списка в редакторе: что нужно, какие параметры у каких
    типов."""
    out = []
    for c in _calcs.values():
        out.append(
            {
                "key": c.key,
                "title": c.title,
                "about": c.about,
                "needs": c.needs,
                "type_ids": [t.id for t in catalog.types_with(session, c.needs)],
                "params": [p.__dict__ for p in c.params],
                "options": [
                    {"key": o.key, "title": o.title, "choices": o.choices, "default": o.default}
                    for o in c.options
                ],
            }
        )
    return out


# препятствия этажа — пока план не меняли (пересчёт на ходу, 8.2)
_obstacles: dict[tuple[uuid.UUID, int], list[BaseGeometry]] = {}


def _floor_obstacles(session: Session, actor: Actor, floor: Any) -> list[BaseGeometry]:
    key = (floor.id, floor.plan_version)
    if key not in _obstacles:
        if len(_obstacles) > 32:
            _obstacles.clear()
        _obstacles[key] = building.floor_obstacles(session, actor, floor.id)
    return _obstacles[key]


def run(
    session: Session,
    actor: Actor,
    key: str,
    floor_id: uuid.UUID,
    items: list[dict[str, Any]] | None,
    options: dict[str, str],
) -> dict[str, Any]:
    calc = _calcs.get(key)
    if calc is None:
        raise NotFound("Такого расчёта нет.")
    started = time.perf_counter()
    floor = building.get_floor(session, actor, floor_id)
    things, missing = _things(session, floor, calc, items)
    ctx = Ctx(
        session=session,
        actor=actor,
        floor=floor,
        rooms=[r for r in building.live_rooms(session, floor.id) if len(r.outline) >= 3],
        obstacles=_floor_obstacles(session, actor, floor),
        things=things,
        setting=lambda k: system.get(session, k),
    )
    chosen = {o.key: options.get(o.key, o.default) for o in calc.options}
    for o in calc.options:
        if chosen[o.key] not in {c for c, _ in o.choices} and o.key != "room":
            chosen[o.key] = o.default
    if "room" in options:
        chosen["room"] = options["room"]
    result = calc.compute(ctx, chosen)
    result.missing = missing + result.missing
    return result.view(time.perf_counter() - started)
