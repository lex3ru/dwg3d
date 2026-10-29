"""Учёт имущества (5.4; С10, С11, С14–С17, С19): места хранения, единицы, документы,
остатки, стоимость, QR-метки, реестр, загрузка из Excel."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core import tasks
from app.core.config import config
from app.core.db import transaction
from app.modules.access import api as access
from tests.conftest import login, make_client
from tests.test_building import building_with_floor, save, two_rooms

SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "samples" / "имущество-пример.xlsx"


def statement(admin, **params: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Ведомость стоимости (5.4.5 п. 4) — фоновой задачей (R-036): запуск, обработчик, итог;
    job_id — для Excel."""
    r = admin.post("/api/inventory/cost", params=params)
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    while tasks.run_one():
        pass
    got = admin.get(f"/api/system/tasks/{job}").json()
    assert got["status"] == "done", got
    return {**got["result"], "job_id": job}


@contextmanager
def viewer_client(admin, app) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """«Просмотр» без зданий — клиент."""
    r = admin.post("/api/users", json={"login": "ivanova", "full_name": "Иванова А. П.",
                                       "role": "viewer", "password": "Temporary-1"})
    assert r.status_code == 201, r.text
    with make_client(app) as c:
        login(c, "ivanova", "Temporary-1")
        c.post("/api/auth/password", json={"current": "Temporary-1", "new": "Viewer-pass-1"})
        yield c


def confirmed_rooms(admin, building_id) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Помещения образца, совпавшие номером, но не названием, — подтверждены как есть (R-002)."""
    check = admin.post(
        "/api/inventory/import",
        data={"building_id": str(building_id)},
        files={"file": ("имущество.xlsx", SAMPLE.read_bytes())},
    ).json()
    return {r["key"]: r["place"] for r in check["rooms"] if r["confirm"]}


def kinds(admin) -> dict[str, dict]:  # type: ignore[no-untyped-def]
    layer = admin.post("/api/catalog/layers", json={"name": "Оборудование"}).json()

    def kind(name, **v):  # type: ignore[no-untyped-def]
        r = admin.post("/api/catalog/types", json={"name": name, **v})
        assert r.status_code == 201, r.text
        return r.json()

    return {
        "монитор": kind("Монитор 24″", layer_id=layer["id"], life_months=60),
        "экг": kind("Электрокардиограф", layer_id=layer["id"], life_months=84),
        "перчатки": kind("Перчатки смотровые", accounting="quantity", unit="упак."),
    }


def setup(admin):  # type: ignore[no-untyped-def]
    building, floor = building_with_floor(admin)
    rooms = {r["number"]: r["id"] for r in save(admin, floor["id"], two_rooms(), 1).json()["rooms"]}
    wh = admin.post("/api/inventory/warehouses", json={"name": "Основной"}).json()
    return building, {k: f"r:{v}" for k, v in rooms.items()}, wh, kinds(admin)


def document(admin, kind, header, lines):  # type: ignore[no-untyped-def]
    r = admin.post(
        "/api/inventory/documents", json={"kind": kind, "header": header, "lines": lines}
    )
    assert r.status_code == 201, r.text
    return r.json()


def post(admin, doc):  # type: ignore[no-untyped-def]
    return admin.post(
        f"/api/inventory/documents/{doc['id']}/post", json={"version": doc["version"]}
    )


def test_c11_receipt_gives_numbers_in_a_row_and_stock(pdf, admin) -> None:
    _, rooms, wh, k = setup(admin)
    doc = document(
        admin,
        "receipt",
        {"to_place": wh["key"], "supplier": "ООО «Медтехника»"},
        [
            {"type_id": k["монитор"]["id"], "qty": 5, "price": 14500},
            {"type_id": k["перчатки"]["id"], "qty": 20, "price": 520},
        ],
    )
    assert doc["status"] == "draft" and doc["title"] == "Приход ПР-00001"
    r = post(admin, doc)
    assert r.status_code == 200, r.text
    posted = r.json()
    assert posted["status"] == "posted"
    numbers = [u["number"] for u in posted["lines"][0]["created_units"]]
    assert numbers == ["000001", "000002", "000003", "000004", "000005"]
    # мониторы на складе — «на хранении»; перчатки — остатком
    units = admin.get("/api/inventory/units", params={"place": wh["key"]}).json()
    assert units["total"] == 5 and {u["state"] for u in units["items"]} == {"storage"}
    stock = admin.get("/api/inventory/balances", params={"place": wh["key"]}).json()["items"]
    assert [(b["type_name"], b["qty"], b["amount"]) for b in stock] == [
        ("Перчатки смотровые", 20, 10400)
    ]
    # проведённый не правится
    assert (
        admin.put(
            f"/api/inventory/documents/{doc['id']}",
            json={"version": posted["version"], "header": {"basis": "x"}},
        ).status_code
        == 409
    )
    # метки на напечатанный приход и печатная форма
    ids = [u["id"] for u in posted["lines"][0]["created_units"]]
    pdf = admin.post("/api/inventory/labels.pdf", json={"unit_ids": ids})
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    form = admin.get(f"/api/inventory/documents/{doc['id']}/print.pdf")
    assert form.content[:5] == b"%PDF-"
    # QR-метка открывает карточку
    code = admin.get(f"/api/inventory/units/{ids[0]}").json()["label_code"]
    assert admin.get(f"/api/q/{code}").json()["href"] == f"/property?card=unit:{ids[0]}"


def test_posting_is_all_or_nothing_and_transfer_issues_from_stock(admin) -> None:
    _, rooms, wh, k = setup(admin)
    post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": wh["key"]},
            [
                {"type_id": k["монитор"]["id"], "qty": 2, "price": 14500},
                {"type_id": k["перчатки"]["id"], "qty": 20, "price": 520},
            ],
        ),
    )
    monitors = admin.get("/api/inventory/units", params={"place": wh["key"]}).json()["items"]
    # перчаток не хватает — не проводится ничего, говорится какая строка и почему
    doc = document(
        admin,
        "transfer",
        {"from_place": wh["key"], "to_place": rooms["214"]},
        [
            {"unit_id": monitors[0]["id"]},
            {"type_id": k["перчатки"]["id"], "qty": 30},
        ],
    )
    r = post(admin, doc)
    assert r.status_code == 400
    assert "строка 2" in r.json()["error"]["message"] and "20" in r.json()["error"]["message"]
    assert (
        admin.get(f"/api/inventory/units/{monitors[0]['id']}").json()["place"]["key"] == wh["key"]
    )
    # исправили — проводится; со склада в кабинет — «в работе»
    doc = admin.get(f"/api/inventory/documents/{doc['id']}").json()
    doc = admin.put(
        f"/api/inventory/documents/{doc['id']}",
        json={
            "version": doc["version"],
            "header": {},
            "lines": [{"unit_id": monitors[0]["id"]}, {"type_id": k["перчатки"]["id"], "qty": 3}],
        },
    ).json()
    assert post(admin, doc).status_code == 200
    unit = admin.get(f"/api/inventory/units/{monitors[0]['id']}").json()
    assert (unit["place"]["key"], unit["state"]) == (rooms["214"], "in_use")
    assert unit["movements"][0]["to"].endswith("214 Кабинет")
    stock = {b["place"]: b["qty"] for b in admin.get("/api/inventory/balances").json()["items"]}
    assert stock == {wh["key"]: 17, rooms["214"]: 3}

    # С16: перчатки израсходованы в кабинете
    use = document(
        admin,
        "writeoff",
        {"from_place": rooms["214"], "reason": "Израсходовано"},
        [{"type_id": k["перчатки"]["id"], "qty": 3}],
    )
    assert post(admin, use).status_code == 200
    stock = {b["place"]: b["qty"] for b in admin.get("/api/inventory/balances").json()["items"]}
    assert stock == {wh["key"]: 17}

    # отмена перемещения — обратным документом; единица возвращается
    back = admin.post(f"/api/inventory/documents/{doc['id']}/cancel")
    assert back.status_code == 409 or back.status_code == 400  # перчатки уже израсходованы
    assert "израсходован" in back.json()["error"]["message"]


def test_c14_repair_and_c15_writeoff_keep_history_and_numbers(admin) -> None:
    _, rooms, wh, k = setup(admin)
    doc = post(
        admin,
        document(
            admin,
            "opening",
            {"to_place": rooms["214"]},
            [
                {
                    "type_id": k["экг"]["id"],
                    "qty": 1,
                    "price": 420000,
                    "number": "000154",
                    "commissioned_on": "2020-03-16",
                },
            ],
        ),
    ).json()
    ecg = doc["lines"][0]["created_units"][0]
    unit = admin.get(f"/api/inventory/units/{ecg['id']}").json()
    assert unit["number"] == "000154" and unit["commissioned_on"] == "2020-03-16"
    # сломался — в карточке без документа; ремонт — документом
    r = admin.patch(
        f"/api/inventory/units/{ecg['id']}",
        json={"version": unit["version"], "values": {"state": "broken"}},
    )
    assert r.status_code == 200 and r.json()["state"] == "broken"
    r = admin.patch(
        f"/api/inventory/units/{ecg['id']}",
        json={"version": r.json()["version"], "values": {"state": "repair"}},
    )
    assert r.status_code == 400
    send = document(
        admin, "repair", {"repair": "send", "contractor": "Медсервис"}, [{"unit_id": ecg["id"]}]
    )
    assert post(admin, send).status_code == 200
    assert admin.get(f"/api/inventory/units/{ecg['id']}").json()["state"] == "repair"
    back = document(
        admin, "repair", {"repair": "return", "repair_cost": 12000}, [{"unit_id": ecg["id"]}]
    )
    assert post(admin, back).status_code == 200
    unit = admin.get(f"/api/inventory/units/{ecg['id']}").json()
    assert unit["state"] == "in_use" and len(unit["movements"]) == 3
    # С15: списан с причиной — из стоимости уходит, номер больше не выдаётся
    off = document(admin, "writeoff", {}, [{"unit_id": ecg["id"], "reason": "Неремонтопригоден"}])
    assert post(admin, off).status_code == 200
    unit = admin.get(f"/api/inventory/units/{ecg['id']}").json()
    assert unit["state"] == "written_off" and unit["writeoff_reason"] == "Неремонтопригоден"
    assert unit["value"] == 0
    assert admin.get("/api/inventory/units").json()["total"] == 0
    assert admin.get("/api/inventory/units", params={"written_off": True}).json()["total"] == 1
    new = post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": wh["key"]},
            [{"type_id": k["экг"]["id"], "qty": 1, "price": 1}],
        ),
    ).json()
    assert new["lines"][0]["created_units"][0]["number"] == "000155"
    taken = document(
        admin,
        "receipt",
        {"to_place": wh["key"]},
        [{"type_id": k["экг"]["id"], "qty": 1, "price": 1, "number": "000154"}],
    )
    r = post(admin, taken)
    assert r.status_code == 400 and "000154 уже занят" in r.json()["error"]["message"]


def test_card_edits_are_history_and_roll_back(admin) -> None:
    _, rooms, wh, k = setup(admin)
    doc = post(
        admin,
        document(
            admin,
            "opening",
            {"to_place": rooms["214"]},
            [{"type_id": k["монитор"]["id"], "qty": 1, "price": 100}],
        ),
    ).json()
    uid = doc["lines"][0]["created_units"][0]["id"]
    unit = admin.get(f"/api/inventory/units/{uid}").json()
    r = admin.patch(
        f"/api/inventory/units/{uid}",
        json={
            "version": unit["version"],
            "values": {"responsible": "Иванова А. А.", "department": "Терапия"},
        },
    )
    assert r.status_code == 200
    # место меняется только документом
    bad = admin.patch(
        f"/api/inventory/units/{uid}",
        json={"version": r.json()["version"], "values": {"place": "x"}},
    )
    assert bad.status_code == 400 and "документами" in bad.json()["error"]["message"]
    change = r.json()["changes"][0]
    assert change["after"] == {"responsible": "Иванова А. А.", "department": "Терапия"}
    assert change["can_roll_back"]
    r = admin.post(f"/api/inventory/changes/{change['id']}/rollback")
    assert r.status_code == 200 and r.json()["responsible"] == ""
    history = admin.get("/api/journal", params={"ref": f"unit:{uid}"}).json()["items"]
    assert "откат правки" in history[0]["summary"]


def test_c17_search_and_viewer_sees_no_numbers_or_cost(admin, app) -> None:
    building, rooms, wh, k = setup(admin)
    post(
        admin,
        document(
            admin,
            "opening",
            {"to_place": rooms["214"]},
            [
                {
                    "type_id": k["экг"]["id"],
                    "qty": 1,
                    "price": 420000,
                    "number": "000777",
                    "responsible": "Петров П. П.",
                }
            ],
        ),
    )
    hits = admin.get("/api/search", params={"q": "000777"}).json()["items"]
    assert hits[0]["group"] == "Имущество" and "Электрокардиограф" in hits[0]["title"]
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
        items = viewer.get("/api/inventory/units").json()
        assert items["total"] == 1
        assert "number" not in items["items"][0] and "price" not in items["items"][0]
        assert "sum_price" not in items
        assert viewer.get("/api/inventory/documents").status_code == 403
        assert viewer.get("/api/search", params={"q": "000777"}).json()["items"] == []


def test_c19_cost_on_date_by_floor_and_layer(admin) -> None:
    _, rooms, wh, k = setup(admin)
    year_ago = date.today().replace(year=date.today().year - 1)
    post(
        admin,
        document(
            admin,
            "opening",
            {"to_place": rooms["214"]},
            [
                {
                    "type_id": k["монитор"]["id"],
                    "qty": 1,
                    "price": 12000,
                    "commissioned_on": year_ago.isoformat(),
                },
            ],
        ),
    )
    post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": wh["key"]},
            [{"type_id": k["перчатки"]["id"], "qty": 10, "price": 500}],
        ),
    )
    st = statement(admin, group_by="floor,layer")
    rows = {tuple(r["group"]): r for r in st["rows"]}
    monitor = rows[("2 этаж", "Оборудование")]
    # срок 60 мес., прошло 12: остаточная — 4/5
    assert monitor["initial"] == 12000 and monitor["value"] == 9600
    assert rows[("—", "без слоя")]["initial"] == 5000
    # на дату до прихода перчаток их нет
    past = statement(admin, at=(date.today() - timedelta(days=30)).isoformat(), group_by="floor")
    assert past["total"]["initial"] == 12000
    xlsx = admin.get(f"/api/inventory/cost/{st['job_id']}.xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert f"{date.today():%d.%m.%Y}.xlsx" in unquote(xlsx.headers["content-disposition"])


def test_r036_cost_statement_is_a_background_task_started_once(admin, app) -> None:
    """Ведомость стоимости по 50 000 единиц считается в фоне (8.2: «идёт в фоне»), а не в
    процессе приложения: там она держала соединение и память и под пиком роняла процессы
    (R-036, ADR-0021). Одинаковая, пока прежняя считается, — та же задача."""
    _, rooms, _, k = setup(admin)
    post(admin, document(admin, "opening", {"to_place": rooms["214"]},
                         [{"type_id": k["монитор"]["id"], "qty": 2, "price": 12000}]))
    first = admin.post("/api/inventory/cost", params={"group_by": "floor"})
    assert first.status_code == 202, first.text
    job = first.json()["job_id"]
    assert admin.post("/api/inventory/cost", params={"group_by": "floor"}).json()["job_id"] == job
    other = admin.post("/api/inventory/cost", params={"group_by": "layer"}).json()["job_id"]
    assert other != job
    assert admin.get(f"/api/system/tasks/{job}").json()["status"] == "queued"
    # итога ещё нет — и Excel нет
    assert admin.get(f"/api/inventory/cost/{job}.xlsx").status_code == 409
    while tasks.run_one():
        pass
    done = admin.get(f"/api/system/tasks/{job}").json()
    assert done["status"] == "done" and done["result"]["total"]["initial"] == 24000
    assert admin.get(f"/api/inventory/cost/{job}.xlsx").status_code == 200
    # посчитанная — не повторяется: новый запрос считает заново
    assert admin.post("/api/inventory/cost", params={"group_by": "floor"}).json()["job_id"] != job
    # ошибка в запросе — сразу, без задачи
    bad = admin.post("/api/inventory/cost", params={"group_by": "floor,цвет"})
    assert bad.status_code == 400 and "цвет" in bad.json()["error"]["message"]
    # по ключу чужой задачи Excel ведомости не отдаётся
    export = admin.post("/api/reports/exports").json()["job_id"]
    assert admin.get(f"/api/inventory/cost/{export}.xlsx").status_code == 404
    with viewer_client(admin, app) as v:
        assert v.post("/api/inventory/cost").status_code == 403
        assert v.get(f"/api/inventory/cost/{job}.xlsx").status_code == 403


def test_r036_old_cost_statements_are_purged(admin) -> None:
    """Каждое открытие «Стоимости» — задача с ведомостью в итоге (до сотни КБ на объёмах 8.1):
    посчитанные старше суток удаляются по расписанию, иначе копились бы в базе и копиях
    годами (R-036, ADR-0021). Свежие и ещё не посчитанные — остаются."""
    old, fresh = statement(admin, group_by="floor")["job_id"], statement(admin)["job_id"]
    waiting = admin.post("/api/inventory/cost", params={"group_by": "layer"}).json()["job_id"]
    with transaction() as s:
        s.execute(text("UPDATE core.job SET finished_at = now() - interval '2 days' "
                       "WHERE id = :id"), {"id": old})
    assert "inventory.purge_cost_statements" in {
        k for k, d in tasks.registered().items() if d.every}
    with transaction() as s:
        tasks.registered()["inventory.purge_cost_statements"].handler(
            s, {}, tasks.Progress(uuid.uuid4()))
    assert admin.get(f"/api/system/tasks/{old}").status_code == 404
    assert admin.get(f"/api/system/tasks/{fresh}").json()["status"] == "done"
    assert admin.get(f"/api/system/tasks/{waiting}").json()["status"] == "queued"


def test_c10_property_list_from_excel(admin) -> None:
    from app.samples import polyclinic

    with transaction() as s:
        actor = access.actor_of(access.find(s, "admin"))
        b = polyclinic.create(s, actor)
    from app.modules.catalog.module import seed

    with transaction() as s:
        seed(s)
    tpl = admin.get("/api/inventory/import/template.xlsx")
    assert tpl.content[:2] == b"PK"
    files = {"file": ("имущество.xlsx", SAMPLE.read_bytes())}
    check = admin.post(
        "/api/inventory/import", data={"building_id": str(b["building_id"])}, files=files
    ).json()
    assert check["rows"] == 57 and not check["applied"]
    names = {n["name"]: n for n in check["names"]}
    assert names["Аппарат УЗИ"]["how"] == "exact"
    assert names["Шкаф медицинский"]["how"] == "similar"
    # «Банкетка трёхместная» — это «Секция стульев трёхместная» базового каталога
    assert names["Банкетка трёхместная"]["how"] == "similar"
    assert names["Банкетка трёхместная"]["candidates"][0]["name"] == "Секция стульев трёхместная"
    corridor = next(r for r in check["rooms"] if r["room"] == "К1")
    assert corridor["how"] == "similar" and "Коридор" in corridor["place_title"]
    import json

    # кабинеты в образце условные: совпавшие номером, но не названием, подтверждаются (R-002)
    assert not check["ok"]
    mapping: dict = {
        "types": {},
        "rooms": {r["key"]: r["place"] for r in check["rooms"] if r["confirm"]},
    }

    ok = admin.post(
        "/api/inventory/import",
        data={"building_id": str(b["building_id"]), "mapping": json.dumps(mapping)},
        files=files,
    ).json()
    assert ok["ok"], ok["errors"][:3]
    done = admin.post(
        "/api/inventory/import",
        data={
            "building_id": str(b["building_id"]),
            "mapping": json.dumps(mapping),
            "apply": "true",
        },
        files=files,
    ).json()
    assert done["applied"]
    doc = admin.get(f"/api/inventory/documents/{done['document_id']}").json()
    assert doc["kind"] == "opening" and doc["status"] == "posted"
    units = admin.get("/api/inventory/units", params={"limit": 1000}).json()
    assert units["total"] == done["units"]
    numbers = {u["number"] for u in units["items"]}
    assert {"000001", "000046"} <= numbers
    # «Hikvision DS-2CD2143G2-IS» из файла — модель каталога «… 2.8 мм», новая не заводится
    tree = admin.get("/api/catalog").json()
    dome = next(t for t in tree["types"] if t["name"] == "Камера купольная")
    assert [m["name"] for m in admin.get(f"/api/catalog/types/{dome['id']}").json()["models"]] == [
        "DS-2CD2143G2-IS 2.8 мм",
        "DS-2CD2743G2-IZS 2.8–12 мм",
    ]
    # повторная загрузка того же списка — без дублей: номера заняты
    again = admin.post(
        "/api/inventory/import",
        data={"building_id": str(b["building_id"]), "mapping": json.dumps(mapping)},
        files=files,
    ).json()
    assert not again["ok"] and any("уже занят" in e["message"] for e in again["errors"])


def test_import_room_by_number_with_other_name_needs_confirmation(admin) -> None:
    """R-002: номер совпал, название другое — не «точно», без подтверждения не загрузится."""
    import json

    from app.modules.catalog.module import seed
    from app.samples import polyclinic

    with transaction() as s:
        actor = access.actor_of(access.find(s, "admin"))
        b = polyclinic.create(s, actor)
    with transaction() as s:
        seed(s)
    files = {"file": ("имущество.xlsx", SAMPLE.read_bytes())}
    data = {"building_id": str(b["building_id"])}
    check = admin.post("/api/inventory/import", data=data, files=files).json()
    rooms = {(r["floor"], r["room"]): r for r in check["rooms"]}
    # кабинеты в образце условные (ТЗ 4.6 п. 1): «101 Регистратура» на плане — «101 Холл»
    reg = rooms[("1", "101")]
    assert reg["how"] == "similar" and reg["confirm"], reg
    assert reg["place_title"].endswith("101 Холл")
    assert not check["ok"]
    assert any(
        e["row"] == reg["rows"][0] and "Регистратура" in e["message"] and "Холл" in e["message"]
        for e in check["errors"]
    ), check["errors"]
    # «Кабинет невролога» ↔ «Кабинет кардиолога»: по сходству 0,8, но это другой кабинет
    assert rooms[("2", "203")]["confirm"]
    # название совпало — «точно», подтверждать нечего
    assert rooms[("2", "201")]["how"] == "exact" and not rooms[("2", "201")]["confirm"]
    # подтверждение — явный выбор места: то же помещение или другое
    pending = [r for r in check["rooms"] if r["confirm"]]
    assert len(pending) == 13
    confirmed = {r["key"]: r["place"] for r in pending}
    ok = admin.post(
        "/api/inventory/import",
        data={**data, "mapping": json.dumps({"rooms": confirmed})},
        files=files,
    ).json()
    assert ok["ok"], ok["errors"][:3]


def test_cancel_is_a_reverse_document(admin) -> None:
    _, rooms, wh, k = setup(admin)
    received = post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": wh["key"]},
            [
                {"type_id": k["монитор"]["id"], "qty": 1, "price": 100},
                {"type_id": k["перчатки"]["id"], "qty": 5, "price": 10},
            ],
        ),
    ).json()
    uid = received["lines"][0]["created_units"][0]["id"]
    move = post(
        admin, document(admin, "transfer", {"to_place": rooms["215"]}, [{"unit_id": uid}])
    ).json()
    back = admin.post(f"/api/inventory/documents/{move['id']}/cancel")
    assert back.status_code == 200, back.text
    assert back.json()["cancels_id"] == move["id"] and back.json()["basis"].startswith("Отмена")
    assert admin.get(f"/api/inventory/documents/{move['id']}").json()["status"] == "cancelled"
    unit = admin.get(f"/api/inventory/units/{uid}").json()
    assert (unit["place"]["key"], unit["state"]) == (wh["key"], "storage")
    # отмена прихода: единица уходит, номер остаётся занятым; остаток обнуляется
    assert admin.post(f"/api/inventory/documents/{received['id']}/cancel").status_code == 200
    assert admin.get(f"/api/inventory/units/{uid}").json()["state"] == "written_off"
    assert admin.get("/api/inventory/balances").json()["items"] == []
    # отмену не отменяют
    assert admin.post(f"/api/inventory/documents/{back.json()['id']}/cancel").status_code == 409


def floor_plan(admin, rooms):  # type: ignore[no-untyped-def]
    """Этаж помещений 214 и 215, его план и версия плана."""
    floor_id = admin.get("/api/inventory/place", params={"key": rooms["214"]}).json()["place"][
        "floor_id"
    ]
    saved = admin.get(f"/api/floors/{floor_id}/plan").json()
    return floor_id, saved["plan"], saved["plan_version"]


def without_partition(admin, rooms):  # type: ignore[no-untyped-def]
    """План этажа без перегородки с одной подписью «214»: 215 убирается. Этаж, план, версия."""
    floor_id, plan, version = floor_plan(admin, rooms)
    plan["walls"] = [w for w in plan["walls"] if w["id"] != "w7"]
    plan["openings"] = [o for o in plan["openings"] if o["wall"] != "w7"]
    plan["rooms"] = [r for r in plan["rooms"] if r["number"] != "215"]
    return floor_id, plan, version


def test_r023_removed_room_hands_its_property_to_the_chosen_place(admin) -> None:
    """Убрали перегородку — 215 уходит в архив. Что в нём числится, видно до сохранения и
    переходит только в место, выбранное администратором (5.1.6 п. 3, 5.4.6, R-023)."""
    _, rooms, wh, k = setup(admin)
    received = post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": rooms["215"]},
            [
                {"type_id": k["экг"]["id"], "qty": 1, "price": 85000},
                {"type_id": k["перчатки"]["id"], "qty": 20, "price": 520},
            ],
        ),
    ).json()
    uid = received["lines"][0]["created_units"][0]["id"]
    floor_id, plan, version = without_partition(admin, rooms)
    room215, room214 = rooms["215"][2:], rooms["214"][2:]

    # предпросмотр: в убираемом 215 числятся единица и остаток
    r = save(admin, floor_id, plan, version)
    assert r.status_code == 409
    removed = r.json()["error"]["details"]["removed"]
    assert [(x["number"], x["property"]) for x in removed] == [("215", {"units": 1, "stock": 1})]

    # подтвердили, не выбрав места, — отказ, ничего не изменилось
    r = save(admin, floor_id, plan, version, confirm=True)
    assert r.status_code == 409 and r.json()["error"]["code"] == "needs_place", r.text
    assert admin.get(f"/api/inventory/units/{uid}").json()["place"]["key"] == rooms["215"]
    assert len(admin.get(f"/api/floors/{floor_id}/plan").json()["rooms"]) == 2

    # место выбрано — единица и остаток в 214, в архивном 215 ничего не числится
    r = save(admin, floor_id, plan, version, confirm=True, moves={room215: room214})
    assert r.status_code == 200, r.text
    assert [x["number"] for x in r.json()["rooms"]] == ["214"]
    unit = admin.get(f"/api/inventory/units/{uid}").json()
    assert unit["place"]["key"] == rooms["214"]
    stock = admin.get("/api/inventory/balances").json()["items"]
    assert [(s["place"], s["type_name"], s["qty"]) for s in stock] == [
        (rooms["214"], "Перчатки смотровые", 20)
    ]


def test_r023_property_goes_to_a_room_made_by_the_same_save(admin) -> None:
    """Перегородку сдвинули, подпись 215 убрали, справа подписали новую 216: имущество 215
    можно отдать ей — по подписи из редактора; место не из этого плана — ошибка (R-023)."""
    _, rooms, wh, k = setup(admin)
    received = post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": rooms["215"]},
            [{"type_id": k["экг"]["id"], "qty": 1, "price": 85000}],
        ),
    ).json()
    uid = received["lines"][0]["created_units"][0]["id"]
    floor_id, plan, version = floor_plan(admin, rooms)
    plan["nodes"]["e"], plan["nodes"]["f"] = [4500, 0], [4500, 4000]
    plan["rooms"] = [r for r in plan["rooms"] if r["number"] != "215"] + [
        {"id": "new-3", "x": 5200, "y": 2000, "number": "216", "name": "Кладовая"}
    ]
    room215 = rooms["215"][2:]

    r = save(admin, floor_id, plan, version, confirm=True, moves={room215: "nowhere"})
    assert r.status_code == 400 and r.json()["error"]["field"] == "moves", r.text

    r = save(admin, floor_id, plan, version, confirm=True, moves={room215: "new-3"})
    assert r.status_code == 200, r.text
    saved = {x["number"]: x["id"] for x in r.json()["rooms"]}
    assert set(saved) == {"214", "216"}
    assert admin.get(f"/api/inventory/units/{uid}").json()["place"]["key"] == f"r:{saved['216']}"
    summary = admin.get("/api/journal", params={"ref": f"room:{room215}"}).json()["items"][0]
    assert "убраны: 215 Кабинет (имущество — в 216 Кладовая)" in summary["summary"]


def test_r028_database_refuses_states_kinds_and_places_that_do_not_exist(admin) -> None:
    """Целостность учёта держит и база, а не только код: состояние, вид документа или события,
    нулевое движение и место не того вида база не запишет (8.3, R-028)."""
    _, rooms, wh, k = setup(admin)
    received = post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": rooms["214"]},
            [
                {"type_id": k["монитор"]["id"], "qty": 1, "price": 100},
                {"type_id": k["перчатки"]["id"], "qty": 5, "price": 10},
            ],
        ),
    ).json()
    unit = {"id": received["lines"][0]["created_units"][0]["id"]}
    doc = {"id": received["id"]}
    for sql, params in [
        ("UPDATE inventory.unit SET state = 'lost' WHERE id = :id", unit),
        ("UPDATE inventory.unit SET place = '214 Кабинет' WHERE id = :id", unit),
        ("UPDATE inventory.unit_event SET kind = 'gift' WHERE unit_id = :id", unit),
        ("UPDATE inventory.unit_event SET place = 'r:1' WHERE unit_id = :id", unit),
        ("UPDATE inventory.document SET kind = 'gift' WHERE id = :id", doc),
        ("UPDATE inventory.document SET status = 'lost' WHERE id = :id", doc),
        ("UPDATE inventory.document SET to_place = 'склад' WHERE id = :id", doc),
        ("UPDATE inventory.doc_line SET state = 'lost' WHERE document_id = :id", doc),
        ("UPDATE inventory.stock_move SET qty = 0 WHERE document_id = :id", doc),
        ("UPDATE inventory.stock_move SET place = 'x:1' WHERE document_id = :id", doc),
    ]:
        with pytest.raises(IntegrityError), transaction() as s:
            s.execute(text(sql), params)
    # черновик с местом не того вида — понятная ошибка, а не отказ базы
    r = admin.post(
        "/api/inventory/documents",
        json={"kind": "transfer", "header": {"to_place": "склад"}, "lines": []},
    )
    assert r.status_code == 400 and r.json()["error"]["field"] == "to_place", r.text


def _label_bases(monkeypatch) -> list[str]:  # type: ignore[no-untyped-def]
    """С каким адресом печатаются метки — без WeasyPrint: адрес не зависит от печати PDF."""
    from app.modules.inventory import printing

    seen: list[str] = []

    def labels_pdf(labels, settings, base_url, mode="sheet"):  # type: ignore[no-untyped-def]
        seen.append(base_url)
        return b"%PDF-"

    monkeypatch.setattr(printing, "labels_pdf", labels_pdf)
    return seen


def _set_label_url(admin, value: str):  # type: ignore[no-untyped-def]
    version = admin.get("/api/system/settings").json()["version"]
    return admin.patch(
        "/api/system/settings", json={"version": version, "values": {"label_url": value}}
    )


def test_r016_label_address_is_permanent_not_the_printing_browser(admin, monkeypatch) -> None:
    """5.4.7: ссылка в метке постоянная. Адрес — из «Настроек», по умолчанию PUBLIC_URL
    установки, а не тот, по которому администратор открыл систему (R-016)."""
    _, rooms, _, _ = setup(admin)
    room = rooms["214"]
    seen = _label_bases(monkeypatch)
    monkeypatch.setattr(config(), "public_url", "https://uchet.local/")

    def label() -> str:
        # браузер печатающего — на самом сервере, по https://localhost
        r = admin.post(
            "/api/inventory/labels.pdf", json={"room_ids": [room[2:]], "origin": "https://localhost"}
        )
        assert r.status_code == 200, r.text
        return r.headers["x-label-url"]

    assert label() == "https://uchet.local"
    # метки места из отчётов — с тем же адресом
    assert admin.get("/api/reports/labels.pdf", params={"place": room}).status_code == 200
    assert seen == ["https://uchet.local", "https://uchet.local"]
    assert admin.get("/api/inventory/labels/address").json() == {
        "url": "https://uchet.local", "source": "install"}

    # адрес из «Настроек» главнее адреса установки
    assert _set_label_url(admin, " https://inv.example:8443/ ").status_code == 200
    assert label() == "https://inv.example:8443"
    assert admin.get("/api/inventory/labels/address").json()["source"] == "settings"

    # ни настройки, ни PUBLIC_URL (разработка) — адрес, по которому открыта система
    assert _set_label_url(admin, "").status_code == 200
    monkeypatch.setattr(config(), "public_url", "")
    assert label() == "http://testserver"
    assert admin.get("/api/inventory/labels/address").json() == {
        "url": "http://testserver", "source": "request"}


def test_r016_label_address_is_checked(admin) -> None:
    assert _set_label_url(admin, "https://10.0.0.5:8443").status_code == 200
    for bad in ("uchet.local", "ftp://uchet.local", "https://uchet.local/q", "https://u.local?x=1"):
        r = _set_label_url(admin, bad)
        assert r.status_code == 400 and r.json()["error"]["field"] == "label_url", bad
