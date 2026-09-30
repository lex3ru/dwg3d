"""Build queue and floors across builds (PostgreSQL).

The API's own worker threads (if another test started them) are paused, so
the tests take jobs from the queue themselves."""
import shutil
import threading
import uuid

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from conftest import add_drawing
from dwg3d import db, files, store, worker
from dwg3d.models import Floor, Job

from make_sample import make

NO_EXPORT = {"export": {"ifc": False, "obj": False}}


@pytest.fixture(autouse=True)
def _no_background_workers():
    with worker.paused():
        yield


@pytest.fixture
def data(tmp_path, monkeypatch, pg):
    monkeypatch.setenv("DWG3D_DATA", str(tmp_path / "data"))
    (files.data_root() / "jobs").mkdir(parents=True)
    yield tmp_path / "data"
    with db.session() as s:                      # other tests count projects / jobs
        s.execute(text("DELETE FROM projects"))


def _project(sample=None, config=None) -> str:
    pid = uuid.uuid4().hex[:12]
    d = files.store().workdir(pid)
    d.mkdir(parents=True)
    if sample:
        shutil.copy(sample, d / "input.dxf")
    with db.session() as s:
        p = add_drawing(s, pid, filename="plan.dxf", config=config or dict(NO_EXPORT))
        store.enqueue(s, p)
    return pid


def _build(pid):
    job = worker.claim()
    assert job is not None and job[1] == pid
    worker.process(*job)
    with db.session() as s:
        j = store.latest_job(s, pid)
        assert j.status == "done", j.error
        return store.public(s, store.get_drawing(s, pid))


def test_one_active_job_per_project(data):
    pid = _project()
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(Job(drawing_id=pid))
    with db.session() as s:
        assert store.has_active(s, pid)


def test_concurrent_claims_get_different_jobs(data):
    pids = {_project() for _ in range(4)}
    got, barrier = [], threading.Barrier(4)

    def take():
        barrier.wait()
        got.append(worker.claim())

    threads = [threading.Thread(target=take) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert {g[1] for g in got if g} == pids and len({g[0] for g in got}) == 4
    assert worker.claim() is None


def test_stale_running_job_is_failed(data):
    pid = _project()
    jid, _ = worker.claim()
    with db.session() as s:
        assert store.fail_stale_jobs(s, 60) == 0
        s.execute(update(Job).where(Job.id == jid).values(heartbeat_at=text("now() - interval '10 minutes'")))
        assert store.fail_stale_jobs(s, 60) == 1
        j = s.get(Job, jid)
        assert j.status == "error" and "перезапущен" in j.error
        assert not store.has_active(s, pid)


def test_build_keeps_floor_rows_across_rebuilds(data, tmp_path):
    sample = make(tmp_path / "sample.dxf")
    pid = _project(sample)
    j1 = _build(pid)
    assert j1["build"] == 1 and j1["status"] == "done" and j1["model_url"].endswith("?v=1")
    with db.session() as s:
        rows1 = {f.candidate: f.id for f in s.scalars(select(Floor).where(Floor.drawing_id == pid))}
    assert set(rows1) == {f["id"] for f in j1["result"]["floors"] if f.get("bbox")}
    with db.session() as s:
        p = store.get_drawing(s, pid, lock=True)
        p.config = {**p.config, "geometry": {"snap_tolerance": 0.011}}
        store.enqueue(s, p)
    j2 = _build(pid)
    assert j2["build"] == 2
    with db.session() as s:
        rows2 = {f.candidate: f.id for f in s.scalars(select(Floor).where(Floor.drawing_id == pid))}
        assert s.scalar(text("SELECT count(*) FROM builds WHERE drawing_id = :p"), {"p": pid}) == 2
    assert rows2 == rows1                       # same sheets -> same floor rows
    with db.session() as s:
        listed = {x["id"]: x for x in store.list_drawings(s)}
    assert listed[pid]["floors"] == len(j2["result"]["floors"]) and listed[pid]["status"] == "done"


def test_failed_build_is_reported(data):
    pid = _project()
    (files.store().workdir(pid) / "input.dxf").write_text("0\nSECTION\n2\nGARBAGE\n")
    worker.process(*worker.claim())
    with db.session() as s:
        pub = store.public(s, store.get_drawing(s, pid))
    assert pub["status"] == "error" and pub["error"] and "trace" not in pub and pub["build"] == 0


def test_floor_row_follows_renumbered_sheet(data):
    pid = _project()
    fl = lambda fid, bbox, name: {"id": fid, "space": "Model", "owner": None, "bbox": bbox,  # noqa: E731
                                  "offset": [0, 0], "name": name, "level": 1, "elevation": 0, "height": 3}
    with db.session() as s:
        store.sync_floors(s, pid, {"floors": [fl("c0", [0, 0, 30, 20], "1 этаж"), fl("c1", [40, 0, 70, 20], "2 этаж")]})
        before = {f.name: f.id for f in s.scalars(select(Floor).where(Floor.drawing_id == pid))}
        # sheets detected in another order, the second sheet removed, a new one added
        store.sync_floors(s, pid, {"floors": [fl("c5", [0, 0, 30, 20], "1 этаж"), fl("c0", [0, 90, 30, 110], "3 этаж")]})
        rows = {f.name: (f.id, f.candidate) for f in s.scalars(select(Floor).where(Floor.drawing_id == pid))}
    assert rows["1 этаж"] == (before["1 этаж"], "c5")
    assert rows["2 этаж"] == (before["2 этаж"], None)          # kept, waits for its sheet to come back
    assert rows["3 этаж"][1] == "c0" and rows["3 этаж"][0] not in before.values()
