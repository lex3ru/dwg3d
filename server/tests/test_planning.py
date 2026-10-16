"""Расстановка (5.3.2; С6, С8): предметы на плане, вложение, помещения, журнал."""

import uuid

from tests.conftest import login, make_client
from tests.test_building import building_with_floor, save, two_rooms


def catalog(admin) -> dict[str, dict]:  # type: ignore[no-untyped-def]
    layer = admin.post("/api/catalog/layers", json={"name": "Мебель"}).json()
    light = admin.post("/api/catalog/layers", json={"name": "Освещение"}).json()

    def kind(name, **v):  # type: ignore[no-untyped-def]
        r = admin.post("/api/catalog/types", json={"name": name, **v})
        assert r.status_code == 201, r.text
        return r.json()

    return {
        "стол": kind("Стол", layer_id=layer["id"], width=1200, depth=600, height=750),
        "шкаф": kind(
            "Шкаф", layer_id=layer["id"], width=800, depth=400, height=1900, container=True
        ),
        "камера": kind(
            "Камера",
            layer_id=layer["id"],
            mount="wall",
            mount_height=2800,
            width=100,
            depth=150,
            height=100,
        ),
        "светильник": kind(
            "Светильник", layer_id=light["id"], mount="ceiling", width=600, depth=600, height=80
        ),
        "перчатки": kind("Перчатки", accounting="quantity"),
        "коммутатор": kind("Коммутатор", layer_id=layer["id"], mount="none"),
    }


def changes(admin, floor_id, **body):  # type: ignore[no-untyped-def]
    return admin.post(f"/api/floors/{floor_id}/items/changes", json=body)


def test_c6_items_are_placed_moved_and_removed_at_once(admin) -> None:
    building, floor = building_with_floor(admin)
    rooms = {r["number"]: r["id"] for r in save(admin, floor["id"], two_rooms(), 1).json()["rooms"]}
    kinds = catalog(admin)

    table = str(uuid.uuid4())
    r = changes(
        admin,
        floor["id"],
        create=[
            {"id": table, "type_id": kinds["стол"]["id"], "x": 1000, "y": 1000, "angle": 90},
            {"type_id": kinds["камера"]["id"], "x": 5800, "y": 3800},
            {"type_id": kinds["светильник"]["id"], "x": 4500, "y": 2000},
        ],
    )
    assert r.status_code == 200, r.text
    placed = {i["type_id"]: i for i in r.json()["items"]}
    assert placed[kinds["стол"]["id"]]["id"] == table
    assert placed[kinds["стол"]["id"]]["room_id"] == rooms["214"]
    # высота установки по умолчанию: на стене — из типа, на потолке — под потолком
    assert placed[kinds["камера"]["id"]]["z"] == 2800
    assert placed[kinds["светильник"]["id"]]["z"] == 3300 - 80
    assert placed[kinds["камера"]["id"]]["room_id"] == rooms["215"]

    # передвинуть стол в соседний кабинет и повернуть — помещение пересчитано
    r = changes(admin, floor["id"], update=[{"id": table, "version": 1, "x": 4500, "angle": 375}])
    assert r.status_code == 200, r.text
    moved = r.json()["items"][0]
    assert (moved["room_id"], moved["angle"], moved["version"]) == (rooms["215"], 15, 2)
    # устаревшая версия — отказ, ничего не меняется
    assert (
        changes(admin, floor["id"], update=[{"id": table, "version": 1, "x": 0}]).status_code == 409
    )

    items = admin.get(f"/api/floors/{floor['id']}/items").json()["items"]
    assert len(items) == 3
    # тип на плане — не удаляется, только в архив (5.2.2)
    assert admin.delete(f"/api/catalog/types/{kinds['стол']['id']}").status_code == 409
    assert admin.get(f"/api/catalog/types/{kinds['стол']['id']}").json()["used"] == 1

    r = changes(admin, floor["id"], delete=[{"id": table, "version": 2}])
    assert r.json()["deleted"] == [table]
    # отмена — тот же предмет ставится заново с тем же ключом
    r = changes(
        admin,
        floor["id"],
        create=[{"id": table, "type_id": kinds["стол"]["id"], "x": 4500, "y": 1000, "angle": 15}],
    )
    assert r.status_code == 200, r.text

    history = admin.get("/api/journal", params={"ref": f"item:{table}"}).json()["items"]
    assert history[-1]["summary"] == (
        "Расстановка «2 этаж», 214 Кабинет, 215 Кабинет: поставлены: Стол, Камера, Светильник"
    )
    assert history[0]["summary"] == "Расстановка «2 этаж», 215 Кабинет: поставлены: Стол"
    assert "изменены: Стол" in history[-2]["summary"]
    room = admin.get("/api/journal", params={"ref": f"room:{rooms['215']}"}).json()["items"]
    assert any("убраны: Стол" in h["summary"] for h in room)


def test_only_placeable_types_and_one_level_nesting(admin) -> None:
    building, floor = building_with_floor(admin)
    save(admin, floor["id"], two_rooms(), 1)
    kinds = catalog(admin)
    r = changes(admin, floor["id"], create=[{"type_id": kinds["перчатки"]["id"], "x": 0, "y": 0}])
    assert r.status_code == 400 and "не ставится на план" in r.json()["error"]["message"]

    cabinet, table, lamp = (str(uuid.uuid4()) for _ in range(3))
    r = changes(
        admin,
        floor["id"],
        create=[
            # вложенное приходит раньше вместилища — порядок в пачке не важен
            {"id": lamp, "type_id": kinds["светильник"]["id"], "parent_id": cabinet},
            {"id": cabinet, "type_id": kinds["шкаф"]["id"], "x": 1000, "y": 3500},
            {"id": table, "type_id": kinds["стол"]["id"], "x": 1500, "y": 1000},
        ],
    )
    assert r.status_code == 200, r.text
    nested = next(i for i in r.json()["items"] if i["id"] == lamp)
    assert nested["x"] is None and nested["parent_id"] == cabinet and nested["room_id"]

    # «не ставится» со слоем — только во вместилище; вынуть его нельзя
    switch = str(uuid.uuid4())
    r = changes(admin, floor["id"], create=[{"type_id": kinds["коммутатор"]["id"], "x": 1, "y": 1}])
    assert r.status_code == 400 and "только во вместилище" in r.json()["error"]["message"]
    r = changes(
        admin,
        floor["id"],
        create=[{"id": switch, "type_id": kinds["коммутатор"]["id"], "parent_id": cabinet}],
    )
    assert r.status_code == 200, r.text
    r = changes(admin, floor["id"], update=[{"id": switch, "version": 1, "parent_id": None}])
    assert r.status_code == 400

    # в стол класть нельзя; шкаф с содержимым — тоже никуда
    r = changes(admin, floor["id"], update=[{"id": lamp, "version": 1, "parent_id": table}])
    assert r.status_code == 400 and "не может содержать" in r.json()["error"]["message"]
    r = changes(admin, floor["id"], update=[{"id": cabinet, "version": 1, "parent_id": cabinet}])
    assert r.status_code == 400

    # шкаф переехал — содержимое с ним: в другом помещении
    r = changes(admin, floor["id"], update=[{"id": cabinet, "version": 1, "x": 5000}])
    items = {i["id"]: i for i in admin.get(f"/api/floors/{floor['id']}/items").json()["items"]}
    assert items[lamp]["room_id"] == items[cabinet]["room_id"] != items[table]["room_id"]

    # шкаф убрали — содержимое осталось на его месте
    r = changes(admin, floor["id"], delete=[{"id": cabinet, "version": 2}])
    out = next(i for i in r.json()["items"] if i["id"] == lamp)
    assert (out["parent_id"], out["x"], out["y"]) == (None, 5000, 3500)
    # а коммутатор сам стоять не может — убран вместе со шкафом
    assert set(r.json()["deleted"]) == {cabinet, switch}


def test_items_follow_rooms_when_the_plan_changes(admin) -> None:
    building, floor = building_with_floor(admin)
    saved = save(admin, floor["id"], two_rooms(), 1).json()
    ids = {r["number"]: r["id"] for r in saved["rooms"]}
    kinds = catalog(admin)
    r = changes(admin, floor["id"], create=[{"type_id": kinds["стол"]["id"], "x": 4500, "y": 2000}])
    item = r.json()["items"][0]
    assert item["room_id"] == ids["215"]

    # снесли перегородку, 214 продолжает — стол из 215 теперь в 214
    plan = saved["plan"]
    plan["walls"] = [w for w in plan["walls"] if w["id"] != "w7"]
    plan["openings"] = [o for o in plan["openings"] if o["wall"] != "w7"]
    r = save(
        admin,
        floor["id"],
        plan,
        saved["plan_version"],
        confirm=True,
        merges=[{"rooms": [ids["214"], ids["215"]], "keep": ids["214"]}],
    )
    assert r.status_code == 200, r.text
    after = admin.get(f"/api/items/{item['id']}").json()
    assert after["room_id"] == ids["214"]

    # этаж с предметами не удаляется (даже без плана)
    bare = admin.post(f"/api/buildings/{building['id']}/floors", json={"name": "3 этаж"}).json()
    changes(admin, bare["id"], create=[{"type_id": kinds["стол"]["id"], "x": 0, "y": 0}])
    r = admin.delete(f"/api/floors/{bare['id']}")
    assert r.status_code == 409 and "стоят предметы" in r.json()["error"]["message"]


def test_viewer_sees_items_and_changes_nothing(admin, app) -> None:
    building, floor = building_with_floor(admin)
    save(admin, floor["id"], two_rooms(), 1)
    kinds = catalog(admin)
    changes(admin, floor["id"], create=[{"type_id": kinds["стол"]["id"], "x": 1000, "y": 1000}])
    admin.post(
        "/api/users",
        json={
            "login": "viewer",
            "full_name": "Петрова Е. А.",
            "role": "viewer",
            "building_ids": [building["id"]],
            "password": "Temporary-1",
        },
    )
    with make_client(app) as viewer:
        login(viewer, "viewer", "Temporary-1")
        viewer.post("/api/auth/password", json={"current": "Temporary-1", "new": "Viewer-pass-1"})
        items = viewer.get(f"/api/floors/{floor['id']}/items").json()["items"]
        assert len(items) == 1
        r = changes(viewer, floor["id"], delete=[{"id": items[0]["id"], "version": 1}])
        assert r.status_code == 403


def test_a_row_of_lamps_is_one_action(admin) -> None:
    """С8: светильник размножен рядом с шагом 3 м — одна пачка, одна запись журнала."""
    building, floor = building_with_floor(admin)
    kinds = catalog(admin)
    row = [
        {"type_id": kinds["светильник"]["id"], "x": 1500 + 3000 * k, "y": 1000} for k in range(300)
    ]
    r = changes(admin, floor["id"], create=row)
    assert r.status_code == 200, r.text
    assert len(admin.get(f"/api/floors/{floor['id']}/items").json()["items"]) == 300
    entries = admin.get("/api/journal", params={"ref": f"floor:{floor['id']}"}).json()["items"]
    assert entries[0]["summary"].endswith("поставлены: Светильник ×300")
