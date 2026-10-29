"""Реестр имущества (5.4.8) на объёмах 8.1 (R-036): сортировка, страница и итоги считает база,
а порядок и итоги — те же, что давал прежний расчёт в Python по всем строкам."""

from types import SimpleNamespace
from typing import Any

from sqlalchemy import String, column, select, values

from app.core.db import transaction
from app.modules.access import api as access
from app.modules.building import api as building
from app.modules.inventory import places
from app.modules.inventory.models import Unit
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


def test_r036_room_title_in_database_equals_python() -> None:
    """Подпись помещения для сортировки по месту считает база (ADR-0018) — так же, как
    room_title: пустые номер и название пропускаются, без обоих — «помещение без номера»."""
    pairs = [("214", "Кабинет терапевта"), ("214", ""), ("", "Холл"), ("", ""), (None, None),
             ("  ", "x"), ("№1", None), (None, "Склад «Б»"), ("Zeta", "ёлка")]
    table = values(column("number", String), column("name", String), name="rooms").data(pairs)
    with transaction() as session:
        got = session.scalars(
            select(building.room_title_sql(table.c.number, table.c.name)).select_from(table)
        ).all()
    assert got == [building.room_title(SimpleNamespace(number=n, name=m)) for n, m in pairs]


def test_r036_place_titles_in_database_equal_cards(admin, app) -> None:
    """Подпись места в базе (сортировка по месту, ADR-0018) — та же, что в карточке: помещение
    «этаж › номер название», склад, ячейка склада; «просмотру» склад без здания недоступен."""
    building_ = stock(admin)

    def titles(login: str) -> dict[str, str]:
        with transaction() as session:
            actor = access.actor_of(access.find(session, login))
            q, title = places.title_sql(select(Unit.id), actor, Unit.place)
            return {str(i): t for i, t in session.execute(q.add_columns(title))}

    items = admin.get("/api/inventory/units", params={"limit": 1000}).json()["items"]
    assert titles("admin") == {u["id"]: u["place"]["title"] for u in items}
    assert {u["place"]["kind"] for u in items} == {"room", "warehouse", "cell"}
    with viewer(admin, app, building_["id"]) as (v, account):
        seen = v.get("/api/inventory/units", params={"limit": 1000}).json()["items"]
        got = titles(account["login"])
    assert {i: got[i] for i in (u["id"] for u in seen)} == {
        u["id"]: u["place"]["title"] for u in seen}
    hidden = {u["id"] for u in items} - {u["id"] for u in seen}
    assert hidden and {got[i] for i in hidden} == {"место недоступно"}


def test_r036_home_cost_is_sum_of_cards(admin) -> None:
    """Стоимость на главной (6.5.1) считает база, карточку — Python: итог — сумма карточек
    единиц здания (ADR-0017)."""
    building = stock(admin)
    items = admin.get("/api/inventory/units",
                      params={"building_id": building["id"], "limit": 1000}).json()["items"]
    cost = admin.get("/api/home", params={"building_id": building["id"]}).json()["cost"]
    assert cost["units"] == len(items) == 8
    assert cost["initial"] == round(sum(u["price"] for u in items), 2)
    assert cost["value"] == round(sum(u["value"] for u in items), 2)


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
