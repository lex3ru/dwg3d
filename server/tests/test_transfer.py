"""Перенос здания на другую установку: пакет выгружается, «другая установка» — та же база,
очищенная от каталога, зданий и учёта, — пакет проверяется и загружается; здание, расстановка
и учёт совпадают с исходными по сути (id — новые)."""

import base64
import io
import zipfile

from sqlalchemy import text

from app.core import tasks
from app.core.db import transaction
from tests.test_building import building_with_floor, save, two_rooms
from tests.test_inventory import document, post
from tests.test_planning import catalog, changes

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def source(admin) -> dict:  # type: ignore[no-untyped-def]
    b, f = building_with_floor(admin)
    rooms = {r["number"]: r["id"] for r in save(admin, f["id"], two_rooms(), 1).json()["rooms"]}
    k = catalog(admin)
    color = admin.post(
        "/api/catalog/characteristics",
        json={"type_id": k["стол"]["id"], "name": "Цвет", "kind": "text", "level": "item"},
    ).json()
    model = admin.post(
        f"/api/catalog/types/{k['стол']['id']}/models", json={"manufacturer": "Акс", "name": "Т-1"}
    ).json()["models"][0]
    wh = admin.post("/api/inventory/warehouses", json={"name": "Склад корпуса", "building_id": b["id"]}).json()
    cell = admin.post(f"/api/inventory/warehouses/{wh['id']}/cells", json={"name": "Стеллаж 1"}).json()[
        "cells"
    ][0]
    got = document(
        admin,
        "receipt",
        {"to_place": f"r:{rooms['214']}"},
        [
            {"type_id": k["стол"]["id"], "model_id": model["id"], "qty": 2, "price": 12000},
            {"type_id": k["перчатки"]["id"], "qty": 30, "price": 520},
        ],
    )
    assert post(admin, got).status_code == 200
    spare = document(
        admin, "receipt", {"to_place": f"c:{cell['id']}"}, [{"type_id": k["стол"]["id"], "qty": 1, "price": 9000}]
    )
    r = post(admin, spare)
    assert r.status_code == 200, r.text
    desks = admin.get(f"/api/inventory/documents/{got['id']}").json()["lines"][0]["created_units"]
    desk = admin.get(f"/api/inventory/units/{desks[0]['id']}").json()
    r = admin.patch(
        f"/api/inventory/units/{desk['id']}",
        json={"version": desk["version"], "values": {"values": {color["id"]: "дуб"}, "state": "broken",
                                                      "responsible": "Иванова А. А."}},
    )
    assert r.status_code == 200, r.text
    photo = admin.post(
        f"/api/inventory/units/{desk['id']}/files", params={"kind": "photo"}, files={"file": ("стол.png", PNG)}
    )
    assert photo.status_code == 201, photo.text
    items = changes(
        admin,
        f["id"],
        create=[
            {"type_id": k["стол"]["id"], "x": 1500, "y": 2000, "unit_id": desk["id"], "label": "С-1"},
            {"type_id": k["шкаф"]["id"], "x": 4500, "y": 2000, "angle": 90},
            {"type_id": k["светильник"]["id"], "x": 1500, "y": 1000},
        ],
    ).json()["items"]
    cabinet = next(i for i in items if i["type_id"] == k["шкаф"]["id"])
    assert changes(admin, f["id"], create=[{"type_id": k["коммутатор"]["id"], "parent_id": cabinet["id"]}]).status_code == 200
    return {"building": b, "floor": f, "rooms": rooms, "desk": admin.get(f"/api/inventory/units/{desk['id']}").json()}


def run_jobs() -> None:
    while tasks.run_one():
        pass


def wipe_catalog_and_buildings() -> None:
    """«Другая установка»: учётные записи те же, каталога, зданий и учёта нет."""
    with transaction() as s:
        s.execute(text("TRUNCATE building.building, catalog.layer, catalog.char_set, catalog.item_type, "
                       "catalog.purpose, inventory.document, inventory.warehouse CASCADE"))


def load(admin, data: bytes, **body):  # type: ignore[no-untyped-def]
    check = admin.post("/api/transfer/check", files={"file": ("перенос.zip", data)})
    assert check.status_code == 200, check.text
    report = check.json()
    r = admin.post("/api/transfer/import", json={"upload_id": report["upload_id"],
                                                 "name": report["building"]["suggested"], **body})
    assert r.status_code == 202, r.text
    run_jobs()
    return report, admin.get(f"/api/system/tasks/{r.json()['job_id']}").json()


def test_building_moves_to_another_installation_with_items_and_accounting(admin) -> None:
    src = source(admin)
    r = admin.get(f"/api/buildings/{src['building']['id']}/transfer.zip")
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert {"manifest.json", "catalog.json", "building.json", "items.json", "inventory.json"} <= set(z.namelist())
    assert any(n.startswith("files/") for n in z.namelist())  # фото единицы

    wipe_catalog_and_buildings()
    report, job = load(admin, r.content)
    assert report["floors"] == 1 and report["items"] == 4 and report["units"] == 3
    assert report["taken_numbers"] == []
    assert {"Стол", "Шкаф", "Перчатки", "Коммутатор"} <= set(report["catalog"]["types"])
    assert set(report["catalog"]["layers"]) == {"Мебель", "Освещение"}
    assert job["status"] == "done", job
    res = job["result"]
    assert res["items"] == 4 and res["units"] == 3

    # здание и план
    b = admin.get(f"/api/buildings/{res['building_id']}").json()
    assert b["name"] == src["building"]["name"]
    floor = b["floors"][0]
    plan = admin.get(f"/api/floors/{floor['id']}/plan").json()
    assert sorted(r["number"] for r in plan["rooms"]) == ["214", "215"]
    rooms = {r["number"]: r["id"] for r in plan["rooms"]}
    # расстановка: в своих помещениях, вложенное — во вместилище, стол связан с единицей
    items = admin.get(f"/api/floors/{floor['id']}/items").json()["items"]
    tree = admin.get("/api/catalog").json()
    name = {t["id"]: t["name"] for t in tree["types"]}
    by = {name[i["type_id"]]: i for i in items}
    assert by["Стол"]["room_id"] == rooms["214"] and by["Стол"]["label"] == "С-1"
    assert by["Шкаф"]["angle"] == 90
    assert by["Коммутатор"]["parent_id"] == by["Шкаф"]["id"]
    assert by["Стол"]["unit_id"]
    # учёт: та же единица — номер, состояние, ответственный, характеристика, фото, модель
    unit = admin.get(f"/api/inventory/units/{by['Стол']['unit_id']}").json()
    old = src["desk"]
    assert unit["number"] == old["number"] and unit["state"] == "broken"
    assert unit["responsible"] == "Иванова А. А." and unit["price"] == 12000
    assert unit["model_name"] == "Акс Т-1"
    assert unit["label_code"] == old["label_code"]  # наклейки остаются верными
    color = next(c for c in unit["characteristics"] if c["name"] == "Цвет")
    assert color["value"] == "дуб"
    assert unit["photo_url"]
    assert unit["place"]["key"] == f"r:{rooms['214']}"
    # склад с ячейкой и остаток перчаток
    units = admin.get("/api/inventory/units", params={"limit": 10}).json()
    assert units["total"] == 3
    assert any(u["place"]["title"].endswith("Стеллаж 1") for u in units["items"])
    stock = admin.get("/api/inventory/balances", params={"place": f"r:{rooms['214']}"}).json()["items"]
    assert [(s["type_name"], s["qty"]) for s in stock] == [("Перчатки", 30)]
    # всё — одним «Вводом остатков»
    docs = admin.get("/api/inventory/documents").json()["items"]
    assert [d["kind"] for d in docs] == ["opening"]


def test_into_the_same_installation_numbers_taken_and_catalog_matched(admin) -> None:
    src = source(admin)
    data = admin.get(f"/api/buildings/{src['building']['id']}/transfer.zip").content
    check = admin.post("/api/transfer/check", files={"file": ("перенос.zip", data)}).json()
    assert check["catalog"]["types"] == [] and check["catalog"]["layers"] == []  # всё совпало
    assert len(check["taken_numbers"]) == 3
    assert check["building"]["exists"] and check["building"]["suggested"] != src["building"]["name"]
    # без новых номеров — задача не проходит, и ничего не заводится
    _, job = load(admin, data)
    assert job["status"] == "failed" and "заняты" in job["error"]
    assert len(admin.get("/api/buildings").json()["items"]) == 1
    # с новыми номерами — проходит
    _, job = load(admin, data, renumber=True)
    assert job["status"] == "done", job
    assert job["result"]["renumbered"] == 3
    assert len(admin.get("/api/buildings").json()["items"]) == 2
