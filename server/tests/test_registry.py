"""Реестр имущества (5.4.8) на объёмах 8.1 (R-036): сортировка, страница и итоги считает база,
а порядок и итоги — те же, что давал прежний расчёт в Python по всем строкам."""

from typing import Any

from tests.test_events import viewer
from tests.test_inventory import document, post, setup

SORTS = ("number", "title", "place", "state", "commissioned_on", "price", "responsible", "нет")


def reference(items: list[dict[str, Any]], sort: str, admin: bool) -> list[str]:
    """Порядок прежнего реестра: строки по коду символов, при равных — по номеру, а у
    «просмотра» — по ключу записи; «просмотру» по цене и номеру — по наименованию (R-015)."""
    by = sort.lstrip("-")
    if by == "price" and not admin:
        by = "title"
    if by not in ("title", "place", "state", "commissioned_on", "price", "responsible"):
        by = "number" if admin else "title"
    key = {
        "number": lambda u: u["number"],
        "title": lambda u: u["type_name"],
        "place": lambda u: u["place"]["title"],
        "state": lambda u: u["state"],
        "commissioned_on": lambda u: u["commissioned_on"],
        "price": lambda u: u["price"],
        "responsible": lambda u: u["responsible"],
    }[by]
    tie = (lambda u: u["number"]) if admin else (lambda u: u["id"])
    ordered = sorted(items, key=lambda u: (key(u), tie(u)), reverse=sort.startswith("-"))
    return [u["id"] for u in ordered]


def stock(admin) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Единицы в помещениях, на складе и в ячейке; равные цены, даты и наименования; имена
    ответственных, которые по алфавиту и по кодам символов идут по-разному."""
    building, rooms, wh, k = setup(admin)
    cell = admin.post(f"/api/inventory/warehouses/{wh['id']}/cells", json={"name": "Стеллаж 1"})
    assert cell.status_code == 201, cell.text
    zebra = admin.post("/api/catalog/types", json={"name": "Zebra-принтер", "life_months": 36})
    lower = admin.post("/api/catalog/types", json={"name": "аппарат УЗИ", "life_months": 120})
    assert zebra.status_code == lower.status_code == 201
    batches = [
        (rooms["214"], [
            {"type_id": k["монитор"]["id"], "qty": 3, "price": 300, "responsible": "Иванов",
             "commissioned_on": "2020-01-15"},
            {"type_id": k["экг"]["id"], "qty": 2, "price": 1000, "responsible": "иванов",
             "commissioned_on": "2021-06-01"},
        ]),
        (rooms["215"], [
            {"type_id": k["монитор"]["id"], "qty": 2, "price": 300, "responsible": "Ёлкин",
             "commissioned_on": "2020-01-15"},
            {"type_id": zebra.json()["id"], "qty": 1, "price": 99.99, "responsible": "Zeta",
             "commissioned_on": "2023-03-03"},
        ]),
        (wh["key"], [
            {"type_id": k["монитор"]["id"], "qty": 2, "price": 100, "responsible": "alpha"},
            {"type_id": lower.json()["id"], "qty": 1, "price": 2500000.5},
        ]),
        (cell.json()["cells"][0]["key"], [
            {"type_id": k["экг"]["id"], "qty": 1, "price": 500, "responsible": "Петров",
             "commissioned_on": "2019-12-31"},
        ]),
    ]
    for place, lines in batches:
        doc = document(admin, "receipt", {"to_place": place}, lines)
        assert post(admin, doc).status_code == 200
    some = admin.get("/api/inventory/units", params={"limit": 1}).json()["items"][0]
    r = admin.patch(f"/api/inventory/units/{some['id']}",
                    json={"version": some["version"], "values": {"state": "broken"}})
    assert r.status_code == 200, r.text
    return building


def test_r036_registry_order_pages_and_totals_as_before(admin, app) -> None:
    building = stock(admin)

    def check(client, is_admin: bool) -> None:  # type: ignore[no-untyped-def]
        everything = client.get("/api/inventory/units", params={"limit": 1000}).json()
        items = everything["items"]
        assert everything["total"] == len(items) > 0
        if is_admin:
            assert everything["sum_price"] == round(sum(u["price"] for u in items), 2)
            assert everything["sum_value"] == round(sum(u["value"] for u in items), 2)
        else:
            assert "sum_price" not in everything and "sum_value" not in everything
        for sort in SORTS:
            for s in (sort, f"-{sort}"):
                want = reference(items, s, is_admin)
                got = client.get("/api/inventory/units", params={"sort": s, "limit": 1000})
                assert [u["id"] for u in got.json()["items"]] == want, s
                page = client.get("/api/inventory/units",
                                  params={"sort": s, "offset": 3, "limit": 4}).json()
                assert [u["id"] for u in page["items"]] == want[3:7], s
                assert page["total"] == len(items)

    check(admin, True)
    with viewer(admin, app, building["id"]) as (v, _):
        check(v, False)


def test_r036_registry_filters_and_totals_agree(admin) -> None:
    """Итоги — по отбору, а не по странице и не по всему реестру."""
    stock(admin)
    every = admin.get("/api/inventory/units", params={"limit": 1000}).json()["items"]
    mine = [u for u in every if u["responsible"].lower() == "иванов"]
    got = admin.get("/api/inventory/units", params={"responsible": "иванов", "limit": 2}).json()
    assert got["total"] == len(mine) == 5
    assert len(got["items"]) == 2
    assert got["sum_price"] == round(sum(u["price"] for u in mine), 2)
    assert got["sum_value"] == round(sum(u["value"] for u in mine), 2)
