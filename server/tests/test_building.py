"""Здания, этажи, план и помещения (5.1.1, 5.1.2, 5.1.4–5.1.6; С2, С3)."""

import io
import uuid

from tests.conftest import login, make_client


def two_rooms(numbers=("214", "215"), partition=True) -> dict:  # type: ignore[no-untyped-def]
    """Коробка 6 × 4 м с перегородкой посередине — два кабинета."""
    plan = {
        "nodes": {"a": [0, 0], "e": [3000, 0], "b": [6000, 0], "c": [6000, 4000],
                  "f": [3000, 4000], "d": [0, 4000]},
        "walls": [
            {"id": "w1", "a": "a", "b": "e", "thickness": 300, "kind": "bearing"},
            {"id": "w2", "a": "e", "b": "b", "thickness": 300, "kind": "bearing"},
            {"id": "w3", "a": "b", "b": "c", "thickness": 300, "kind": "bearing"},
            {"id": "w4", "a": "c", "b": "f", "thickness": 300, "kind": "bearing"},
            {"id": "w5", "a": "f", "b": "d", "thickness": 300, "kind": "bearing"},
            {"id": "w6", "a": "d", "b": "a", "thickness": 300, "kind": "bearing"},
        ],
        "openings": [{"id": "o1", "wall": "w1", "kind": "window", "at": 1500, "width": 1200,
                      "height": 1500, "sill": 800}],
        "rooms": [
            {"id": "new-1", "x": 1000, "y": 2000, "number": numbers[0], "name": "Кабинет"},
            {"id": "new-2", "x": 5000, "y": 2000, "number": numbers[1], "name": "Кабинет"},
        ],
    }
    if partition:
        plan["walls"].append({"id": "w7", "a": "e", "b": "f", "thickness": 100})
        plan["openings"].append({"id": "o2", "wall": "w7", "kind": "door", "at": 3000,
                                 "width": 900, "height": 2100})
    return plan


def building_with_floor(admin) -> tuple[dict, dict]:  # type: ignore[no-untyped-def]
    b = admin.post("/api/buildings", json={"name": "Поликлиника", "address": "ул. Садовая, 12"})
    assert b.status_code == 201, b.text
    f = admin.post(f"/api/buildings/{b.json()['id']}/floors", json={"name": "2 этаж"})
    assert f.status_code == 201, f.text
    return b.json(), f.json()


def save(admin, floor_id, plan, version, **extra):  # type: ignore[no-untyped-def]
    return admin.put(f"/api/floors/{floor_id}/plan",
                     json={"plan": plan, "plan_version": version, **extra})


def test_floors_stack_by_elevation(admin) -> None:
    building, first = building_with_floor(admin)
    second = admin.post(f"/api/buildings/{building['id']}/floors",
                        json={"name": "3 этаж", "height": 3000}).json()
    assert first["elevation"] == 0 and second["elevation"] == 3300
    basement = admin.post(f"/api/buildings/{building['id']}/floors",
                          json={"name": "Подвал", "elevation": -3000}).json()
    floors = admin.get(f"/api/buildings/{building['id']}").json()["floors"]
    assert [f["name"] for f in floors] == ["Подвал", "2 этаж", "3 этаж"]
    assert admin.delete(f"/api/floors/{basement['id']}").status_code == 204


def test_plan_saves_rooms_from_closed_walls(admin) -> None:
    building, floor = building_with_floor(admin)
    check = admin.post(f"/api/floors/{floor['id']}/plan/check",
                       json={"plan": two_rooms()}).json()
    assert check["issues"] == [] and not check["needs_confirmation"]
    assert sorted(r["area"] for r in check["rooms"]) == [10.36, 10.36]

    r = save(admin, floor["id"], two_rooms(), 1)
    assert r.status_code == 200, r.text
    saved = r.json()
    rooms = {room["number"]: room for room in saved["rooms"]}
    assert set(rooms) == {"214", "215"} and rooms["214"]["area"] == 10.36
    # новые подписи получили ключи помещений
    assert set(saved["label_ids"]) == {"new-1", "new-2"}
    assert {lbl["id"] for lbl in saved["plan"]["rooms"]} == {str(r["id"]) for r in
                                                              rooms.values()}
    assert saved["plan_version"] == 2
    entry = admin.get("/api/journal", params={"ref": f"floor:{floor['id']}"}).json()["items"][0]
    assert "новые: 214 Кабинет, 215 Кабинет" in entry["summary"]


def test_stale_plan_is_refused(admin) -> None:
    _, floor = building_with_floor(admin)
    assert save(admin, floor["id"], two_rooms(), 1).status_code == 200
    r = save(admin, floor["id"], two_rooms(), 1)
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"


def test_c3_removing_a_partition_merges_rooms_after_asking(admin) -> None:
    building, floor = building_with_floor(admin)
    saved = save(admin, floor["id"], two_rooms(), 1).json()
    ids = {r["number"]: str(r["id"]) for r in saved["rooms"]}
    plan = saved["plan"]
    plan["walls"] = [w for w in plan["walls"] if w["id"] != "w7"]
    plan["openings"] = [o for o in plan["openings"] if o["wall"] != "w7"]

    r = save(admin, floor["id"], plan, saved["plan_version"])
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["code"] == "needs_confirmation"
    merge = error["details"]["merges"][0]
    assert {m["number"] for m in merge["rooms"]} == {"214", "215"} and merge["keep"] is None

    r = save(admin, floor["id"], plan, saved["plan_version"], confirm=True,
             merges=[{"rooms": [ids["214"], ids["215"]], "keep": ids["214"]}])
    assert r.status_code == 200, r.text
    after = r.json()
    assert [(x["number"], x["area"]) for x in after["rooms"]] == [("214", 21.09)]
    assert len(after["plan"]["rooms"]) == 1

    history = admin.get("/api/journal", params={"ref": f"room:{ids['215']}"}).json()["items"]
    assert "объединены: 214 Кабинет + 215 Кабинет → 214 Кабинет" in history[0]["summary"]


def test_removed_and_split_rooms_need_confirmation(admin) -> None:
    _, floor = building_with_floor(admin)
    plan = two_rooms(partition=False)
    plan["rooms"] = plan["rooms"][:1]
    saved = save(admin, floor["id"], plan, 1).json()
    # перегородка делит помещение: часть с подписью остаётся, вторая — новое помещение
    plan = saved["plan"]
    plan["walls"].append({"id": "w7", "a": "e", "b": "f", "thickness": 100})
    r = save(admin, floor["id"], plan, saved["plan_version"])
    assert r.status_code == 409
    details = r.json()["error"]["details"]
    assert details["splits"][0]["from"]["number"] == "214"
    saved = save(admin, floor["id"], plan, saved["plan_version"], confirm=True).json()
    assert sorted(r["number"] for r in saved["rooms"]) == ["", "214"]

    # убрали все стены — помещения уходят в архив после подтверждения
    empty = {"nodes": {}, "walls": [], "openings": [], "rooms": []}
    r = save(admin, floor["id"], empty, saved["plan_version"])
    assert len(r.json()["error"]["details"]["removed"]) == 2
    assert save(admin, floor["id"], empty, saved["plan_version"], confirm=True
                ).json()["rooms"] == []


def test_fix_repairs_what_is_unambiguous(admin) -> None:
    _, floor = building_with_floor(admin)
    plan = two_rooms()
    plan["nodes"]["g"] = [3002, 4000]  # узел в 2 мм от другого
    plan["walls"].append({"id": "w8", "a": "f", "b": "g", "thickness": 100})
    plan["walls"].append({"id": "w9", "a": "a", "b": "e", "thickness": 100})  # двойная
    plan["openings"][0]["at"] = 200  # окно за гранью стены
    codes = sorted(i["code"] for i in admin.post(
        f"/api/floors/{floor['id']}/plan/check", json={"plan": plan}).json()["issues"])
    assert codes == ["double_wall", "opening_outside", "short_wall"]
    fixed = admin.post(f"/api/floors/{floor['id']}/plan/fix", json={"plan": plan}).json()
    assert fixed["issues"] == []
    assert len(fixed["fixed"]) == 4
    assert fixed["plan"]["openings"][0]["at"] == 600


def test_viewer_sees_only_granted_buildings_and_changes_nothing(admin, app) -> None:
    building, floor = building_with_floor(admin)
    other = admin.post("/api/buildings", json={"name": "Хозблок"}).json()
    save(admin, floor["id"], two_rooms(), 1)
    created = admin.post("/api/users", json={
        "login": "viewer", "full_name": "Петрова Е. А.", "role": "viewer",
        "building_ids": [building["id"]], "password": "Temporary-1"}).json()
    assert created["user"]["buildings"] == [{"id": building["id"], "name": "Поликлиника"}]

    with make_client(app) as viewer:
        login(viewer, "viewer", "Temporary-1")
        viewer.post("/api/auth/password", json={"current": "Temporary-1",
                                                "new": "Viewer-pass-1"})
        names = [b["name"] for b in viewer.get("/api/buildings").json()["items"]]
        assert names == ["Поликлиника"]
        assert viewer.get(f"/api/buildings/{other['id']}").status_code == 404
        plan = viewer.get(f"/api/floors/{floor['id']}/plan").json()
        assert len(plan["rooms"]) == 2 and plan["issues"] == []
        assert save(viewer, floor["id"], two_rooms(), 2).status_code == 403
        assert viewer.post(f"/api/buildings/{building['id']}/floors",
                           json={"name": "x"}).status_code == 403
        hits = viewer.get("/api/search", params={"q": "214"}).json()["items"]
        assert hits[0]["group"] == "Помещения" and hits[0]["title"] == "214 Кабинет"


def test_lifts_span_floors(admin) -> None:
    building, first = building_with_floor(admin)
    second = admin.post(f"/api/buildings/{building['id']}/floors",
                        json={"name": "3 этаж"}).json()
    lift = admin.post(f"/api/buildings/{building['id']}/lifts", json={
        "name": "Л1", "x": 1000, "y": 1000, "w": 2000, "d": 2200,
        "floor_ids": [first["id"], second["id"]]})
    assert lift.status_code == 201, lift.text
    assert lift.json()["stop_ids"] == [first["id"], second["id"]]
    plan = admin.get(f"/api/floors/{second['id']}/plan").json()
    assert [x["name"] for x in plan["lifts"]] == ["Л1"]
    assert admin.delete(f"/api/floors/{second['id']}").status_code == 204
    lifts = admin.get(f"/api/floors/{first['id']}/plan").json()["lifts"]
    assert lifts[0]["floor_ids"] == [first["id"]]


def test_only_an_empty_building_is_deleted_and_archive_hides_it(admin) -> None:
    building, floor = building_with_floor(admin)
    r = admin.delete(f"/api/buildings/{building['id']}")
    assert r.status_code == 409 and "пустое здание" in r.json()["error"]["message"]
    admin.post(f"/api/buildings/{building['id']}/archive")
    assert admin.get("/api/buildings").json()["items"] == []
    assert admin.get(f"/api/buildings/{building['id']}").json()["archived"] is True
    assert len(admin.get("/api/buildings", params={"archived": True}).json()["items"]) == 1
    admin.delete(f"/api/floors/{floor['id']}")
    assert admin.delete(f"/api/buildings/{building['id']}").status_code == 204


def test_floor_copies_bearing_walls(admin) -> None:
    building, floor = building_with_floor(admin)
    save(admin, floor["id"], two_rooms(), 1)
    copy = admin.post(f"/api/buildings/{building['id']}/floors",
                      json={"name": "3 этаж", "copy_bearing_from": floor["id"]}).json()
    plan = admin.get(f"/api/floors/{copy['id']}/plan").json()["plan"]
    assert len(plan["walls"]) == 6 and plan["openings"] == [] and plan["rooms"] == []


def test_files_are_checked_by_content_and_stored_once(admin) -> None:
    pdf = b"%PDF-1.4\n" + b"x" * 1000
    one = admin.post("/api/files", files={"file": ("план.pdf", io.BytesIO(pdf))}).json()
    two = admin.post("/api/files", files={"file": ("копия.pdf", io.BytesIO(pdf))}).json()
    assert one["id"] != two["id"] and one["content_type"] == "application/pdf"
    assert admin.get(one["url"]).content == pdf
    r = admin.post("/api/files", files={"file": ("план.pdf", io.BytesIO(b"MZ\x90\x00exe"))})
    assert r.status_code == 400
    assert r.json()["error"]["message"].startswith("Файл «план.pdf» — не")
    assert admin.get(f"/api/files/{uuid.uuid4()}").status_code == 404


def test_floor_prints_to_pdf_and_exports_to_dxf(admin) -> None:
    import ezdxf

    _, floor = building_with_floor(admin)
    save(admin, floor["id"], two_rooms(), 1)
    r = admin.get(f"/api/floors/{floor['id']}/export.pdf", params={"paper": "A3", "scale": 50})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
    r = admin.get(f"/api/floors/{floor['id']}/export.dxf")
    doc = ezdxf.read(io.StringIO(r.content.decode()))
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"Стены несущие", "Перегородки", "Проёмы", "Помещения"} <= layers
    texts = {e.dxf.text for e in doc.modelspace().query("TEXT")}
    assert {"214", "215"} <= texts
    assert admin.get(f"/api/floors/{floor['id']}/export.pdf",
                     params={"scale": 33}).status_code == 400


def test_polyclinic_sample_has_three_clean_floors(admin) -> None:
    from app.core.db import transaction
    from app.modules.access import api as access
    from app.samples import polyclinic

    with transaction() as s:
        actor = access.actor_of(access.find(s, "admin"))
        result = polyclinic.create(s, actor)
    building = admin.get(f"/api/buildings/{result['building_id']}").json()
    assert [f["name"] for f in building["floors"]] == ["1 этаж", "2 этаж", "3 этаж"]
    for floor in building["floors"]:
        view = admin.get(f"/api/floors/{floor['id']}/plan").json()
        assert view["issues"] == [], (floor["name"], view["issues"])
        numbers = {r["number"] for r in view["rooms"]}
        assert len(view["rooms"]) == 23, floor["name"]
        assert "" not in numbers
    rooms = {r["number"]: r for r in admin.get(
        f"/api/floors/{building['floors'][1]['id']}/plan").json()["rooms"]}
    assert {"214", "215"} <= set(rooms)  # соседние кабинеты для С3
    assert len(view["lifts"]) == 1 and len(view["lifts"][0]["floor_ids"]) == 3
