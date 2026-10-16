"""Проекты (5.3.6, 5.5; С9): изменения поверх расстановки, «устарел», сравнение,
спецификация и смета, выгрузка, применение с выдачей со склада и «к закупке»."""

import uuid

from tests.conftest import login, make_client
from tests.test_building import building_with_floor, save, two_rooms
from tests.test_calc import catalog
from tests.test_inventory import document, post
from tests.test_planning import changes


def setup(admin):  # type: ignore[no-untyped-def]
    types, _ = catalog(admin)
    b, f = building_with_floor(admin)
    rooms = {r["number"]: r["id"] for r in save(admin, f["id"], two_rooms(), 1).json()["rooms"]}
    t = {
        n: types[n]["id"]
        for n in (
            "Стол письменный 1200×600",
            "Шкаф для документов",
            "Кушетка смотровая",
            "Стол процедурный",
        )
    }
    layout = changes(
        admin,
        f["id"],
        create=[
            {"type_id": t["Стол письменный 1200×600"], "x": 1500, "y": 2000},
            {"type_id": t["Шкаф для документов"], "x": 600, "y": 3500},
        ],
    ).json()["items"]
    return b, f, rooms, t, layout


def project(admin, building_id, name, copy_of=None):  # type: ignore[no-untyped-def]
    r = admin.post(
        "/api/projects", json={"building_id": building_id, "name": name, "copy_of": copy_of}
    )
    assert r.status_code == 201, r.text
    return r.json()


def edit(admin, p, floor_id, **body):  # type: ignore[no-untyped-def]
    r = admin.post(f"/api/projects/{p['id']}/floors/{floor_id}/changes", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_c9_project_changes_layout_only_when_applied(admin, app) -> None:
    b, f, rooms, t, (desk, cabinet) = setup(admin)
    a = project(admin, b["id"], "Процедурный 214")
    couch = str(uuid.uuid4())
    edit(
        admin,
        a,
        f["id"],
        delete=[{"id": desk["id"]}],
        create=[
            {
                "id": couch,
                "type_id": t["Кушетка смотровая"],
                "x": 1000,
                "y": 1000,
                "angle": 0,
                "z": 0,
            },
            {"type_id": t["Стол процедурный"], "x": 2200, "y": 1000},
        ],
        update=[{"id": cabinet["id"], "x": 2500}],
    )
    state = admin.get(f"/api/projects/{a['id']}/floors/{f['id']}").json()
    marks = sorted(i["state"] for i in state["items"] if i["state"])
    assert marks == ["added", "added", "moved"]
    assert [i["id"] for i in state["removed"]] == [desk["id"]]
    assert state["rooms"] == ["214 Кабинет"]
    # расстановка не тронута
    layout = {i["id"]: i for i in admin.get(f"/api/floors/{f['id']}/items").json()["items"]}
    assert set(layout) == {desk["id"], cabinet["id"]} and layout[cabinet["id"]]["x"] == 600
    # вернули шкаф на место — изменения нет
    edit(admin, a, f["id"], update=[{"id": cabinet["id"], "x": 600}])
    assert admin.get(f"/api/projects/{a['id']}").json()["changes"] == 3
    edit(admin, a, f["id"], update=[{"id": cabinet["id"], "x": 2500}])
    view = admin.get(f"/api/projects/{a['id']}").json()
    assert view["status"] == "draft" and (view["added"], view["moved"], view["removed"]) == (
        2,
        1,
        1,
    )

    # второй вариант — копия без кушетки; сравнение
    v2 = project(admin, b["id"], "Процедурный 214, вариант 2", copy_of=a["id"])
    edit(admin, v2, f["id"], delete=[{"id": couch}])
    vs_layout = admin.get(f"/api/projects/{a['id']}/compare").json()
    assert vs_layout["b"] == "Как есть"
    assert vs_layout["counts"] == {"добавлен": 2, "перемещён": 1, "убран": 1}
    vs_v2 = admin.get(f"/api/projects/{a['id']}/compare", params={"other": v2["id"]}).json()
    assert [(r["type"], r["what"]) for r in vs_v2["rows"]] == [("Кушетка смотровая", "добавлен")]

    # спецификация: кушетка есть на складе, стол — купить
    wh = admin.post("/api/inventory/warehouses", json={"name": "Основной"}).json()
    got = document(
        admin,
        "receipt",
        {"to_place": wh["key"]},
        [{"type_id": t["Кушетка смотровая"], "qty": 1, "price": 9000}],
    )
    assert post(admin, got).status_code == 200
    spec = admin.get(f"/api/projects/{a['id']}/specification").json()
    rows = {r["type"]: r for r in spec["rows"]}
    assert (rows["Кушетка смотровая"]["have"], rows["Кушетка смотровая"]["buy"]) == (1, 0)
    assert rows["Стол процедурный"]["buy"] == 1 and rows["Стол процедурный"]["price"] > 0
    assert spec["total"] == rows["Стол процедурный"]["sum"]

    # выгрузка для руководства
    pdf = admin.get(f"/api/projects/{a['id']}/export.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    xlsx = admin.get(f"/api/projects/{a['id']}/export.xlsx")
    assert xlsx.content[:2] == b"PK"

    # расстановку изменили там, где проект меняет, — «устарел»
    changes(
        admin, f["id"], update=[{"id": cabinet["id"], "version": cabinet["version"], "y": 3000}]
    )
    view = admin.get(f"/api/projects/{a['id']}").json()
    assert view["status"] == "outdated"
    assert "передвинули" in view["conflicts"][0]["text"]

    # применение: кушетку — со склада, стол — к закупке; шкаф остаётся в проекте
    plan = admin.get(f"/api/projects/{a['id']}/apply").json()
    couch_plan = next(i for i in plan["items"] if i["item_id"] == couch)
    unit_id = couch_plan["suggested"]
    assert unit_id and len(plan["conflicts"]) == 1
    desk2 = next(i for i in plan["items"] if i["item_id"] != couch)["item_id"]
    r = admin.post(
        f"/api/projects/{a['id']}/apply",
        json={"version": view["version"], "choices": {couch: unit_id, desk2: "buy"}},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["applied"], out["kept"]) == (3, 1)
    assert out["notes"][0].startswith("Оформлено «Перемещение")
    layout = {i["id"]: i for i in admin.get(f"/api/floors/{f['id']}/items").json()["items"]}
    assert desk["id"] not in layout
    assert layout[couch]["unit_id"] == unit_id
    assert layout[desk2]["params"] == {"project.buy": True}
    unit = admin.get(f"/api/inventory/units/{unit_id}").json()
    assert unit["place"]["key"] == f"r:{rooms['214']}"
    assert out["project"]["status"] == "outdated" and out["project"]["changes"] == 1

    # «просмотр» проектов не видит
    admin.post(
        "/api/users",
        json={
            "login": "viewer",
            "full_name": "Петрова Е. А.",
            "role": "viewer",
            "building_ids": [b["id"]],
            "password": "Temporary-1",
        },
    )
    with make_client(app) as viewer:
        login(viewer, "viewer", "Temporary-1")
        viewer.post("/api/auth/password", json={"current": "Temporary-1", "new": "Viewer-pass-1"})
        assert viewer.get("/api/projects").status_code == 403
        assert viewer.get(f"/api/projects/{a['id']}/specification").status_code == 403


def test_project_undo_restores_removed_and_archive_blocks_edits(admin) -> None:
    b, f, _, t, (desk, _) = setup(admin)
    p = project(admin, b["id"], "Перестановка")
    edit(admin, p, f["id"], delete=[{"id": desk["id"]}])
    assert admin.get(f"/api/projects/{p['id']}").json()["removed"] == 1
    # отмена в редакторе — тот же предмет «поставить» обратно: изменения нет
    edit(admin, p, f["id"], create=[{**desk}])
    assert admin.get(f"/api/projects/{p['id']}").json()["changes"] == 0
    view = admin.patch(
        f"/api/projects/{p['id']}", json={"version": p["version"], "archived": True}
    ).json()
    assert view["status"] == "archived"
    r = admin.post(
        f"/api/projects/{p['id']}/floors/{f['id']}/changes", json={"delete": [{"id": desk["id"]}]}
    )
    assert r.status_code == 409
    assert admin.get("/api/projects", params={"building_id": b["id"]}).json()["items"] == []
    assert (
        len(
            admin.get("/api/projects", params={"building_id": b["id"], "archived": True}).json()[
                "items"
            ]
        )
        == 1
    )
    assert admin.delete(f"/api/projects/{p['id']}").status_code == 204
    # тип, который проект ставит, из каталога не удаляется
    q = project(admin, b["id"], "Новое")
    edit(admin, q, f["id"], create=[{"type_id": t["Стол процедурный"], "x": 1000, "y": 1000}])
    assert admin.delete(f"/api/catalog/types/{t['Стол процедурный']}").status_code == 409
