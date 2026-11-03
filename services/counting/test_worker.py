"""Очередь сохраняет события после перезапуска и подтверждает только принятые (ADR-0028)."""
import uuid

from worker import Outbox


def test_outbox_survives_restart(tmp_path):
    path = tmp_path / "queue.db"
    queue = Outbox(path)
    first, second = {"id": str(uuid.uuid4())}, {"id": str(uuid.uuid4())}
    queue.put(first)
    queue.put(second)
    queue.db.close()
    restored = Outbox(path)
    assert restored.pending() == [first, second]
    restored.ack([first["id"]])
    assert restored.pending() == [second]
    restored.db.close()


def test_batch_is_atomic(tmp_path):
    import sqlite3

    import pytest

    queue = Outbox(tmp_path / "queue.db")
    event = {"id": str(uuid.uuid4())}
    with pytest.raises(sqlite3.IntegrityError):
        queue.put_many([event, event])
    assert queue.pending() == []


def test_crossings_have_opposite_directions():
    import numpy as np
    from events_line import LineParams, line_events, make_line

    def walk(y0, y1, first):
        return np.c_[np.arange(first, first + 40), np.full(40, 300),
                     np.linspace(y0, y1, 40) - 120, np.full(40, 40), np.full(40, 120)]

    tracks = {1: walk(100, 400, 20), 2: walk(400, 100, 80)}
    line = make_line("Вход", (200, 200), (440, 200), (320, 400))
    result = line_events(tracks, [line], 10, 200, 640, 480, LineParams(smooth=1))
    assert [(e["track"], e["kind"]) for e in result] == [(1, "in"), (2, "out")]
