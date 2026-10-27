"""Настройки и страница состояния (8.5 п. 4)."""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.db import transaction
from tests.test_inventory import document, post, setup


def test_settings_are_validated_versioned_and_journaled(admin) -> None:
    current = admin.get("/api/system/settings").json()
    assert {i["key"]: i["value"] for i in current["items"]}["journal_years"] == 5
    r = admin.patch("/api/system/settings", json={"version": current["version"],
                                                  "values": {"journal_years": 0}})
    assert r.status_code == 400 and r.json()["error"]["field"] == "journal_years"
    r = admin.patch("/api/system/settings", json={
        "version": current["version"],
        "values": {"journal_years": 7, "organization_name": "ГБУЗ «Поликлиника № 1»"}})
    assert r.status_code == 200
    r = admin.patch("/api/system/settings", json={"version": current["version"],
                                                  "values": {"journal_years": 8}})
    assert r.status_code == 409
    entry = admin.get("/api/journal").json()["items"][0]
    assert entry["action"] == "settings.update"
    assert entry["after"] == {"Срок хранения журнала, лет": 7,
                              "Название учреждения": "ГБУЗ «Поликлиника № 1»"}


def test_status_reports_database_worker_and_backup(admin, tmp_path, monkeypatch) -> None:
    from app.core.config import config

    monkeypatch.setattr(config(), "backup_dir", tmp_path)
    status = admin.get("/api/system/status").json()
    checks = {c["name"]: c for c in status["checks"]}
    assert checks["База данных"]["ok"] is True
    assert checks["Фоновые задачи"]["ok"] is False  # обработчик в тестах не запущен
    assert checks["Резервное копирование"]["detail"] == "Резервных копий ещё не было."

    (tmp_path / "last.json").write_text(json.dumps({
        "ok": True, "finished_at": datetime.now(UTC).isoformat(), "size": 1234,
        "message": "", "kept": {"daily": 1, "monthly": 1}}))
    status = admin.get("/api/system/status").json()
    assert {c["name"]: c["ok"] for c in status["checks"]}["Резервное копирование"] is True
    assert status["backup"]["size"] == 1234
    assert any(d["path"] == str(tmp_path) for d in status["disks"])


def test_health_needs_no_login(client) -> None:
    assert client.get("/api/health").json() == {"ok": True}


def test_search_is_empty_while_no_module_provides_results(admin) -> None:
    assert admin.get("/api/search", params={"q": "кабинет"}).json() == {"items": []}


def test_server_errors_are_human_and_logged(app, admin, caplog) -> None:
    from fastapi.testclient import TestClient

    @app.get("/api/test-crash")
    def crash() -> None:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as c:
        c.cookies = admin.cookies
        r = c.get("/api/test-crash")
    assert r.status_code == 500
    assert r.json()["error"]["message"].startswith("Внутренняя ошибка сервера.")
    assert "boom" in caplog.text


def test_r028_status_finds_property_in_places_that_are_gone(admin) -> None:
    """Место единицы — строка без внешнего ключа: страница состояния называет, сколько единиц и
    остатков числится в убранных или несуществующих местах (8.5 п. 4, R-028)."""
    _, rooms, wh, k = setup(admin)

    def check() -> dict:  # type: ignore[type-arg]
        checks = admin.get("/api/system/status").json()["checks"]
        return next(c for c in checks if c["name"] == "Места учёта")

    received = document(
        admin,
        "receipt",
        {"to_place": rooms["214"]},
        [
            {"type_id": k["монитор"]["id"], "qty": 2, "price": 100},
            {"type_id": k["перчатки"]["id"], "qty": 5, "price": 10},
        ],
    )
    assert post(admin, received).status_code == 200
    assert check()["ok"] is True

    # 214 ушло в архив с имуществом (данные до R-023), одна единица — в помещении, которого нет
    with transaction() as s:
        s.execute(
            text("UPDATE building.room SET archived_at = now() WHERE id = :id"),
            {"id": rooms["214"][2:]},
        )
        s.execute(
            text(
                "UPDATE inventory.unit SET place = :gone WHERE id = "
                "(SELECT id FROM inventory.unit ORDER BY number LIMIT 1)"
            ),
            {"gone": f"r:{uuid.uuid4()}"},
        )
    found = check()
    assert found["ok"] is False
    assert "единиц: 2" in found["detail"] and "позиций остатков: 1" in found["detail"], found
    assert admin.get("/api/system/status").json()["ok"] is False
