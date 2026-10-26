"""Инвентаризация (5.4.6, С18): ведомость этажа, обход со сканом меток и ручными отметками,
вещь без метки, пересчёт остатков, проведение расхождений, акт; запрет документов задним
числом раньше проведённой инвентаризации (5.4.4 п. 2)."""

from datetime import date, timedelta

from app.core.db import transaction
from app.modules.access import api as access
from tests.test_inventory import document, post, setup


def floor_id(admin, rooms):  # type: ignore[no-untyped-def]
    key = rooms["214"]
    return admin.get("/api/inventory/place", params={"key": key}).json()["place"]["floor_id"]


def unit(admin, unit_id):  # type: ignore[no-untyped-def]
    return admin.get(f"/api/inventory/units/{unit_id}").json()


def test_c18_count_by_scanning_and_posting_discrepancies(pdf, admin) -> None:
    _, rooms, wh, k = setup(admin)
    got = document(
        admin,
        "receipt",
        {"to_place": rooms["214"]},
        [
            {"type_id": k["монитор"]["id"], "qty": 3, "price": 14500},
            {"type_id": k["перчатки"]["id"], "qty": 20, "price": 520},
        ],
    )
    assert post(admin, got).status_code == 200
    ecg = document(
        admin,
        "receipt",
        {"to_place": rooms["215"]},
        [{"type_id": k["экг"]["id"], "qty": 1, "price": 85000}],
    )
    assert post(admin, ecg).status_code == 200
    monitors = admin.get(f"/api/inventory/documents/{got['id']}").json()["lines"][0][
        "created_units"
    ]
    ecg_unit = admin.get(f"/api/inventory/documents/{ecg['id']}").json()["lines"][0][
        "created_units"
    ][0]
    codes = {u["id"]: unit(admin, u["id"])["label_code"] for u in [*monitors, ecg_unit]}

    r = admin.post("/api/inventory/counts", json={"floor_id": floor_id(admin, rooms)})
    assert r.status_code == 201, r.text
    count = r.json()
    assert count["title"].startswith("Инвентаризация ИН-")
    assert count["summary"]["expected"] == 4 and len(count["places"]) == 2

    scan = lambda code, place: admin.post(  # noqa: E731
        f"/api/inventory/counts/{count['id']}/scan", json={"code": code, "place": place}
    ).json()
    assert scan(codes[monitors[0]["id"]], rooms["214"])["result"] == "here"
    assert scan(codes[monitors[0]["id"]], rooms["214"])["result"] == "again"
    moved = scan(codes[monitors[1]["id"]], rooms["215"])
    assert moved["result"] == "elsewhere" and "числится" in moved["text"]
    assert scan("ZZZZZZZZZZZZ", rooms["214"])["result"] == "unknown"
    # номер с наклейки, набранный руками, — тоже
    assert scan(unit(admin, ecg_unit["id"])["number"], rooms["215"])["result"] == "here"
    # вещь без метки — заведётся
    r = admin.post(
        f"/api/inventory/counts/{count['id']}/extras",
        json={
            "place": rooms["214"],
            "type_id": k["экг"]["id"],
            "serial": "SN-77",
            "note": "без наклейки",
        },
    )
    assert r.status_code == 201, r.text
    # перчаток насчитали 17 из 20
    assert (
        admin.put(
            f"/api/inventory/counts/{count['id']}/stock",
            json={"place": rooms["214"], "type_id": k["перчатки"]["id"], "counted": 17},
        ).status_code
        == 204
    )

    detail = admin.get(
        f"/api/inventory/counts/{count['id']}", params={"place": rooms["214"]}
    ).json()
    statuses = sorted(x["status"] for x in detail["place"]["items"])
    assert statuses == ["elsewhere", "here", "missing"]
    assert detail["place"]["stock"][0]["counted"] == 17
    assert detail["summary"] == {
        "expected": 4,
        "found_in_place": 2,
        "found_elsewhere": 1,
        "missing": 1,
        "extras": 1,
        "stock_diff": 1,
    }

    # пока идёт обход — движения по месту предупреждают
    move = document(
        admin,
        "transfer",
        {"from_place": rooms["214"], "to_place": wh["key"]},
        [{"unit_id": monitors[0]["id"]}],
    )
    assert (
        "идёт «Инвентаризация"
        in admin.get(f"/api/inventory/documents/{move['id']}").json()["warnings"][0]
    )
    admin.delete(f"/api/inventory/documents/{move['id']}")

    statement = admin.get(f"/api/inventory/counts/{count['id']}/statement.pdf")
    assert statement.status_code == 200 and statement.content[:5] == b"%PDF-"
    assert admin.get(f"/api/inventory/counts/{count['id']}/act.pdf").status_code == 400

    view = admin.get(f"/api/inventory/counts/{count['id']}").json()
    r = admin.post(f"/api/inventory/counts/{count['id']}/post", json={"version": view["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "posted"
    assert unit(admin, monitors[1]["id"])["place"]["key"] == rooms["215"]
    assert unit(admin, monitors[2]["id"])["state"] == "not_found"
    assert unit(admin, monitors[0]["id"])["state"] == "in_use"
    new = [
        u
        for u in admin.get("/api/inventory/units", params={"place": rooms["214"]}).json()["items"]
        if u["serial"] == "SN-77"
    ]
    assert len(new) == 1
    stock = admin.get("/api/inventory/balances", params={"place": rooms["214"]}).json()["items"]
    assert [s["qty"] for s in stock] == [17]
    act = admin.get(f"/api/inventory/counts/{count['id']}/act.pdf")
    assert act.status_code == 200 and act.content[:5] == b"%PDF-"
    # отметки после проведения не меняются
    late_scan = admin.post(
        f"/api/inventory/counts/{count['id']}/scan",
        json={"code": codes[monitors[2]["id"]], "place": rooms["214"]},
    )
    assert late_scan.status_code == 409

    # 5.4.4 п. 2: документ по месту раньше проведённой инвентаризации — нельзя
    late = document(
        admin,
        "transfer",
        {
            "from_place": rooms["214"],
            "to_place": wh["key"],
            "date": str(date.today() - timedelta(days=1)),
        },
        [{"unit_id": monitors[0]["id"]}],
    )
    r = post(admin, late)
    assert (
        r.status_code == 400
        and "раньше проведённой «Инвентаризация" in r.json()["error"]["message"]
    )


# ---------------------------------------------------------------- R-021: остатки с моделью


def model_of(admin, type_id, name):  # type: ignore[no-untyped-def]
    r = admin.post(f"/api/catalog/types/{type_id}/models", json={"name": name})
    assert r.status_code == 201, r.text
    return next(m["id"] for m in r.json()["models"] if m["name"] == name)


def count_stock(admin, places, counted):  # type: ignore[no-untyped-def]
    """Ведомость на места, пересчёт остатков {(место, тип, модель): факт}, проведение."""
    count = admin.post("/api/inventory/counts", json={"places": places}).json()
    for (place, type_id, model_id), qty in counted.items():
        r = admin.put(
            f"/api/inventory/counts/{count['id']}/stock",
            json={"place": place, "type_id": type_id, "model_id": model_id, "counted": qty},
        )
        assert r.status_code == 204, r.text
    view = admin.get(f"/api/inventory/counts/{count['id']}").json()
    return view, admin.post(
        f"/api/inventory/counts/{count['id']}/post", json={"version": view["version"]}
    )


def stock_at(admin, place):  # type: ignore[no-untyped-def]
    items = admin.get("/api/inventory/balances", params={"place": place}).json()["items"]
    return sorted((b["model_id"] or "", b["qty"]) for b in items)


def test_r021_shortage_and_surplus_of_stock_with_model(admin) -> None:
    """R-021, 5.4.6 п. 3: недостача остатка с моделью проводится, излишек ложится на ту же
    модель, а не отдельной позицией без модели."""
    _, rooms, wh, k = setup(admin)
    gloves = k["перчатки"]["id"]
    m = model_of(admin, gloves, "Нитрил M")
    got = document(
        admin,
        "receipt",
        {"to_place": rooms["214"]},
        [{"type_id": gloves, "model_id": m, "qty": 10, "price": 520}],
    )
    assert post(admin, got).status_code == 200

    _, r = count_stock(admin, [rooms["214"]], {(rooms["214"], gloves, m): 9})
    assert r.status_code == 200, r.text
    assert stock_at(admin, rooms["214"]) == [(m, 9)]

    _, r = count_stock(admin, [rooms["214"]], {(rooms["214"], gloves, m): 11})
    assert r.status_code == 200, r.text
    assert stock_at(admin, rooms["214"]) == [(m, 11)]


def test_r021_each_model_is_counted_on_its_own(admin) -> None:
    """R-021: в одном месте две модели одного типа и остаток без модели — в ведомости три
    строки, каждая пересчитывается и выравнивается отдельно."""
    _, rooms, wh, k = setup(admin)
    gloves = k["перчатки"]["id"]
    m, s = model_of(admin, gloves, "Нитрил M"), model_of(admin, gloves, "Нитрил S")
    got = document(
        admin,
        "receipt",
        {"to_place": rooms["214"]},
        [
            {"type_id": gloves, "model_id": m, "qty": 10, "price": 520},
            {"type_id": gloves, "model_id": s, "qty": 5, "price": 540},
            {"type_id": gloves, "qty": 4, "price": 500},
        ],
    )
    assert post(admin, got).status_code == 200
    count = admin.post("/api/inventory/counts", json={"places": [rooms["214"]]}).json()
    detail = admin.get(
        f"/api/inventory/counts/{count['id']}", params={"place": rooms["214"]}
    ).json()
    rows = sorted(
        (x["model_id"] or "", x["title"], x["expected"]) for x in detail["place"]["stock"]
    )
    assert rows == sorted(
        [
            (m, "Перчатки смотровые Нитрил M", 10),
            (s, "Перчатки смотровые Нитрил S", 5),
            ("", "Перчатки смотровые", 4),
        ]
    )
    for model_id, qty in [(m, 10), (s, 3), (None, 6)]:
        r = admin.put(
            f"/api/inventory/counts/{count['id']}/stock",
            json={"place": rooms["214"], "type_id": gloves, "model_id": model_id, "counted": qty},
        )
        assert r.status_code == 204, r.text
    view = admin.get(f"/api/inventory/counts/{count['id']}").json()
    r = admin.post(f"/api/inventory/counts/{count['id']}/post", json={"version": view["version"]})
    assert view["summary"]["stock_diff"] == 2
    assert r.status_code == 200, r.text
    assert stock_at(admin, rooms["214"]) == sorted([(m, 10), (s, 3), ("", 6)])


def test_c18_count_with_stock_recount_on_the_sample(admin) -> None:
    """С18 на образце `имущество-пример.xlsx`: на складе 106 перчатки, бахилы и бумага — с
    моделью, стеллажи — без; пересчёт каждой позиции с недостачей и излишком проводится."""
    import json

    from app.modules.catalog.module import seed
    from app.samples import polyclinic
    from tests.test_inventory import SAMPLE

    with transaction() as session:
        b = polyclinic.create(session, access.actor_of(access.find(session, "admin")))
    with transaction() as session:
        seed(session)
    done = admin.post(
        "/api/inventory/import",
        data={
            "building_id": str(b["building_id"]),
            "mapping": json.dumps({"types": {}}),
            "apply": "true",
        },
        files={"file": ("имущество.xlsx", SAMPLE.read_bytes())},
    ).json()
    assert done["applied"], done.get("errors", [])[:3]
    stock = admin.get(
        "/api/inventory/balances", params={"building_id": str(b["building_id"])}
    ).json()["items"]
    store = next(x["place"] for x in stock if x["qty"] == 40)  # перчатки, склад 106
    here = [x for x in stock if x["place"] == store]
    assert len(here) == 4 and sum(1 for x in here if x["model_id"]) == 3

    # по возрастанию: стеллажи 4 — как по учёту, бахилы 25 — недостача, перчатки 40 — излишек
    counted = {
        (store, x["type_id"], x["model_id"]): x["qty"] + (0, -2, 3, 0)[i]
        for i, x in enumerate(sorted(here, key=lambda x: x["qty"]))
    }
    view, r = count_stock(admin, [store], counted)
    assert view["summary"]["stock_diff"] == 2
    assert r.status_code == 200, r.text
    assert stock_at(admin, store) == sorted(
        (model or "", qty) for (_, _, model), qty in counted.items()
    )
