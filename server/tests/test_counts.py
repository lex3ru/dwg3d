"""Инвентаризация (5.4.6, С18): ведомость этажа, обход со сканом меток и ручными отметками,
вещь без метки, пересчёт остатков, проведение расхождений, акт; запрет документов задним
числом раньше проведённой инвентаризации (5.4.4 п. 2)."""

from datetime import date, timedelta

from tests.test_inventory import document, post, setup


def floor_id(admin, rooms):  # type: ignore[no-untyped-def]
    key = rooms["214"]
    return admin.get("/api/inventory/place", params={"key": key}).json()["place"]["floor_id"]


def unit(admin, unit_id):  # type: ignore[no-untyped-def]
    return admin.get(f"/api/inventory/units/{unit_id}").json()


def test_c18_count_by_scanning_and_posting_discrepancies(admin) -> None:
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
