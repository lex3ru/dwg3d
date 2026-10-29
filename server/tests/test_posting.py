"""Проведение документов учёта при одновременной работе и задним числом (5.4.4, 8.3 п. 2;
находки R-019, R-020, R-001, R-022 ревью 21.10.2026). Гонка — два сеанса базы в двух потоках:
первый выполняет своё и держит транзакцию открытой, второй в это время выполняет своё. Так
второй читает данные, которые первый ещё не зафиксировал, — не 1 раз из 3, а каждый раз."""

import io
import json
import threading
import time
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import psycopg.errors as pg
import pytest
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.actor import Actor
from app.core.db import transaction
from app.core.errors import AppError
from app.modules.access import api as access
from app.modules.inventory import documents, units
from app.modules.inventory.excel import HEAD
from app.modules.inventory.models import StockMove
from tests.test_inventory import document, post, setup, statement

HOLD = 0.5  # сколько первый сеанс держит транзакцию после своего действия, с


def actor() -> Actor:
    with transaction() as s:
        return access.actor_of(access.find(s, "admin"))  # type: ignore[arg-type]


def race(first: Callable[[Session], Any], second: Callable[[Session], Any]) -> list[Any]:
    """Итог каждого сеанса: результат действия или исключение."""
    done = threading.Event()
    out: list[Any] = [None, None]

    def run(i: int, action: Callable[[Session], Any]) -> None:
        try:
            with transaction() as s:
                out[i] = action(s)
                if i == 0:
                    done.set()
                    time.sleep(HOLD)
        except Exception as e:  # noqa: BLE001 — итог гонки, а не сбой теста
            out[i] = e
        finally:
            done.set()

    t = threading.Thread(target=run, args=(0, first))
    t.start()
    done.wait()
    run(1, second)
    t.join()
    return out


def outcome(results: list[Any]) -> list[Any]:
    """Код ошибки для отказов, имя класса для «внутренней ошибки», иначе результат."""
    return [
        r.code if isinstance(r, AppError) else type(r).__name__ if isinstance(r, Exception) else r
        for r in results
    ]


def posting(who: Actor, doc: dict) -> Callable[[Session], str]:  # type: ignore[type-arg]
    return lambda s: documents.post(s, who, uuid.UUID(doc["id"]), doc["version"]).status


def stock(place: str, type_id: str) -> tuple[float, float]:
    """Остаток позиции как есть в базе — вместе с отрицательным, которого «Склад» не покажет."""
    with transaction() as s:
        qty, amount = s.execute(
            select(func.coalesce(func.sum(StockMove.qty), 0),
                   func.coalesce(func.sum(StockMove.amount), 0))
            .where(StockMove.place == place, StockMove.type_id == uuid.UUID(type_id))
        ).one()
    return float(qty), float(amount)


def day(ago: int) -> str:
    return (date.today() - timedelta(days=ago)).isoformat()


def ru(ago: int) -> str:
    return f"{date.today() - timedelta(days=ago):%d.%m.%Y}"


# ---------------------------------------------------------------- R-019 одновременное проведение


def test_r019_two_writeoffs_at_once_do_not_overdraw_stock(admin) -> None:
    _, _, wh, k = setup(admin)
    gloves, who = k["перчатки"]["id"], actor()
    receipt = document(
        admin, "receipt", {"to_place": wh["key"]}, [{"type_id": gloves, "qty": 10, "price": 100}]
    )
    assert post(admin, receipt).status_code == 200
    a, b = (
        document(admin, "writeoff", {"from_place": wh["key"]}, [{"type_id": gloves, "qty": 8}])
        for _ in range(2)
    )
    assert outcome(race(posting(who, a), posting(who, b))) == ["posted", "not_posted"]
    assert stock(wh["key"], gloves) == (2, 200)


def test_r019_same_draft_posted_twice_at_once_counts_once(admin) -> None:
    _, _, wh, k = setup(admin)
    gloves, who = k["перчатки"]["id"], actor()
    doc = document(
        admin, "receipt", {"to_place": wh["key"]}, [{"type_id": gloves, "qty": 5, "price": 100}]
    )
    assert outcome(race(posting(who, doc), posting(who, doc))) == ["posted", "conflict"]
    assert stock(wh["key"], gloves) == (5, 500)


def test_r019_cancel_and_writeoff_at_once_do_not_overdraw_stock(admin) -> None:
    _, _, wh, k = setup(admin)
    gloves, who = k["перчатки"]["id"], actor()
    receipt = post(
        admin,
        document(
            admin, "receipt", {"to_place": wh["key"]}, [{"type_id": gloves, "qty": 5, "price": 100}]
        ),
    ).json()
    out = document(admin, "writeoff", {"from_place": wh["key"]}, [{"type_id": gloves, "qty": 5}])
    results = race(
        lambda s: documents.cancel(s, who, uuid.UUID(receipt["id"])).status, posting(who, out)
    )
    assert outcome(results) == ["posted", "not_posted"]
    assert stock(wh["key"], gloves) == (0, 0)


def test_r019_draft_edit_while_posting_is_refused(admin) -> None:
    _, _, wh, k = setup(admin)
    gloves, who = k["перчатки"]["id"], actor()
    doc = document(
        admin, "receipt", {"to_place": wh["key"]}, [{"type_id": gloves, "qty": 5, "price": 100}]
    )
    more = [{"type_id": gloves, "qty": 50, "price": 100}]
    results = race(
        posting(who, doc),
        lambda s: documents.update_document(
            s, who, uuid.UUID(doc["id"]), doc["version"], {}, more
        ).status,
    )
    assert outcome(results) == ["posted", "conflict"]
    # проведённый документ показывает те строки, по которым проведён
    view = admin.get(f"/api/inventory/documents/{doc['id']}").json()
    assert [line["qty"] for line in view["lines"]] == [5]
    assert stock(wh["key"], gloves) == (5, 500)


def test_r019_card_edit_while_posting_does_not_overwrite_the_document(admin) -> None:
    _, rooms, _, k = setup(admin)
    who = actor()
    got = post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": rooms["214"]},
            [{"type_id": k["экг"]["id"], "qty": 1, "price": 90000}],
        ),
    ).json()
    uid = got["lines"][0]["created_units"][0]["id"]
    version = admin.get(f"/api/inventory/units/{uid}").json()["version"]
    repair = document(admin, "repair", {"contractor": "Медтехсервис"}, [{"unit_id": uid}])
    results = race(
        posting(who, repair),
        lambda s: units.update_unit(s, who, uuid.UUID(uid), {"state": "broken"}, version).state,
    )
    assert outcome(results) == ["posted", "stale"]
    assert admin.get(f"/api/inventory/units/{uid}").json()["state"] == "repair"


# ---------------------------------------------------------------- R-022 номера и неверный ввод


def test_r022_two_receipts_at_once_get_different_numbers(admin) -> None:
    _, _, wh, k = setup(admin)
    who = actor()
    a, b = (
        document(
            admin, "receipt", {"to_place": wh["key"]},
            [{"type_id": k["монитор"]["id"], "qty": 3, "price": 14500}],
        )
        for _ in range(2)
    )
    assert outcome(race(posting(who, a), posting(who, b))) == ["posted", "posted"]
    numbers = [u["number"] for u in admin.get("/api/inventory/units").json()["items"]]
    assert len(numbers) == len(set(numbers)) == 6


def test_r022_two_drafts_at_once_get_different_numbers(admin) -> None:
    who = actor()

    def create(s: Session) -> int:
        return documents.create_document(s, who, "receipt", {}).number

    assert set(outcome(race(create, create))) == {1, 2}


def test_r022_bad_line_value_is_a_message_not_a_crash(admin) -> None:
    _, _, wh, k = setup(admin)
    gloves, monitor = k["перчатки"]["id"], k["монитор"]["id"]
    good = {"type_id": gloves, "qty": 1, "price": 100}
    for bad in (
        {"unit_id": "не-идентификатор"},
        {"type_id": "123"},
        {"type_id": gloves, "qty": "много", "price": 100},
        {"type_id": gloves, "qty": "NaN", "price": 100},
        {"type_id": gloves, "qty": 1e20, "price": 100},
        {"type_id": gloves, "qty": 1, "price": "дёшево"},
        {"type_id": gloves, "qty": 1, "price": 100, "to_place": 5},
        {"type_id": gloves, "qty": 1, "price": 100, "to_place": "w:" + "0" * 60},
        {"type_id": monitor, "qty": 1, "price": 100, "number": "1" * 41},
        {"type_id": monitor, "qty": 1, "price": 100, "state": ["в работе"]},
        {"type_id": monitor, "qty": 1, "price": 100, "life_months": "год"},
        {"type_id": monitor, "qty": 1, "price": 100, "life_months": 5000},
        {"type_id": monitor, "qty": 1, "price": 100, "values": "нет"},
    ):
        r = admin.post(
            "/api/inventory/documents",
            json={"kind": "receipt", "header": {"to_place": wh["key"]}, "lines": [good, bad]},
        )
        assert r.status_code == 400, (bad, r.text)
        assert "строка 2" in r.json()["error"]["message"].lower(), (bad, r.text)
    assert admin.get("/api/inventory/documents").json()["items"] == []


def test_r022_bad_header_value_is_a_message_not_a_crash(admin) -> None:
    for kind, header in (
        ("repair", {"repair_cost": "дорого"}),
        ("repair", {"repair_cost": "Infinity"}),
        ("transfer", {"to_place": 5}),
        ("transfer", {"from_place": "w:" + "0" * 60}),
    ):
        r = admin.post("/api/inventory/documents", json={"kind": kind, "header": header})
        assert r.status_code == 400, (header, r.text)
        assert r.json()["error"]["field"] == next(iter(header)), r.text
    # длинный текст обрезается по столбцу, как и раньше, а не роняет запрос
    r = admin.post(
        "/api/inventory/documents", json={"kind": "receipt", "header": {"supplier": "А" * 250}}
    )
    assert r.status_code == 201 and len(r.json()["supplier"]) == 200, r.text


@pytest.mark.parametrize(
    "error",
    [
        IntegrityError("INSERT …", {}, pg.UniqueViolation("номер уже занят")),
        OperationalError("UPDATE …", {}, pg.DeadlockDetected("взаимоблокировка")),
        StaleDataError("строку уже удалили"),
    ],
    ids=["unique", "deadlock", "stale"],
)
def test_r022_conflict_in_the_database_is_409_not_500(admin, monkeypatch, error) -> None:
    """Если одновременная работа всё же упёрлась в базу — «обновите и повторите» (ADR-0003)."""

    def conflict(*_: object, **__: object) -> None:
        raise error

    monkeypatch.setattr(documents, "create_document", conflict)
    r = admin.post("/api/inventory/documents", json={"kind": "receipt", "header": {}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale", r.text


def test_other_database_error_stays_internal(admin, monkeypatch) -> None:
    def broken(*_: object, **__: object) -> None:
        raise IntegrityError("INSERT …", {}, pg.NotNullViolation("пусто"))

    monkeypatch.setattr(documents, "create_document", broken)
    with pytest.raises(IntegrityError):
        admin.post("/api/inventory/documents", json={"kind": "receipt", "header": {}})


# ---------------------------------------------------------------- R-020 задним числом


def monitor_received(admin, place: str, k: dict, ago: int) -> str:  # type: ignore[no-untyped-def,type-arg]
    got = post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": place, "date": day(ago)},
            [{"type_id": k["монитор"]["id"], "qty": 1, "price": 14500}],
        ),
    ).json()
    return got["lines"][0]["created_units"][0]["id"]


def moved(admin, uid: str, to: str, ago: int) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return document(admin, "transfer", {"to_place": to, "date": day(ago)}, [{"unit_id": uid}])


def where(admin, ago: int) -> list[str]:  # type: ignore[no-untyped-def]
    """Где числится имущество на дату — по «Стоимости на дату» с разбивкой по местам."""
    st = statement(admin, at=day(ago), group_by="place")
    return [r["group"][0] for r in st["rows"]]


def test_r020_unit_document_cannot_predate_its_last_event(admin) -> None:
    _, rooms, wh, k = setup(admin)
    uid = monitor_received(admin, wh["key"], k, 14)
    t1 = moved(admin, uid, rooms["214"], 4)
    assert post(admin, t1).status_code == 200
    # забытое перемещение задним числом — раньше Т1: история по единице разошлась бы
    r = post(admin, moved(admin, uid, rooms["215"], 6))
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_posted", r.text
    message = r.json()["error"]["message"]
    assert t1["title"] in message and ru(4) in message, message
    # карточка и «Стоимость на дату» говорят одно и то же
    assert admin.get(f"/api/inventory/units/{uid}").json()["place"]["key"] == rooms["214"]
    assert len(where(admin, 0)) == 1 and "214" in where(admin, 0)[0]
    assert len(where(admin, 5)) == 1 and "Основной" in where(admin, 5)[0]
    # в тот же день, что и последнее событие, — можно
    assert post(admin, moved(admin, uid, rooms["215"], 4)).status_code == 200
    # отмена Т1 после Т3 по той же единице — нельзя
    r = admin.post(f"/api/inventory/documents/{t1['id']}/cancel")
    assert r.status_code == 400 and r.json()["error"]["code"] == "cannot_cancel", r.text


def test_r020_forgotten_document_goes_in_after_cancelling_later_ones(admin) -> None:
    """Путь из ADR-0004: отменить более поздний документ, провести забытый, оформить отменённый
    заново. Обратный документ датирован сегодня, но правило его не учитывает: отменённый
    документ и обратный к нему взаимно гасятся."""
    _, rooms, wh, k = setup(admin)
    uid = monitor_received(admin, wh["key"], k, 14)
    t1 = moved(admin, uid, rooms["214"], 4)
    assert post(admin, t1).status_code == 200
    forgotten = moved(admin, uid, rooms["215"], 6)
    assert post(admin, forgotten).status_code == 400
    assert admin.post(f"/api/inventory/documents/{t1['id']}/cancel").status_code == 200
    r = post(admin, forgotten)
    assert r.status_code == 200, r.text
    again = moved(admin, uid, rooms["214"], 4)
    assert post(admin, again).status_code == 200
    # карточка и «Стоимость на дату» — одна история: склад → 215 (−6 дн.) → 214 (−4 дн.)
    assert admin.get(f"/api/inventory/units/{uid}").json()["place"]["key"] == rooms["214"]
    for ago, room in ((10, "Основной"), (5, "215"), (3, "214"), (0, "214")):
        places = where(admin, ago)
        assert len(places) == 1 and room in places[0], (ago, places)
    # отменённое не в счёт, а «Т1 заново» — в счёт: раньше него по единице снова нельзя
    r = post(admin, moved(admin, uid, rooms["215"], 8))
    assert r.status_code == 400 and again["title"] in r.json()["error"]["message"], r.text


def test_r020_transfer_cannot_predate_the_receipt_of_the_unit(admin) -> None:
    _, rooms, wh, k = setup(admin)
    got = post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": wh["key"], "date": day(4)},
            [{"type_id": k["монитор"]["id"], "qty": 1, "price": 14500}],
        ),
    ).json()
    uid = got["lines"][0]["created_units"][0]["id"]
    early = document(
        admin, "transfer", {"to_place": rooms["214"], "date": day(10)}, [{"unit_id": uid}]
    )
    r = post(admin, early)
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_posted", r.text


def test_r020_backdated_writeoff_keeps_stock_on_every_date(admin) -> None:
    _, _, wh, k = setup(admin)
    gloves = k["перчатки"]["id"]

    def doc(kind: str, ago: int, qty: int) -> Any:
        place = {"to_place" if kind == "receipt" else "from_place": wh["key"], "date": day(ago)}
        return post(
            admin, document(admin, kind, place, [{"type_id": gloves, "qty": qty, "price": 100}])
        )

    assert doc("receipt", 10, 10).status_code == 200
    assert doc("writeoff", 4, 8).status_code == 200
    assert doc("receipt", 2, 10).status_code == 200
    # на дату расхода (−6 дн.) остаток 10 и сейчас 12, но на −4 дн. стало бы 10 − 5 − 8 = −3
    r = doc("writeoff", 6, 5)
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_posted", r.text
    # остаток на количество — мягче, чем единица: забытый приход задним числом проводится
    assert doc("receipt", 8, 3).status_code == 200
    assert doc("writeoff", 6, 5).status_code == 200

    def on(ago: int) -> float:
        items = admin.get(
            "/api/inventory/balances", params={"place": wh["key"], "at": day(ago)}
        ).json()["items"]
        return sum(i["qty"] for i in items)

    assert [on(a) for a in (10, 8, 6, 4, 2)] == [10, 13, 8, 0, 10]


# ---------------------------------------------------------------- R-001 номера в документе


def test_r001_number_given_below_is_not_taken_by_a_line_above(admin) -> None:
    _, _, wh, k = setup(admin)
    monitor = k["монитор"]["id"]
    got = post(
        admin,
        document(
            admin,
            "receipt",
            {"to_place": wh["key"]},
            [
                {"type_id": monitor, "qty": 1, "price": 14500},
                {"type_id": monitor, "qty": 1, "price": 14500, "number": "000001"},
            ],
        ),
    )
    assert got.status_code == 200, got.text
    numbers = [line["created_units"][0]["number"] for line in got.json()["lines"]]
    assert numbers == ["000002", "000001"]


def test_r001_excel_check_and_upload_agree_on_numbers(admin) -> None:
    building, _, _, k = setup(admin)
    wb = Workbook()
    ws = wb.active
    ws.title = "Имущество"
    ws.append(HEAD)
    row = {
        "Наименование": k["монитор"]["name"],
        "Вид учёта": "поштучно",
        "Количество": 1,
        "Ед. изм.": "шт.",
        "Этаж": "2",
        "Помещение": "214",
        "Состояние": "в работе",
        "Цена за ед., ₽": 14500,
        "Дата ввода": date.today().strftime("%d.%m.%Y"),
    }
    ws.append([row.get(h) for h in HEAD])
    ws.append([{**row, "Инвентарный номер": "000001"}.get(h) for h in HEAD])
    out = io.BytesIO()
    wb.save(out)
    files = {"file": ("имущество.xlsx", out.getvalue())}
    form = {"building_id": building["id"], "mapping": json.dumps({"types": {}})}
    check = admin.post("/api/inventory/import", data=form, files=files).json()
    assert check["ok"], check["errors"]
    done = admin.post("/api/inventory/import", data={**form, "apply": "true"}, files=files)
    assert done.status_code == 200 and done.json()["applied"], done.text
    numbers = {u["number"] for u in admin.get("/api/inventory/units").json()["items"]}
    assert numbers == {"000001", "000002"}
