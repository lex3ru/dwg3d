"""Связь планировки и учёта (5.5; С10 обходом, С12, С13): «Неразмещённые», постановка на
учёт с плана, перемещение переносом на плане, уход предмета вслед за документом."""

import uuid

from app.core.db import transaction
from app.modules.inventory.models import RoomLabel
from tests.test_inventory import document, post, setup
from tests.test_planning import changes


def floor_of(admin, rooms) -> str:  # type: ignore[no-untyped-def]
    room = rooms["214"][2:]
    return admin.get("/api/inventory/place", params={"key": f"r:{room}"}).json()["place"][
        "floor_id"
    ]


def receipt_and_issue(admin, rooms, wh, k, qty=2):  # type: ignore[no-untyped-def]
    doc = document(
        admin,
        "receipt",
        {"to_place": wh["key"]},
        [{"type_id": k["монитор"]["id"], "qty": qty, "price": 14500}],
    )
    assert post(admin, doc).status_code == 200
    units = admin.get(f"/api/inventory/documents/{doc['id']}").json()["lines"][0]["created_units"]
    issue = document(
        admin,
        "transfer",
        {"from_place": wh["key"], "to_place": rooms["214"]},
        [{"unit_id": u["id"]} for u in units],
    )
    assert post(admin, issue).status_code == 200
    return [u["id"] for u in units]


def link_view(admin, floor_id):  # type: ignore[no-untyped-def]
    r = admin.get(f"/api/link/floors/{floor_id}")
    assert r.status_code == 200, r.text
    return r.json()


def unit(admin, unit_id):  # type: ignore[no-untyped-def]
    return admin.get(f"/api/inventory/units/{unit_id}").json()


def test_c12_issued_units_wait_unplaced_and_are_placed_by_drop(admin) -> None:
    _, rooms, wh, k = setup(admin)
    floor_id = floor_of(admin, rooms)
    first, second = receipt_and_issue(admin, rooms, wh, k)
    view = link_view(admin, floor_id)
    assert set(view["unplaced"]) == {first, second}
    assert {u["room_title"] for u in view["units"]} == {"214 Кабинет"}

    # перетащили из «Неразмещённых» на стол в 214 — предмет связан с единицей
    item = str(uuid.uuid4())
    r = changes(
        admin,
        floor_id,
        create=[
            {"id": item, "type_id": k["монитор"]["id"], "unit_id": first, "x": 1000, "y": 2000}
        ],
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["unit_id"] == first
    assert r.json()["notes"] == []
    view = link_view(admin, floor_id)
    assert view["unplaced"] == [second]
    assert next(u for u in view["units"] if u["id"] == first)["item_id"] == item
    assert admin.get(f"/api/link/units/{first}").json()["item"]["item_id"] == item

    # та же единица второй раз — нельзя; другого типа — нельзя; вне помещений — нельзя
    again = changes(
        admin,
        floor_id,
        create=[{"type_id": k["монитор"]["id"], "unit_id": first, "x": 1500, "y": 2000}],
    )
    assert again.status_code == 409
    other = changes(
        admin,
        floor_id,
        create=[{"type_id": k["экг"]["id"], "unit_id": second, "x": 1500, "y": 2000}],
    )
    assert other.status_code == 400 and "другого типа" in other.json()["error"]["message"]
    outside = changes(
        admin,
        floor_id,
        create=[{"type_id": k["монитор"]["id"], "unit_id": second, "x": 9000, "y": 9000}],
    )
    assert outside.status_code == 400 and "в помещение" in outside.json()["error"]["message"]
    # вторую поставили сразу в 215 — числится там, перемещение оформлено само
    r = changes(
        admin,
        floor_id,
        create=[{"type_id": k["монитор"]["id"], "unit_id": second, "x": 5000, "y": 2000}],
    )
    assert r.status_code == 200 and r.json()["notes"][0].startswith("Оформлено «Перемещение")
    assert unit(admin, second)["place"]["key"] == rooms["215"]


def test_c13_moving_a_linked_item_to_another_room_is_a_transfer(admin) -> None:
    _, rooms, wh, k = setup(admin)
    floor_id = floor_of(admin, rooms)
    ecg, _ = receipt_and_issue(admin, rooms, wh, k)
    item = changes(
        admin,
        floor_id,
        create=[{"type_id": k["монитор"]["id"], "unit_id": ecg, "x": 1000, "y": 2000}],
    ).json()["items"][0]
    # внутри помещения — только расстановка
    r = changes(admin, floor_id, update=[{"id": item["id"], "version": item["version"], "x": 1200}])
    assert r.status_code == 200 and r.json()["notes"] == []
    item = r.json()["items"][0]
    before = len(unit(admin, ecg)["movements"])
    # перенесли в 215 — в учёте числится там, документ «Перемещение» от имени перенёсшего
    r = changes(admin, floor_id, update=[{"id": item["id"], "version": item["version"], "x": 5000}])
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["room_id"] == rooms["215"][2:]
    card = unit(admin, ecg)
    assert card["place"]["key"] == rooms["215"]
    assert len(card["movements"]) == before + 1
    docs = admin.get("/api/inventory/documents", params={"unit_id": ecg}).json()["items"]
    moved = next(d for d in docs if d["basis"] == "Перенос на плане")
    assert moved["kind"] == "transfer" and moved["status"] == "posted"
    assert moved["created_by"] == "Андреева Н. В."
    # предмет остался на плане и связан
    assert link_view(admin, floor_id)["unplaced"] == [
        u for u in link_view(admin, floor_id)["unplaced"] if u != ecg
    ]


def test_unit_moved_or_written_off_by_document_leaves_the_plan(admin) -> None:
    _, rooms, wh, k = setup(admin)
    floor_id = floor_of(admin, rooms)
    a, b = receipt_and_issue(admin, rooms, wh, k)
    items = changes(
        admin,
        floor_id,
        create=[
            {"type_id": k["монитор"]["id"], "unit_id": a, "x": 1000, "y": 2000},
            {"type_id": k["монитор"]["id"], "unit_id": b, "x": 1000, "y": 1000},
        ],
    ).json()["items"]
    # вернули на склад документом — предмет ушёл с плана, на складе единица не «неразмещённая»
    back = document(admin, "transfer", {"to_place": wh["key"]}, [{"unit_id": a}])
    assert post(admin, back).status_code == 200
    left = {i["id"] for i in admin.get(f"/api/floors/{floor_id}/items").json()["items"]}
    assert items[0]["id"] not in left and items[1]["id"] in left
    assert a not in link_view(admin, floor_id)["unplaced"]
    # отменили возврат — единица снова в 214 и ждёт расстановки
    assert admin.post(f"/api/inventory/documents/{back['id']}/cancel").status_code == 200
    assert a in link_view(admin, floor_id)["unplaced"]
    # списание тоже убирает предмет
    off = document(admin, "writeoff", {"reason": "сломан"}, [{"unit_id": b}])
    assert post(admin, off).status_code == 200
    assert admin.get(f"/api/floors/{floor_id}/items").json()["items"] == []


def test_removing_a_linked_item_returns_or_writes_off(admin) -> None:
    _, rooms, wh, k = setup(admin)
    floor_id = floor_of(admin, rooms)
    a, b = receipt_and_issue(admin, rooms, wh, k)
    items = changes(
        admin,
        floor_id,
        create=[
            {"type_id": k["монитор"]["id"], "unit_id": a, "x": 1000, "y": 2000},
            {"type_id": k["монитор"]["id"], "unit_id": b, "x": 1000, "y": 1000},
        ],
    ).json()["items"]
    r = admin.post(
        "/api/link/remove",
        json={"item_ids": [items[0]["id"]], "mode": "return", "to_place": wh["key"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == [items[0]["id"]]
    assert unit(admin, a)["place"]["key"] == wh["key"]
    no_reason = admin.post(
        "/api/link/remove", json={"item_ids": [items[1]["id"]], "mode": "writeoff"}
    )
    assert no_reason.status_code == 400
    r = admin.post(
        "/api/link/remove",
        json={"item_ids": [items[1]["id"]], "mode": "writeoff", "reason": "разбит"},
    )
    assert r.status_code == 200 and r.json()["document"]["title"].startswith("Списание")
    assert unit(admin, b)["state"] == "written_off"
    # только убрать с плана — обычное действие: единица остаётся и ждёт расстановки
    c = receipt_and_issue(admin, rooms, wh, k, qty=1)[0]
    item = changes(
        admin,
        floor_id,
        create=[{"type_id": k["монитор"]["id"], "unit_id": c, "x": 1000, "y": 2000}],
    ).json()["items"][0]
    assert changes(admin, floor_id, delete=[{"id": item["id"]}]).status_code == 200
    assert c in link_view(admin, floor_id)["unplaced"]


def test_c10_walk_puts_items_on_the_books_and_counts_quantities(admin) -> None:
    _, rooms, wh, k = setup(admin)
    floor_id = floor_of(admin, rooms)
    layer = k["монитор"]["layer_id"]
    lamp = admin.post(
        "/api/catalog/types",
        json={
            "name": "Светильник",
            "layer_id": layer,
            "accounting": "quantity",
            "unit": "шт.",
            "mount": "ceiling",
        },
    ).json()
    created = changes(
        admin,
        floor_id,
        create=[
            {"type_id": k["монитор"]["id"], "x": 1000, "y": 2000},
            {"type_id": k["экг"]["id"], "x": 1000, "y": 1000},
            *[{"type_id": lamp["id"], "x": 500 + 600 * i, "y": 3000} for i in range(3)],
        ],
    ).json()["items"]
    ids = [i["id"] for i in created]
    r = admin.post(
        "/api/link/register",
        json={
            "floor_id": floor_id,
            "item_ids": ids,
            "kind": "opening",
            "prices": {k["экг"]["id"]: 85000, lamp["id"]: 1200},
            "responsible": "Петрова А. С.",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["document"]["title"].startswith("Ввод остатков")
    assert len(out["unit_ids"]) == 2
    numbers = [unit(admin, u)["number"] for u in out["unit_ids"]]
    assert numbers[1] == f"{int(numbers[0]) + 1:06d}"
    ecg = unit(admin, out["unit_ids"][1])
    assert ecg["place"]["key"] == rooms["214"] and ecg["responsible"] == "Петрова А. С."
    assert float(ecg["price"]) == 85000
    view = link_view(admin, floor_id)
    assert view["unplaced"] == [] and view["mismatch"] == []
    # второй раз — уже на учёте
    again = admin.post("/api/link/register", json={"floor_id": floor_id, "item_ids": ids[:1]})
    assert again.status_code == 409
    # поставили ещё светильник — сверка: на плане 4, по учёту 3
    changes(admin, floor_id, create=[{"type_id": lamp["id"], "x": 2300, "y": 3000}])
    mismatch = link_view(admin, floor_id)["mismatch"]
    assert [(m["type_name"], m["on_plan"], m["in_stock"]) for m in mismatch] == [
        ("Светильник", 4, 3.0)
    ]


def test_new_room_outlines_move_linked_units_with_their_items(admin) -> None:
    _, rooms, wh, k = setup(admin)
    floor_id = floor_of(admin, rooms)
    a, _ = receipt_and_issue(admin, rooms, wh, k)
    changes(
        admin,
        floor_id,
        create=[{"type_id": k["монитор"]["id"], "unit_id": a, "x": 2500, "y": 2000}],
    )
    # перегородку сдвинули левее — монитор (x = 2500) теперь в 215
    plan = admin.get(f"/api/floors/{floor_id}/plan").json()
    p = plan["plan"]
    p["nodes"]["e"] = [2000, 0]
    p["nodes"]["f"] = [2000, 4000]
    r = admin.put(
        f"/api/floors/{floor_id}/plan",
        json={"plan": p, "plan_version": plan["plan_version"], "confirm": True},
    )
    assert r.status_code == 200, r.text
    assert unit(admin, a)["place"]["key"] == rooms["215"]
    docs = admin.get("/api/inventory/documents", params={"unit_id": a}).json()["items"]
    assert any(d["basis"] == "Изменение плана" for d in docs)


def test_door_label_opens_the_room_for_a_walk(pdf, admin) -> None:
    _, rooms, _, _ = setup(admin)
    room = rooms["214"][2:]
    r = admin.post(
        "/api/inventory/labels.pdf", json={"room_ids": [room], "origin": "http://localhost"}
    )
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    with transaction() as s:
        code = s.get(RoomLabel, uuid.UUID(room)).label_code
    target = admin.get(f"/api/q/{code}").json()
    assert target["kind"] == "room"
    assert target["href"].endswith(f"?room={room}&mode=place")
