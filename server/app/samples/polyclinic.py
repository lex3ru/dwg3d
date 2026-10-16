"""Тестовое здание «Поликлиника» (ТЗ 7.2, 11.1 п. 6 — по придуманной планировке): три
этажа 42 × 16,2 м, коридор посередине, кабинеты по обе стороны, лестничная клетка и лифт
в восточном конце. Создаётся командой `python -m app sample polyclinic` от имени
администратора — как если бы он нарисовал его в редакторе (С2)."""

from typing import Any

from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.modules.building import api
from app.modules.building.plan import Plan

LENGTH, DEPTH = 42000.0, 16200.0
OUTER, BEARING, PARTITION = 380.0, 250.0, 120.0
CORRIDOR = (6600.0, 9000.0)  # южная и северная стены коридора
SOUTH = [0.0, 6000, 9600, 13200, 16800, 20400, 24000, 27600, 31200, 34800, 37200, LENGTH]
NORTH = [0.0, 4800, 8400, 12000, 15600, 19200, 22800, 26400, 30000, 33600, 37200, LENGTH]
HEIGHT = 3300.0

FLOORS: list[dict[str, Any]] = [
    {"name": "1 этаж", "south": ["Холл", "Гардероб", "Кабинет терапевта", "Процедурная", "Склад",
                                 "Кабинет врача", "Прививочный кабинет", "Санузел", "Санузел",
                                 "Кладовая", "Лифтовый холл"],
     "north": ["Регистратура", "Кабинет заведующего", "Аптечный пункт", "Смотровой кабинет",
               "Кабинет педиатра", "Лаборатория", "Кабинет забора крови", "Кабинет ЭКГ",
               "Комната персонала", "Серверная", "Лестничная клетка"]},
    {"name": "2 этаж", "south": ["Кабинет терапевта", "Кабинет терапевта", "Кабинет кардиолога",
                                 "Кабинет невролога", "Процедурный кабинет", "Перевязочная",
                                 "Кабинет хирурга", "Санузел", "Санузел", "Кладовая",
                                 "Лифтовый холл"],
     "north": ["Ожидание", "Кабинет офтальмолога", "Кабинет оториноларинголога",
               "Кабинет эндокринолога", "Кабинет врача", "Кабинет врача", "Кабинет УЗИ",
               "Кабинет функциональной диагностики", "Ординаторская", "Склад этажа",
               "Лестничная клетка"]},
    {"name": "3 этаж", "south": ["Конференц-зал", "Приёмная", "Кабинет главного врача",
                                 "Бухгалтерия", "Отдел кадров", "Кабинет заместителя",
                                 "Архив", "Санузел", "Санузел", "Кладовая", "Лифтовый холл"],
     "north": ["Ожидание", "Кабинет стоматолога", "Кабинет стоматолога", "Стерилизационная",
               "Кабинет физиотерапии", "Кабинет массажа", "Кабинет ЛФК", "Комната отдыха",
               "Методический кабинет", "Серверная", "Лестничная клетка"]},
]


def floor_plan(level: int, rooms: dict[str, Any]) -> dict[str, Any]:
    nodes: dict[str, list[float]] = {}
    walls: list[dict[str, Any]] = []
    openings: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []

    def node(x: float, y: float) -> str:
        key = f"n{int(x)}_{int(y)}"
        nodes[key] = [x, y]
        return key

    def wall(xa: float, ya: float, xb: float, yb: float, thickness: float, kind: str) -> str:
        wid = f"w{len(walls) + 1}"
        walls.append({"id": wid, "a": node(xa, ya), "b": node(xb, yb), "thickness": thickness,
                      "kind": kind})
        return wid

    def opening(wall_id: str, kind: str, at: float, width: float, **extra: Any) -> None:
        defaults = {"door": (2100, 0), "window": (1500, 850), "glazing": (2700, 0),
                    "passage": (2100, 0)}
        height, sill = defaults[kind]
        openings.append({"id": f"o{len(openings) + 1}", "wall": wall_id, "kind": kind, "at": at,
                         "width": width, "height": height, "sill": sill, **extra})

    # узлы на наружных и коридорных стенах — у каждой перегородки
    south_xs = SOUTH
    north_xs = NORTH
    ys, yn = CORRIDOR
    # южная наружная стена: по комнатам, с окнами
    for i in range(len(south_xs) - 1):
        x0, x1 = south_xs[i], south_xs[i + 1]
        w = wall(x0, 0, x1, 0, OUTER, "bearing")
        if level == 0 and i == 0:
            opening(w, "glazing", (x1 - x0) / 2, 3000)
        elif rooms["south"][i] != "Лифтовый холл":
            opening(w, "window", (x1 - x0) / 2, 1500 if x1 - x0 < 5000 else 2400)
    for i in range(len(north_xs) - 1):
        x0, x1 = north_xs[i], north_xs[i + 1]
        w = wall(x1, DEPTH, x0, DEPTH, OUTER, "bearing")
        opening(w, "window", (x1 - x0) / 2, 1500)
    # торцы: запад и восток, по три участка (юг, коридор, север)
    for x in (0.0, LENGTH):
        for y0, y1 in ((0, ys), (ys, yn), (yn, DEPTH)):
            w = wall(x, y0, x, y1, OUTER, "bearing")
            if y0 == ys:
                if x == 0:
                    opening(w, "door" if level == 0 else "window", (y1 - y0) / 2, 1200,
                            side="right")
                else:
                    opening(w, "window", (y1 - y0) / 2, 1200)
    # стены коридора — по участкам между перегородками, с дверями в кабинеты
    for i in range(len(south_xs) - 1):
        x0, x1 = south_xs[i], south_xs[i + 1]
        w = wall(x0, ys, x1, ys, BEARING, "bearing")
        width = 1800 if rooms["south"][i] in ("Холл", "Лифтовый холл") else 900
        kind = "passage" if width > 1000 else "door"
        opening(w, kind, (x1 - x0) / 2, width, hinge="start", side="right")
    for i in range(len(north_xs) - 1):
        x0, x1 = north_xs[i], north_xs[i + 1]
        w = wall(x0, yn, x1, yn, BEARING, "bearing")
        width = 1400 if rooms["north"][i] == "Лестничная клетка" else 900
        opening(w, "door", (x1 - x0) / 2, width, hinge="end", side="left")
    # перегородки между кабинетами
    for x in south_xs[1:-1]:
        wall(x, 0, x, ys, PARTITION, "partition")
    for x in north_xs[1:-1]:
        wall(x, yn, x, DEPTH, PARTITION, "partition")

    first = (level + 1) * 100
    number = first + 1
    def label_x(x0: float, x1: float, name: str) -> float:
        # в лифтовом холле и на лестнице подпись — в стороне от шахты и марша
        return x0 + 1200 if name in ("Лифтовый холл", "Лестничная клетка") else (x0 + x1) / 2

    for i, name in enumerate(rooms["south"]):
        labels.append({"id": f"new-s{i}", "x": label_x(south_xs[i], south_xs[i + 1], name),
                       "y": ys / 2 + 700, "number": str(number), "name": name})
        number += 1
    for i, name in enumerate(rooms["north"]):
        labels.append({"id": f"new-n{i}", "x": label_x(north_xs[i], north_xs[i + 1], name),
                       "y": (yn + DEPTH) / 2 + 700, "number": str(number), "name": name})
        number += 1
    labels.append({"id": "new-c", "x": 18000, "y": (ys + yn) / 2, "number": f"{first // 100}К",
                   "name": "Коридор"})

    stairs = []
    if level < len(FLOORS) - 1:
        # марш с этого этажа на следующий — в лестничной клетке, вдоль восточной стены
        stairs.append({"id": "s1", "x": 40400, "y": yn + 600, "width": 1400, "length": 5700,
                       "angle": 90, "steps": 19})
    # колонны в холле (на втором и третьем — в ожидании и конференц-зале над ним)
    columns = [{"id": "c1", "x": 3000, "y": 3300, "w": 400, "d": 400},
               {"id": "c2", "x": 2400, "y": 12600, "w": 400, "d": 400, "round": True}]
    plan = {"nodes": nodes, "walls": walls, "openings": openings, "columns": columns,
            "stairs": stairs, "rooms": labels}
    return Plan.model_validate(plan).model_dump()


def create(session: Session, actor: Actor, name: str = "Поликлиника") -> dict[str, Any]:
    building = api.create_building(session, actor, name, "ул. Садовая, 12")
    floor_ids = []
    for level, rooms in enumerate(FLOORS):
        floor = api.add_floor(session, actor, building.id, rooms["name"],
                              elevation=level * HEIGHT, height=HEIGHT)
        plan = Plan.model_validate(floor_plan(level, rooms))
        api.save_plan(session, actor, floor.id, plan, floor.plan_version, confirm=True)
        floor_ids.append(floor.id)
    api.create_lift(session, actor, building.id, {
        "name": "Л1", "x": 40800, "y": 3600, "w": 2000, "d": 2300, "door_side": 0,
        "floor_ids": floor_ids})
    return {"building_id": building.id, "floor_ids": floor_ids}
