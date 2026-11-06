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


def test_confirmed_passages():
    import numpy as np
    from events_line import LineParams, line_events, make_line

    line = make_line("Вход", (100, 200), (300, 200), (200, 300))

    def walk(xs, ys, start=0):
        return np.array([(start+i, x-10, y-100, 20, 100) for i, (x, y) in enumerate(zip(xs, ys))])

    def directions(tracks):
        events = line_events(tracks, [line], 15, 120, 640, 480,
                             LineParams(band=.03, min_track_s=.4, use_terminal=False))
        return [(e["track"], e["kind"]) for e in events]

    # Встречные люди у одного порога, проходы разделены одной секундой.
    assert directions({1: walk([160]*16, np.linspace(230, 170, 16)),
                       2: walk([250]*16, np.linspace(170, 230, 16), 15)}) == [(1, "out"), (2, "in")]
    # Подтверждение уже за концом отрезка, пересечение внутри него.
    diagonal = walk([190, 220, 245, 265, 280, 295, 340, 360],
                    [178, 183, 188, 193, 198, 201, 205, 210])
    assert directions({1: diagonal}) == [(1, "in")]
    outside = diagonal.copy()
    outside[:, 1] += 120
    assert directions({1: outside}) == []
    assert directions({1: walk([180]*9, [185, 190, 195, 198, 201, 198, 195, 190, 185])}) == []
    # Оба подтверждённых перехода одного человека, даже при быстром возвращении.
    assert directions({1: walk([180]*32, list(np.linspace(170, 230, 16)) +
                               list(np.linspace(230, 170, 16)))}) == [(1, "in"), (1, "out")]
