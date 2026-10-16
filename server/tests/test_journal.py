"""Журнал (5.7.3): только добавление, ленты, срок хранения."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import tasks
from app.core.db import transaction
from app.modules.journal import api as journal


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
