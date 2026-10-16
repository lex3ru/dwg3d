"""Расчёты (5.3.4, 5.3.5, 5.3.7; С7, С8): обзор камер со стенами и уровнями различимости,
«непросматриваемые места», освещённость помещений с нормами."""

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from app.core.db import transaction
from app.modules.catalog.module import seed
from tests.test_building import building_with_floor, save, two_rooms
from tests.test_planning import changes


def catalog(admin):  # type: ignore[no-untyped-def]
    with transaction() as s:
        seed(s)
    tree = admin.get("/api/catalog").json()
    types = {t["name"]: t for t in tree["types"]}
    purposes = {p["name"]: p["id"] for p in tree["purposes"]}
    return types, purposes


def model_of(admin, type_id, name):  # type: ignore[no-untyped-def]
    full = admin.get(f"/api/catalog/types/{type_id}").json()
    return next(m for m in full["models"] if name in m["name"])["id"]


def floor(admin, purposes=None):  # type: ignore[no-untyped-def]
    _, f = building_with_floor(admin)
    plan = two_rooms()
    for label, purpose in zip(plan["rooms"], purposes or [None, None], strict=True):
        label["purpose_id"] = purpose
    rooms = {r["number"]: r for r in save(admin, f["id"], plan, 1).json()["rooms"]}
    return f, rooms


def run(admin, key, floor_id, **body):  # type: ignore[no-untyped-def]
    r = admin.post(f"/api/calc/{key}/floors/{floor_id}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def zones(result, fill=None):  # type: ignore[no-untyped-def]
    shapes = []
    for d in result["draw"]:
        if d["kind"] == "polygon" and not d.get("hatch") and (fill is None or d["fill"] == fill):
            for rings in d["rings"]:
                shapes.append(Polygon(rings[0], rings[1:]))
    return unary_union(shapes)


def test_calculations_list_declares_needs_params_and_types(admin) -> None:
    types, _ = catalog(admin)
    items = {c["key"]: c for c in admin.get("/api/calc").json()["items"]}
    assert items["camera"]["title"] == "Обзор камер"
    assert types["Камера цилиндрическая"]["id"] in items["camera"]["type_ids"]
    assert types["Светильник светодиодный 600×600"]["id"] in items["light"]["type_ids"]
    assert types["Стол письменный 1200×600"]["id"] not in items["light"]["type_ids"]
    assert [p["key"] for p in items["camera"]["params"]] == ["tilt", "fov"]
    assert items["camera"]["options"][0]["key"] == "unseen"


def test_c7_camera_zone_levels_and_walls(admin) -> None:
    types, _ = catalog(admin)
    f, rooms = floor(admin)
    cam = types["Камера цилиндрическая"]["id"]
    model = model_of(admin, cam, "4 мм")
    # на стене 214 на высоте 2,8 м, смотрит вдоль кабинета к перегородке с дверью
    r = changes(
        admin,
        f["id"],
        create=[{"type_id": cam, "model_id": model, "x": 200, "y": 2000, "angle": 270, "z": 2800}],
    )
    assert r.status_code == 200, r.text
    result = run(admin, "camera", f["id"])
    fills = {d["fill"] for d in result["draw"] if d["kind"] == "polygon"}
    assert len(fills) == 4  # обнаружение, наблюдение, узнавание, идентификация
    seen = zones(result)
    identify = zones(result, "#E57373")
    assert identify.contains(Point(2500, 2000))  # лицо у перегородки различимо
    assert seen.contains(Point(4000, 3000))  # через дверь видно соседний кабинет
    assert not seen.contains(Point(5000, 1000))  # за перегородкой — нет
    assert not seen.contains(Point(500, 2000))  # прямо под камерой на высоте лица — нет
    row = result["table"]["rows"][0]
    assert row[2] == "2.8" and row[5] == "84°"
    assert float(row[6]) > 5  # идентификация — дальше 5 м
    assert result["draw3d"][0]["kind"] == "lines" and len(result["draw3d"][0]["segments"]) == 8

    # «непросматриваемые места» в 214 на уровне идентификации
    unseen = run(
        admin, "camera", f["id"], options={"unseen": "identify", "room": rooms["214"]["id"]}
    )
    assert unseen["issues"]["rows"][0]["text"].startswith("214 Кабинет:")
    assert any(d.get("hatch") for d in unseen["draw"])

    # расстановка с экрана: камеру утащили в 215 и повернули к 214 — считается она
    item = r.json()["items"][0]
    moved = run(
        admin,
        "camera",
        f["id"],
        items=[{**item, "x": 5800, "y": 2000, "angle": 90, "params": {"camera.fov": 60}}],
    )
    assert zones(moved).contains(Point(4000, 2000))
    assert not zones(moved).contains(Point(1000, 500))
    assert moved["table"]["rows"][0][5] == "84°"  # объектив с постоянным фокусом — угол модели
    # наклон вниз сильнее — ближняя граница ближе, дальняя появляется
    steep = run(admin, "camera", f["id"], items=[{**item, "params": {"camera.tilt": 60}}])
    assert zones(steep).contains(Point(800, 2000))
    assert not zones(steep).contains(Point(2800, 2000))


def test_camera_without_characteristics_is_reported(admin) -> None:
    types, _ = catalog(admin)
    f, _ = floor(admin)
    cam = types["Камера купольная"]["id"]
    bare = admin.post(
        f"/api/catalog/types/{cam}/models", json={"manufacturer": "Noname", "name": "X1"}
    ).json()
    model = next(m for m in bare["models"] if m["name"] == "X1")["id"]
    changes(admin, f["id"], create=[{"type_id": cam, "model_id": model, "x": 1500, "y": 2000}])
    result = run(admin, "camera", f["id"])
    assert result["table"]["rows"] == []
    assert "не заполнено — Разрешение по горизонтали" in result["missing"][0]["text"]


def test_c8_illuminance_by_room_against_norms(admin) -> None:
    types, purposes = catalog(admin)
    f, rooms = floor(admin, [purposes["Кабинет врача"], purposes["Коридор"]])
    lamp = types["Светильник светодиодный 600×600"]["id"]
    model = model_of(admin, lamp, "ДВО 40")
    changes(admin, f["id"], create=[{"type_id": lamp, "model_id": model, "x": 4500, "y": 2000}])
    result = run(admin, "light", f["id"])
    table = {row[0]: row for row in result["table"]["rows"]}
    assert table["214 Кабинет"][3] == "500" and table["214 Кабинет"][4] == "0"
    assert table["215 Кабинет"][2] == "0.0"  # коридор — на полу
    assert 30 < float(table["215 Кабинет"][4]) < 200  # один светильник — ниже нормы 200
    low = [x["text"] for x in result["issues"]["rows"]]
    assert any(t.startswith("214 Кабинет") and "светильников нет" in t for t in low)
    assert any(t.startswith("215 Кабинет") for t in low)
    cells = next(d for d in result["draw"] if d["kind"] == "cells" and "scale" in d)
    assert len(cells["cells"]) > 100
    hatch = next(d for d in result["draw"] if d["kind"] == "cells" and d.get("hatch"))
    assert hatch["cells"]

    # С8: светильники сеткой — коридор выходит на норму
    grid = [
        {"type_id": lamp, "model_id": model, "x": 3750 + 1500 * i, "y": 1000 + 2000 * j}
        for i in range(2)
        for j in range(2)
    ]
    changes(admin, f["id"], create=grid)
    result = run(admin, "light", f["id"])
    table = {row[0]: row for row in result["table"]["rows"]}
    assert float(table["215 Кабинет"][4]) >= 200
    assert not any(x["text"].startswith("215") for x in result["issues"]["rows"])
    # свет через стены не проходит: в 214 по-прежнему темно
    assert table["214 Кабинет"][4] == "0"
    labels = [d for d in result["draw"] if d["kind"] == "label"]
    assert any("норма 200" in d["text"] and d["tone"] == "ok" for d in labels)
