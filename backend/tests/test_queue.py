"""Build queue, floors across builds and the job.json import (PostgreSQL).

Runs before test_robustness starts the API's own worker threads; if they are
already running, the queue tests would race them and are skipped."""
import json
import shutil
import threading
import uuid

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from dwg3d import db, migrate_files, store, worker
from dwg3d.models import Floor, Job, Project

from make_sample import make

NO_EXPORT = {"export": {"ifc": False, "obj": False}}


@pytest.fixture(autouse=True)
def _no_background_workers():
    if worker._started:
        pytest.skip("фоновые воркеры API уже запущены в этом процессе")


@pytest.fixture
def data(tmp_path, monkeypatch, pg):
    monkeypatch.setenv("DWG3D_DATA", str(tmp_path / "data"))
    store.data_dir().mkdir(parents=True)
    yield tmp_path / "data"
    with db.session() as s:                      # other tests count projects / jobs
        s.execute(text("DELETE FROM projects"))


def _project(sample=None, config=None) -> str:
    pid = uuid.uuid4().hex[:12]
    d = store.project_dir(pid)
    d.mkdir(parents=True)
    if sample:
        shutil.copy(sample, d / "input.dxf")
    with db.session() as s:
        p = Project(id=pid, filename="plan.dxf", input_path="input.dxf", config=config or dict(NO_EXPORT), view={})
        s.add(p)
        s.flush()
        store.enqueue(s, p)
    return pid


def _build(pid):
    job = worker.claim()
    assert job is not None and job[1] == pid
    worker.process(*job)
    with db.session() as s:
        j = store.latest_job(s, pid)
        assert j.status == "done", j.error
        return store.public(s, store.get_project(s, pid))


def test_one_active_job_per_project(data):
    pid = _project()
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(Job(project_id=pid))
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
        rows1 = {f.candidate: f.id for f in s.scalars(select(Floor).where(Floor.project_id == pid))}
    assert set(rows1) == {f["id"] for f in j1["result"]["floors"] if f.get("bbox")}
    with db.session() as s:
        p = store.get_project(s, pid, lock=True)
        p.config = {**p.config, "geometry": {"snap_tolerance": 0.011}}
        store.enqueue(s, p)
    j2 = _build(pid)
    assert j2["build"] == 2
    with db.session() as s:
        rows2 = {f.candidate: f.id for f in s.scalars(select(Floor).where(Floor.project_id == pid))}
        assert s.scalar(text("SELECT count(*) FROM builds WHERE project_id = :p"), {"p": pid}) == 2
    assert rows2 == rows1                       # same sheets -> same floor rows
    with db.session() as s:
        listed = {x["id"]: x for x in store.list_projects(s)}
    assert listed[pid]["floors"] == len(j2["result"]["floors"]) and listed[pid]["status"] == "done"


def test_failed_build_is_reported(data):
    pid = _project()
    (store.project_dir(pid) / "input.dxf").write_text("0\nSECTION\n2\nGARBAGE\n")
    worker.process(*worker.claim())
    with db.session() as s:
        pub = store.public(s, store.get_project(s, pid))
    assert pub["status"] == "error" and pub["error"] and "trace" not in pub and pub["build"] == 0


def _file_project(root, pid, result=None, **kw):
    d = root / "jobs" / pid
    (d / "out").mkdir(parents=True)
    (d / "input.dwg").write_bytes(b"x")
    if result:
        (d / "out" / "model.glb").write_bytes(b"glTF")
    job = {"id": pid, "filename": "Планы.dwg", "input": "input.dwg", "size": 1, "status": "done",
           "stage": "done", "progress": 1.0, "message": "Готово", "config": {"edits": {}},
           "created": 1.7e9, "updated": 1.75e9, "build": 3 if result else 0, "error": None, **kw}
    if result:
        job["result"] = result
    (d / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return job


def test_migrate_files(data, tmp_path):
    sample = make(tmp_path / "sample.dxf")
    pid = _project(sample)
    result = _build(pid)["result"]
    fid = result["floors"][0]["id"]
    root = tmp_path / "old"
    view = {"name": "Корпус А", "site": {"lat": 55.0, "lon": 37.0, "azimuth": 0, "scale": 1},
            "furniture": [{"id": "a", "floor": fid, "item": "diag.mri", "at": [1, 2], "angle": 0}],
            "comments": [{"id": "k", "floor": fid, "pos": [0, 0, 0], "text": "!"}]}
    _file_project(root, "aaaaaaaaaaaa", result, view=view)
    _file_project(root, "bbbbbbbbbbbb", status="error", error="битый файл")
    _file_project(root, "cccccccccccc", result, status="running")       # interrupted
    (root / "jobs" / "junk").mkdir()
    (root / "jobs" / "junk" / "job.json").write_text("{")

    st = migrate_files.migrate(root, dry_run=True)
    assert st["imported"] == 3 and st["unreadable"] == 1 and st["furniture"] == 1 and st["pins"] == 1
    with db.session() as s:
        assert store.get_project(s, "aaaaaaaaaaaa") is None

    st = migrate_files.migrate(root)
    assert st["imported"] == 3 and st["builds"] == 2
    assert migrate_files.verify(root) == []
    with db.session() as s:
        a = store.public(s, store.get_project(s, "aaaaaaaaaaaa"))
        b = store.public(s, store.get_project(s, "bbbbbbbbbbbb"))
        c = store.public(s, store.get_project(s, "cccccccccccc"))
    assert a["build"] == 3 and a["status"] == "done" and a["result"]["floors"][0]["id"] == fid
    assert a["view"]["name"] == "Корпус А" and a["view"]["furniture"][0]["item"] == "diag.mri"
    assert a["view"]["site"]["lat"] == 55.0 and a["created"] == 1.7e9
    assert b["status"] == "error" and b["error"] == "битый файл" and "result" not in b
    assert c["status"] == "error" and c["build"] == 3 and "прервана" in c["error"]

    again = migrate_files.migrate(root)
    assert again["imported"] == 0 and again["skipped"] == 3


def test_floor_row_follows_renumbered_sheet(data):
    pid = _project()
    fl = lambda fid, bbox, name: {"id": fid, "space": "Model", "owner": None, "bbox": bbox,  # noqa: E731
                                  "offset": [0, 0], "name": name, "level": 1, "elevation": 0, "height": 3}
    with db.session() as s:
        store.sync_floors(s, pid, {"floors": [fl("c0", [0, 0, 30, 20], "1 этаж"), fl("c1", [40, 0, 70, 20], "2 этаж")]})
        before = {f.name: f.id for f in s.scalars(select(Floor).where(Floor.project_id == pid))}
        # sheets detected in another order, the second sheet removed, a new one added
        store.sync_floors(s, pid, {"floors": [fl("c5", [0, 0, 30, 20], "1 этаж"), fl("c0", [0, 90, 30, 110], "3 этаж")]})
        rows = {f.name: (f.id, f.candidate) for f in s.scalars(select(Floor).where(Floor.project_id == pid))}
    assert rows["1 этаж"] == (before["1 этаж"], "c5")
    assert rows["2 этаж"] == (before["2 этаж"], None)          # kept, waits for its sheet to come back
    assert rows["3 этаж"][1] == "c0" and rows["3 этаж"][0] not in before.values()
