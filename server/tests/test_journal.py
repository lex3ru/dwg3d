"""Журнал (5.7.3): только добавление, ленты, срок хранения."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import tasks
from app.core.db import transaction
from app.modules.journal import api as journal
from tests import test_projects as projects
from tests.test_building import save
from tests.test_inventory import document, post, setup, without_partition

PDF = b"%PDF-1.4\n" + b"x" * 1000


def feed(admin, ref: str) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    """Лента по ссылке: (действие, кто), новые сверху."""
    items = admin.get("/api/journal", params={"ref": ref, "limit": 200}).json()["items"]
    return [(e["action"], e["actor_name"]) for e in items]


def test_entries_cannot_be_changed_or_deleted(admin) -> None:
    for sql in ["UPDATE journal.entry SET summary = 'подделка'",
                "DELETE FROM journal.entry", "TRUNCATE journal.entry"]:
        with pytest.raises(DBAPIError, match="только для добавления"):
            with transaction() as s:
                s.execute(text(sql))


def test_feed_filters_and_pages(admin) -> None:
    with transaction() as s:
        for i in range(5):
            journal.record(s, None, "test.thing", f"Событие {i}", entity=f"room:{i % 2}",
                           refs=["building:b1"])
    feed = admin.get("/api/journal", params={"ref": "room:1"}).json()["items"]
    assert [e["summary"] for e in feed] == ["Событие 3", "Событие 1"]
    page = admin.get("/api/journal", params={"ref": "building:b1", "limit": 2}).json()
    assert [e["summary"] for e in page["items"]] == ["Событие 4", "Событие 3"]
    rest = admin.get("/api/journal", params={"ref": "building:b1",
                                             "before_id": page["next_before_id"]}).json()
    assert [e["summary"] for e in rest["items"]] == ["Событие 2", "Событие 1", "Событие 0"]
    assert admin.get("/api/journal", params={"q": "событие 2"}).json()["items"][0][
        "summary"] == "Событие 2"


def test_retention_purges_only_old_entries(admin) -> None:
    with transaction() as s:
        journal.record(s, None, "test.old", "Старое", entity="x:1")
        s.execute(text("SET LOCAL session_replication_role = replica"))
        s.execute(text("UPDATE journal.entry SET at = :at WHERE action = 'test.old'"),
                  {"at": datetime.now(UTC) - timedelta(days=365 * 5 + 10)})
    with transaction() as s:
        tasks.enqueue(s, "system.purge_journal")
    assert tasks.run_one()
    actions = [e["action"] for e in admin.get("/api/journal").json()["items"]]
    assert "test.old" not in actions and actions[0] == "journal.purge"


def test_r011_draft_document_is_journaled(admin) -> None:
    """Черновик документа учёта — создание, правка, скан, удаление — в журнале документа
    (9.2 п. 3, R-011): удалённый черновик оставляет след."""
    _, rooms, _, k = setup(admin)
    doc = document(admin, "receipt", {"to_place": rooms["214"]},
                   [{"type_id": k["экг"]["id"], "qty": 1, "price": 85000}])
    r = admin.put(f"/api/inventory/documents/{doc['id']}",
                  json={"version": doc["version"], "header": {"basis": "Счёт № 15"}})
    assert r.status_code == 200, r.text
    r = admin.post(f"/api/inventory/documents/{doc['id']}/files",
                   files={"file": ("счёт.pdf", PDF)})
    assert r.status_code == 201, r.text
    assert admin.delete(f"/api/inventory/documents/{doc['id']}").status_code == 204
    me = "Андреева Н. В."
    assert feed(admin, f"document:{doc['id']}") == [
        ("inventory.document_delete", me), ("inventory.document_file", me),
        ("inventory.document_update", me), ("inventory.document_create", me),
    ]


def test_r011_project_edit_is_journaled(admin) -> None:
    """Правка содержимого проекта в редакторе — запись в журнале проекта (5.3.6, R-011)."""
    b, f, _, _, (desk, _) = projects.setup(admin)
    p = projects.project(admin, b["id"], "Перестановка")
    projects.edit(admin, p, f["id"], delete=[{"id": desk["id"]}])
    assert feed(admin, f"project:{p['id']}") == [
        ("project.change", "Андреева Н. В."), ("project.create", "Андреева Н. В.")]


def test_r011_property_moved_by_room_merge_is_journaled_with_author(admin) -> None:
    """Объединили помещения — перенос единицы в журнале единицы, с тем, кто сохранил план
    (5.1.6 п. 3, R-011)."""
    _, rooms, _, k = setup(admin)
    received = post(admin, document(admin, "receipt", {"to_place": rooms["215"]},
                                    [{"type_id": k["экг"]["id"], "qty": 1, "price": 85000}]))
    uid = received.json()["lines"][0]["created_units"][0]["id"]
    floor_id, plan, version = without_partition(admin, rooms)
    r = save(admin, floor_id, plan, version, confirm=True,
             moves={rooms["215"][2:]: rooms["214"][2:]})
    assert r.status_code == 200, r.text
    assert feed(admin, f"unit:{uid}")[0] == ("inventory.room_merge", "Андреева Н. В.")
    assert "inventory.room_merge" in [a for a, _ in feed(admin, f"room:{rooms['214'][2:]}")]


def test_r041_building_and_floor_feeds_show_accounting_and_projects(admin) -> None:
    """Ленты здания и этажа (5.7.3, R-041): документы учёта, карточки единиц, склады здания,
    инвентаризации, правки проектов."""
    building, rooms, _, k = setup(admin)
    floor_id = admin.get("/api/inventory/place", params={"key": rooms["214"]}).json()[
        "place"]["floor_id"]
    doc = post(admin, document(admin, "receipt", {"to_place": rooms["214"]},
                               [{"type_id": k["экг"]["id"], "qty": 1, "price": 85000}])).json()
    uid = doc["lines"][0]["created_units"][0]["id"]
    unit = admin.get(f"/api/inventory/units/{uid}").json()
    r = admin.patch(f"/api/inventory/units/{uid}",
                    json={"version": unit["version"], "values": {"responsible": "Иванова А. А."}})
    assert r.status_code == 200, r.text
    r = admin.post("/api/inventory/warehouses",
                   json={"name": "Склад этажа", "building_id": building["id"]})
    assert r.status_code == 201, r.text
    r = admin.post("/api/inventory/counts", json={"floor_id": floor_id})
    assert r.status_code == 201, r.text
    p = projects.project(admin, building["id"], "Перестановка")
    desk = admin.post(f"/api/floors/{floor_id}/items/changes", json={"create": [
        {"type_id": k["экг"]["id"], "x": 1500, "y": 2000}]})
    assert desk.status_code == 200, desk.text
    projects.edit(admin, p, floor_id, delete=[{"id": desk.json()["items"][0]["id"]}])

    by_building = [a for a, _ in feed(admin, f"building:{building['id']}")]
    for action in ["inventory.document_create", "inventory.document_post",
                   "inventory.unit_edit", "inventory.warehouse_create",
                   "inventory.count_create", "project.change"]:
        assert action in by_building, f"{action} нет в ленте здания"
    by_floor = [a for a, _ in feed(admin, f"floor:{floor_id}")]
    for action in ["inventory.document_post", "inventory.unit_edit", "inventory.count_create",
                   "planning.change", "project.change"]:
        assert action in by_floor, f"{action} нет в ленте этажа"
