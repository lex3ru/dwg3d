"""Стенд объёмов (ТЗ 8.1, 10.3): 20 зданий, около 10 000 помещений, 200 000 предметов на
планах (на одном этаже — 2 000), 50 000 инвентарных единиц, 5 000 позиций остатков, 20 000
документов за год (один — на 1 000 строк), 100 учётных записей. Создаётся командой
`python -m app sample volume` на отдельной базе — так же, как это сделал бы администратор:
через те же функции модулей, с проверкой планов, проведением документов и журналом.

Этажи — планировка «Поликлиники» (23 помещения на этаже); здания — по 21 этажу, первое — 30
этажей. scale < 1 уменьшает всё пропорционально (для пробы)."""

import logging
import math
import random
import time
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.db import transaction
from app.modules.access import api as access
from app.modules.building import api as building
from app.modules.building.plan import Plan
from app.modules.catalog import api as catalog
from app.modules.inventory import documents, places
from app.modules.planning import api as planning
from app.samples.polyclinic import CORRIDOR, DEPTH, FLOORS, LENGTH, NORTH, SOUTH, floor_plan

log = logging.getLogger("app.volume")

BUILDINGS = 20
FLOORS_FIRST, FLOORS_OTHER = 30, 21
ITEMS = 200_000
DENSE_FLOOR = 2_000
UNITS = 50_000
STOCK_POSITIONS = 5_000
DOCUMENTS = 20_000
USERS = 100
BIG_DOCUMENT = 1_000


def _rooms(level: int) -> list[tuple[float, float, float, float]]:
    """Прямоугольники помещений этажа (x0, y0, x1, y1), коридор — последним."""
    ys, yn = CORRIDOR
    out = [(SOUTH[i], 0.0, SOUTH[i + 1], ys) for i in range(len(SOUTH) - 1)]
    out += [(NORTH[i], yn, NORTH[i + 1], DEPTH) for i in range(len(NORTH) - 1)]
    out.append((0.0, ys, LENGTH, yn))
    return out


def _floor(level: int, number: int, purposes: dict[str, str]) -> Plan:
    plan = floor_plan(level % len(FLOORS), FLOORS[level % len(FLOORS)], purposes)
    n = 1
    for label in plan["rooms"]:
        if label["name"] == "Коридор":
            label["number"] = f"{number}К"
        else:
            label["number"] = f"{number}{n:02d}"
            n += 1
    if level % len(FLOORS) == len(FLOORS) - 1:
        plan["stairs"] = []
    return Plan.model_validate(plan)


def _items(
    count: int, level: int, kinds: list[dict[str, Any]], rnd: random.Random
) -> list[dict[str, Any]]:
    """count предметов, разложенных сеткой по помещениям этажа, с отступом от стен."""
    rects = _rooms(level)
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
    out: list[dict[str, Any]] = []
    for k, (x0, y0, x1, y1) in enumerate(rects):
        share = (
            count - len(out) if k == len(rects) - 1 else round(count * (x1 - x0) * (y1 - y0) / area)
        )
        if share <= 0:
            continue
        w, h = x1 - x0 - 1600, y1 - y0 - 1600
        cols = max(1, round(math.sqrt(share * w / h)))
        rows = math.ceil(share / cols)
        for i in range(share):
            kind = kinds[rnd.randrange(len(kinds))]
            item = {
                "type_id": str(kind["id"]),
                "x": round(x0 + 800 + w * ((i % cols) + 0.5) / cols),
                "y": round(y0 + 800 + h * ((i // cols) + 0.5) / rows),
                "angle": rnd.choice((0, 90, 180, 270)),
            }
            if kind["mount"] == "ceiling":
                item["z"] = 3000
            out.append(item)
    return out


def _post(
    session: Session, actor: Actor, kind: str, header: dict[str, Any], lines: list[dict[str, Any]]
) -> Any:
    doc = documents.create_document(session, actor, kind, header)
    doc = documents.update_document(session, actor, doc.id, doc.version, {}, lines)
    return documents.post(session, actor, doc.id, doc.version)


def create(admin_login: str, scale: float = 1.0, seed: int = 81) -> dict[str, Any]:
    rnd = random.Random(seed)
    started = time.monotonic()
    n = lambda v: max(1, round(v * scale))  # noqa: E731

    def actor() -> Actor:
        with transaction() as session:
            account = access.find(session, admin_login)
            if account is None or account.role != "admin":
                raise SystemExit(f"Администратора «{admin_login}» нет.")
            return access.actor_of(account)

    me = actor()
    with transaction() as session:
        tree = catalog.tree(session, me)
    purposes = {p["name"]: str(p["id"]) for p in tree["purposes"]}
    placeable = [
        t
        for t in tree["types"]
        if t.get("layer_id")
        and t["mount"] in ("floor", "ceiling", "wall")
        and not t.get("archived")
    ]
    pieces = [t for t in tree["types"] if t["accounting"] == "piece" and not t.get("archived")]
    quantities = [
        t for t in tree["types"] if t["accounting"] == "quantity" and not t.get("archived")
    ]
    if not placeable or not pieces or not quantities:
        raise SystemExit("В каталоге нет типов для расстановки или учёта — нужен базовый каталог.")

    # ---------------------------------------------------------------- здания и планы
    floors_total = n(FLOORS_FIRST) + n(FLOORS_OTHER) * (n(BUILDINGS) - 1)
    per_floor = (n(ITEMS) - n(DENSE_FLOOR)) / max(1, floors_total - 1)
    made: list[dict[str, Any]] = []  # здания: id, склад, помещения
    rooms_total = items_total = 0
    for b in range(n(BUILDINGS)):
        with transaction() as session:
            bld = building.create_building(
                session, me, f"Объём-{b + 1:02d}", f"Стенд объёмов, корпус {b + 1}"
            )
            wh = places.create_warehouse(
                session, me, {"name": f"Склад корпуса {b + 1}", "building_id": str(bld.id)}
            )
            info = {"id": bld.id, "warehouse": f"w:{wh.id}", "rooms": []}
        for level in range(n(FLOORS_FIRST) if b == 0 else n(FLOORS_OTHER)):
            with transaction() as session:
                floor = building.add_floor(session, me, info["id"], f"{level + 1} этаж")
                saved = building.save_plan(
                    session,
                    me,
                    floor.id,
                    _floor(level, level + 1, purposes),
                    floor.plan_version,
                    confirm=True,
                )
                rooms = [r["id"] for r in saved["rooms"]]
                info["rooms"] += rooms
                rooms_total += len(rooms)
                count = n(DENSE_FLOOR) if (b, level) == (0, 0) else round(per_floor)
                planning.apply_changes(
                    session,
                    me,
                    floor.id,
                    planning.Changes(create=_items(count, level, placeable, rnd)),
                )
                items_total += count
        made.append(info)
        log.info(
            "здание %d из %d: помещений %d, предметов %d (%.0f с)",
            b + 1,
            n(BUILDINGS),
            rooms_total,
            items_total,
            time.monotonic() - started,
        )

    # ---------------------------------------------------------------- учёт: год документов
    today = date.today()
    first = today - timedelta(days=364)
    docs = 0
    per_building_units = n(UNITS) // len(made)
    # приходы на склады (по 100 единиц), один — на 1 000 строк
    for k, info in enumerate(made):
        info["stock"] = []
        left = per_building_units
        day = first + timedelta(days=k % 20)
        with transaction() as session:
            while left > 0:
                size = min(left, BIG_DOCUMENT if (k == 0 and docs == 0 and scale >= 1) else 100)
                lines = (
                    [
                        {
                            "type_id": str(rnd.choice(pieces)["id"]),
                            "qty": 1,
                            "price": rnd.randrange(1500, 250_000, 100),
                            "commissioned_on": str(day),
                        }
                        for _ in range(size)
                    ]
                    if size == BIG_DOCUMENT
                    else [
                        {
                            "type_id": str(t["id"]),
                            "qty": size // 5 + (1 if i < size % 5 else 0),
                            "price": rnd.randrange(1500, 250_000, 100),
                            "commissioned_on": str(day),
                        }
                        for i, t in enumerate(rnd.sample(pieces, 5))
                        if size // 5 + (1 if i < size % 5 else 0)
                    ]
                )
                doc = _post(
                    session, me, "receipt", {"to_place": info["warehouse"], "date": str(day)}, lines
                )
                info["stock"] += [
                    u for line in documents.lines_of(session, doc) for u in line.created_units
                ]
                left -= size
                docs += 1
    log.info("приходы: документов %d (%.0f с)", docs, time.monotonic() - started)

    # остатки: все количественные типы по помещениям — до 5 000 позиций
    stock_places = math.ceil(n(STOCK_POSITIONS) / len(quantities))
    with transaction() as session:
        for i in range(stock_places):
            info = made[i % len(made)]
            room = info["rooms"][(i // len(made)) % len(info["rooms"])]
            _post(
                session,
                me,
                "receipt",
                {"to_place": f"r:{room}", "date": str(first + timedelta(days=21))},
                [
                    {
                        "type_id": str(t["id"]),
                        "qty": rnd.randrange(5, 200),
                        "price": rnd.randrange(20, 3000),
                    }
                    for t in quantities
                ],
            )
            docs += 1
    log.info(
        "остатки: позиций %d (%.0f с)", stock_places * len(quantities), time.monotonic() - started
    )

    # выдача со складов по помещениям (по 5 единиц), затем перемещения между помещениями —
    # до 20 000 документов, в порядке дат до сегодня
    left_docs = n(DOCUMENTS) - docs
    issues = sum(math.ceil(len(i["stock"]) / 5) for i in made)
    moves = max(0, left_docs - issues)
    plan: list[tuple[str, dict[str, Any], int]] = []  # вид, здание, номер
    for info in made:
        info["where"] = {}
        plan += [("issue", info, j) for j in range(math.ceil(len(info["stock"]) / 5))]
    rnd.shuffle(plan)
    plan += [("move", made[j % len(made)], j) for j in range(moves)]
    span = (today - (first + timedelta(days=22))).days
    for chunk in range(0, len(plan), 500):
        with transaction() as session:
            for j, (kind, info, k) in enumerate(plan[chunk : chunk + 500], start=chunk):
                day = first + timedelta(days=22 + span * j // len(plan))
                if kind == "issue":
                    units = info["stock"][k * 5 : (k + 1) * 5]
                    room = rnd.choice(info["rooms"])
                    _post(
                        session,
                        me,
                        "transfer",
                        {
                            "from_place": info["warehouse"],
                            "to_place": f"r:{room}",
                            "date": str(day),
                        },
                        [{"unit_id": u} for u in units],
                    )
                    for u in units:
                        info["where"][u] = room
                else:
                    placed = list(info["where"].items())
                    if not placed:
                        continue
                    unit, src = placed[rnd.randrange(len(placed))]
                    dst = src
                    while dst == src:
                        dst = rnd.choice(info["rooms"])
                    _post(
                        session,
                        me,
                        "transfer",
                        {"from_place": f"r:{src}", "to_place": f"r:{dst}", "date": str(day)},
                        [{"unit_id": unit}],
                    )
                    info["where"][unit] = dst
                docs += 1
        log.info("документов %d из %d (%.0f с)", docs, n(DOCUMENTS), time.monotonic() - started)

    # ---------------------------------------------------------------- учётные записи
    with transaction() as session:
        for u in range(n(USERS) - 1):
            access.create(
                session,
                me,
                login_name=f"volume{u + 1:03d}",
                full_name=f"Сотрудник {u + 1:03d}",
                role="viewer",
                building_ids=[rnd.choice(made)["id"]],
                password=f"Volume-pass-{uuid.uuid4().hex[:8]}",
            )
    result = {
        "buildings": len(made),
        "floors": floors_total,
        "rooms": rooms_total,
        "items": items_total,
        "units": sum(len(i["stock"]) for i in made),
        "stock_positions": stock_places * len(quantities),
        "documents": docs,
        "users": n(USERS),
        "seconds": round(time.monotonic() - started),
    }
    log.info("готово: %s", result)
    return result
