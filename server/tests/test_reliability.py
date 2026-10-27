"""Надёжность (8.3 п. 1, 10.3): сбой посреди операции не оставляет данные наполовину
изменёнными — документ проводится, план сохраняется, загрузка выполняется целиком или
никак. Сбой подставляется в самый конец операции, когда всё остальное уже записано в
транзакцию: после неё не должно остаться ничего."""

import copy

import pytest

from app.modules.building import api as building
from app.modules.inventory import documents
from tests.test_building import save, two_rooms
from tests.test_inventory import document, post, setup


class Crash(RuntimeError):
    pass


def crash(*_: object, **__: object) -> None:
    raise Crash("сбой посреди операции")


def balances(admin) -> list:  # type: ignore[no-untyped-def]
    return admin.get("/api/inventory/balances").json()["items"]


def test_crash_while_posting_leaves_draft_and_nothing_moved(admin, monkeypatch) -> None:
    _, rooms, wh, k = setup(admin)
    got = document(
        admin,
        "receipt",
        {"to_place": wh["key"]},
        [
            {"type_id": k["монитор"]["id"], "qty": 3, "price": 14500},
            {"type_id": k["перчатки"]["id"], "qty": 20, "price": 520},
        ],
    )
    assert post(admin, got).status_code == 200
    units = [
        u["id"]
        for u in admin.get(f"/api/inventory/documents/{got['id']}").json()["lines"][0][
            "created_units"
        ]
    ]
    stock = balances(admin)
    move = document(
        admin,
        "transfer",
        {"from_place": wh["key"], "to_place": rooms["214"]},
        [*({"unit_id": u} for u in units), {"type_id": k["перчатки"]["id"], "qty": 5}],
    )

    # сбой — когда строки уже проведены, документ помечен проведённым и записан в журнал
    monkeypatch.setattr(documents, "_units_changed", crash)
    with pytest.raises(Crash):
        post(admin, move)
    monkeypatch.undo()

    after = admin.get(f"/api/inventory/documents/{move['id']}").json()
    assert after["status"] == "draft" and after["version"] == move["version"]
    assert {admin.get(f"/api/inventory/units/{u}").json()["place"]["key"] for u in units} == {
        wh["key"]
    }
    assert balances(admin) == stock
    assert not admin.get(
        "/api/journal",
        params={"ref": f"document:{move['id']}", "action": "inventory.document_post"},
    ).json()["items"]
    # и после сбоя документ проводится как обычно
    assert post(admin, move).status_code == 200
    assert {admin.get(f"/api/inventory/units/{u}").json()["place"]["key"] for u in units} == {
        rooms["214"]
    }


def test_crash_while_saving_plan_keeps_previous_plan(admin, monkeypatch) -> None:
    b = admin.post("/api/buildings", json={"name": "Корпус"}).json()
    floor = admin.post(f"/api/buildings/{b['id']}/floors", json={"name": "1 этаж"}).json()
    first = save(admin, floor["id"], two_rooms(), 1)
    assert first.status_code == 200, first.text
    before = admin.get(f"/api/floors/{floor['id']}/plan").json()

    changed = copy.deepcopy(before["plan"])
    for label, number in zip(changed["rooms"], ("301", "302"), strict=True):
        label["number"] = number
    # сбой — после записи плана и помещений, в обработчиках других модулей
    monkeypatch.setattr(building, "_on_plan_saved", [*building._on_plan_saved, crash])
    with pytest.raises(Crash):
        r = save(admin, floor["id"], changed, before["plan_version"])
        pytest.fail(f"сохранение не дошло до сбоя: {r.status_code} {r.text}")
    monkeypatch.undo()

    after = admin.get(f"/api/floors/{floor['id']}/plan").json()
    assert after["plan_version"] == before["plan_version"]
    assert after["plan"] == before["plan"]
    assert sorted(r["number"] for r in after["rooms"]) == ["214", "215"]


def test_crash_while_loading_excel_loads_nothing(admin, monkeypatch) -> None:
    import json

    from app.core.db import transaction
    from app.modules.access import api as access
    from app.modules.catalog.module import seed
    from app.samples import polyclinic
    from tests.test_inventory import SAMPLE, confirmed_rooms

    with transaction() as s:
        b = polyclinic.create(s, access.actor_of(access.find(s, "admin")))
    with transaction() as s:
        seed(s)
    files = {"file": ("имущество.xlsx", SAMPLE.read_bytes())}
    mapping = json.dumps({"rooms": confirmed_rooms(admin, b["building_id"])})
    data = {"building_id": str(b["building_id"]), "mapping": mapping, "apply": "true"}
    # сбой — когда единицы уже заведены и остаётся провести «Ввод остатков»
    monkeypatch.setattr(documents, "post", crash)
    with pytest.raises(Crash):
        admin.post("/api/inventory/import", data=data, files=files)
    monkeypatch.undo()
    assert admin.get("/api/inventory/units", params={"limit": 1}).json()["total"] == 0
    assert not admin.get("/api/inventory/documents").json()["items"]
    assert balances(admin) == []
    done = admin.post("/api/inventory/import", data=data, files=files).json()
    assert done["applied"], done.get("errors", [])[:3]
