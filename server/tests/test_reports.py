"""Отчёты (5.6), главная (6.5.1), полная выгрузка (7.4)."""

import io
import zipfile
from datetime import date

from app.core import tasks
from tests.test_building import building_with_floor, save, two_rooms
from tests.test_calc import catalog
from tests.test_inventory import document, post
from tests.test_planning import changes


def setup(admin):  # type: ignore[no-untyped-def]
    types, purposes = catalog(admin)
    b, f = building_with_floor(admin)
    plan = two_rooms()
    plan["rooms"][0]["purpose_id"] = purposes["Кабинет врача"]
    rooms = {r["number"]: r["id"] for r in save(admin, f["id"], plan, 1).json()["rooms"]}
    desk = types["Стол письменный 1200×600"]["id"]
    lamp = types["Светильник светодиодный 600×600"]["id"]
    cam = types["Камера купольная"]["id"]
    changes(
        admin,
        f["id"],
        create=[
            {"type_id": desk, "x": 1500, "y": 2000},
            {"type_id": lamp, "x": 1500, "y": 2000},
            {"type_id": cam, "x": 2800, "y": 3800},
        ],
    )
    got = document(
        admin,
        "receipt",
        {"to_place": f"r:{rooms['214']}"},
        [
            {"type_id": types["Кушетка смотровая"]["id"], "qty": 2, "price": 18000},
            {"type_id": types["Перчатки смотровые нитриловые"]["id"], "qty": 10, "price": 520},
        ],
    )
    assert post(admin, got).status_code == 200
    return b, f, rooms, got, types


def test_every_report_builds(admin) -> None:
    b, f, rooms, got, types = setup(admin)
    defs = {d["key"]: d for d in admin.get("/api/reports").json()["items"]}
    assert len(defs) == 13
    count = admin.post("/api/inventory/counts", json={"places": [f"r:{rooms['214']}"]}).json()
    project = admin.post("/api/projects", json={"building_id": b["id"], "name": "Вариант"}).json()
    layers = ",".join(t["layer_id"] for t in types.values() if t["layer_id"])[:2000]
    params = {
        "registry": {"building_id": b["id"]},
        "balances": {"at": str(date.today()), "building_id": b["id"]},
        "movement": {"since": "2020-01-01", "building_id": b["id"]},
        "cost": {"at": str(date.today()), "building_id": b["id"], "group_by": "floor,layer"},
        "room": {"place": f"r:{rooms['214']}"},
        "count": {"count_id": count["id"], "what": "statement"},
        "mismatch": {"building_id": b["id"]},
        "project": {"project_id": project["id"]},
        "cameras": {"building_id": b["id"]},
        "light": {"floor_id": f["id"]},
        "plan": {"floor_id": f["id"], "layers": layers},
        "labels": {"place": f"r:{rooms['214']}"},
        "document": {"document_id": got["id"]},
    }
    magic = {"pdf": b"%PDF-", "xlsx": b"PK", "dxf": b"  0"}
    for key, d in defs.items():
        for fmt in d["formats"]:
            r = admin.get(f"/api/reports/{key}.{fmt}", params=params[key])
            assert r.status_code == 200, (key, fmt, r.text[:300])
            assert r.content.startswith(magic[fmt]), (key, fmt)
    # отчёт без обязательного — понятная ошибка
    r = admin.get("/api/reports/room.pdf")
    assert r.status_code == 400 and "место" in r.json()["error"]["message"].lower()


def test_home_counts_what_needs_attention(admin) -> None:
    b, f, rooms, got, types = setup(admin)
    units = admin.get(f"/api/inventory/documents/{got['id']}").json()["lines"][0]["created_units"]
    card = admin.get(f"/api/inventory/units/{units[0]['id']}").json()
    r = admin.patch(
        f"/api/inventory/units/{card['id']}",
        json={"version": card["version"], "values": {"state": "broken"}},
    )
    assert r.status_code == 200, r.text
    home = admin.get("/api/home", params={"building_id": b["id"]}).json()
    counts = {a["key"]: a["count"] for a in home["attention"]}
    assert counts["broken"] == 1 and counts["repair"] == 0
    assert home["cost"]["initial"] == 2 * 18000 + 10 * 520
    assert home["documents"][0]["title"].startswith("Приход")
    plan = admin.get("/api/home/plan", params={"building_id": b["id"]}).json()
    checks = {a["key"]: a for a in plan["attention"]}
    assert checks["unplaced"]["count"] == 2  # кушетки числятся, на плане их нет
    assert checks["dark"]["count"] >= 1  # 214 — кабинет врача, одного светильника мало
    assert checks["mismatch"]["count"] == 1  # светильник на плане, по учёту — нет


def test_full_export_is_an_archive_readable_without_the_system(admin) -> None:
    b, _, _, got, types = setup(admin)
    # у кушетки — своя характеристика «у каждой вещи»: она должна попасть в архив
    couch = types["Кушетка смотровая"]["id"]
    ch = admin.post(
        "/api/catalog/characteristics",
        json={"type_id": couch, "name": "Цвет обивки", "kind": "text", "level": "item"},
    ).json()
    unit_id = admin.get(f"/api/inventory/documents/{got['id']}").json()["lines"][0][
        "created_units"
    ][0]["id"]
    unit = admin.get(f"/api/inventory/units/{unit_id}").json()
    r = admin.patch(
        f"/api/inventory/units/{unit_id}",
        json={"version": unit["version"], "values": {"values": {ch["id"]: "бежевый"}}},
    )
    assert r.status_code == 200, r.text
    r = admin.post("/api/reports/exports", params={"building_id": b["id"]})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    while tasks.run_one():
        pass
    job = admin.get(f"/api/system/tasks/{job_id}").json()
    assert job["status"] == "done", job
    z = zipfile.ZipFile(io.BytesIO(admin.get(job["result"]["href"]).content))
    names = z.namelist()
    for n in (
        "README.txt",
        "Помещения.xlsx",
        "Расстановка.xlsx",
        "Имущество.xlsx",
        "Характеристики.xlsx",
        "Каталог.xlsx",
        "Остатки.xlsx",
        "Документы.xlsx",
        "История.xlsx",
    ):
        assert n in names, n
    assert b["name"] in z.read("README.txt").decode()
    # расстановка читается без системы: обычная таблица
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(z.read("Расстановка.xlsx"))).active
    assert [c.value for c in ws[3]][:3] == ["Этаж", "Помещение", "Тип"]
    assert ws.max_row == 6  # заголовок, пустая строка, шапка и три предмета
    # каталог — тот же файл, что «Выгрузить в Excel» в каталоге: загружается обратно
    assert "Типы" in load_workbook(io.BytesIO(z.read("Каталог.xlsx"))).sheetnames
    chars = load_workbook(io.BytesIO(z.read("Характеристики.xlsx"))).active
    assert [c.value for c in chars[4]] == [
        unit["number"],
        "Кушетка смотровая",
        "Цвет обивки",
        "бежевый",
    ]
