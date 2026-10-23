"""Безопасность (8.4 п. 3, 10.3): «просмотр» не получает стоимость, инвентарные номера и
проекты ни на экране, ни в ответах сервера, ни в выгрузках. Обходятся все адреса GET;
ответы (и таблицы Excel внутри) проверяются на номера и цены, которые завёл администратор."""

import io
import zipfile

from app.core.db import transaction
from app.modules.access import api as access
from tests.conftest import login, make_client
from tests.test_inventory import document, post, setup

NUMBERS = ["ТАЙНА-0001", "ТАЙНА-0002"]
PRICES = ["14537", "14 537", "14 537", "523.5", "523,5", "777331"]


def text_of(content: bytes) -> str:
    """Тело ответа как текст; у xlsx — все листы и строки."""
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            return "\n".join(
                z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml")
            )
    return content.decode("utf-8", "replace")


def test_viewer_gets_no_cost_numbers_or_projects_anywhere(pdf, admin, app) -> None:
    building, rooms, wh, k = setup(admin)
    t = k["монитор"]
    assert (
        admin.patch(
            f"/api/catalog/types/{t['id']}", json={"version": t["version"], "price": 777331}
        ).status_code
        == 200
    )
    got = document(
        admin,
        "receipt",
        {"to_place": rooms["214"]},
        [{"type_id": t["id"], "qty": 1, "price": 14537, "number": n} for n in NUMBERS]
        + [{"type_id": k["перчатки"]["id"], "qty": 10, "price": 523.5}],
    )
    assert post(admin, got).status_code == 200, post(admin, got).text
    units = [
        u["id"]
        for line in admin.get(f"/api/inventory/documents/{got['id']}").json()["lines"]
        for u in line["created_units"]
    ]
    unit = admin.get(f"/api/inventory/units/{units[0]}").json()
    assert unit["number"] == NUMBERS[0]
    floor = unit["place"]["floor_id"]
    project = admin.post(
        "/api/projects", json={"building_id": building["id"], "name": "Тайный проект"}
    ).json()
    count = admin.post("/api/inventory/counts", json={"floor_id": floor}).json()

    with transaction() as s:
        access.create(
            s,
            None,
            login_name="zav",
            full_name="Заведующий З. З.",
            role="viewer",
            building_ids=[building["id"]],
            password="Viewer-pass-123",
        )
    with make_client(app) as viewer:
        login(viewer, "zav", "Viewer-pass-123")
        viewer.post(
            "/api/auth/password", json={"current": "Viewer-pass-123", "new": "Viewer-pass-456"}
        )
        b, f, u = building["id"], floor, units[0]
        reachable = [
            "/api/buildings",
            f"/api/buildings/{b}",
            f"/api/floors/{f}/plan",
            f"/api/floors/{f}/items",
            "/api/catalog",
            f"/api/catalog/types/{t['id']}",
            "/api/inventory/places",
            f"/api/inventory/place?key={rooms['214']}",
            "/api/inventory/units",
            "/api/inventory/units/export.xlsx",
            f"/api/inventory/units/{u}",
            f"/api/inventory/units/{units[-1]}",
            f"/api/inventory/balances?place={rooms['214']}",
            f"/api/link/floors/{f}",
            f"/api/link/units/{u}",
            f"/api/q/{unit['label_code']}",
            "/api/search?q=Монитор",
            "/api/search?q=ТАЙНА",
            f"/api/floors/{f}/export.pdf",
        ]
        closed = [
            "/api/inventory/cost",
            "/api/inventory/cost.xlsx",
            "/api/inventory/documents",
            f"/api/inventory/documents/{got['id']}",
            f"/api/inventory/documents/{got['id']}/print.pdf",
            "/api/inventory/balances/history",
            "/api/inventory/counts",
            f"/api/inventory/counts/{count['id']}",
            f"/api/inventory/counts/{count['id']}/act.pdf",
            "/api/catalog/export.xlsx",
            "/api/projects",
            f"/api/projects/{project['id']}",
            f"/api/projects/{project['id']}/specification",
            f"/api/projects/{project['id']}/export.xlsx",
            "/api/reports",
            "/api/reports/registry.xlsx",
            "/api/reports/cost.xlsx",
            f"/api/home?building_id={b}",
            f"/api/home/plan?building_id={b}",
            "/api/journal",
            "/api/users",
            "/api/share-links",
            "/api/system/settings",
        ]
        leaks = []
        for url in reachable:
            r = viewer.get(url)
            assert r.status_code == 200, f"{url}: {r.status_code} {r.text[:200]}"
            body = text_of(r.content)
            leaks += [f"{url}: «{s}»" for s in [*NUMBERS, *PRICES] if s in body]
        assert not leaks, "просмотру видно:\n" + "\n".join(leaks)
        for url in closed:
            assert viewer.get(url).status_code in (403, 404), url
        # поиск по номеру ничего не находит — номера просмотру не известны
        assert not viewer.get("/api/search", params={"q": NUMBERS[0]}).json().get("items")
