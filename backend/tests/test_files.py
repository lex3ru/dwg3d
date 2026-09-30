"""File store in S3 mode (an S3-compatible server; skipped without one):
working copies, manifests, the whole API flow on object storage.

  docker compose up -d s3 && uv run pytest tests/test_files.py
"""
import os
import time
import uuid

import pytest

from dwg3d import files

from make_sample import make

ENDPOINT = os.environ.get("DWG3D_TEST_S3_ENDPOINT", "http://127.0.0.1:9000")
KEYS = {"DWG3D_S3_ACCESS_KEY": os.environ.get("DWG3D_TEST_S3_ACCESS_KEY", "dwg3d"),
        "DWG3D_S3_SECRET_KEY": os.environ.get("DWG3D_TEST_S3_SECRET_KEY", "dwg3d-secret")}


@pytest.fixture
def s3(tmp_path, monkeypatch):
    """S3 mode with a scratch bucket (removed afterwards)."""
    monkeypatch.setenv("DWG3D_S3_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("DWG3D_S3_BUCKET", f"dwg3d-test-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("DWG3D_DATA", str(tmp_path / "data"))
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    files.reset()
    st = files.store()
    try:
        st.list("")
    except Exception as ex:
        files.reset()
        pytest.skip(f"S3 недоступно ({ENDPOINT}): {ex.__class__.__name__}")
    yield st
    st.delete_prefix("")
    st.client.delete_bucket(Bucket=st.bucket)
    files.reset()


def test_put_get_list_delete(s3, tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"x" * 3000)
    s3.put_file("drawings/d1/input.dwg", src)
    s3.put_bytes("drawings/d1/out/metadata.json", b"{}", "application/json")
    assert s3.size("drawings/d1/input.dwg") == 3000 and s3.size("drawings/d1/nope") is None
    assert s3.get_bytes("drawings/d1/out/metadata.json") == b"{}" and s3.get_bytes("nope") is None
    assert b"".join(s3.stream("drawings/d1/input.dwg")) == b"x" * 3000
    assert set(s3.list("drawings/d1/")) == {"drawings/d1/input.dwg", "drawings/d1/out/metadata.json"}
    assert not s3.download("drawings/d1/nope", tmp_path / "n") and not (tmp_path / "n").exists()
    s3.delete_prefix("drawings/d1/")
    assert s3.list("drawings/") == {}


def test_working_copies_follow_the_manifest(s3, tmp_path, monkeypatch):
    s3.put_bytes("drawings/d/input.dxf", b"dxf")
    # worker A builds
    monkeypatch.setenv("DWG3D_SCRATCH", str(tmp_path / "a"))
    wd = s3.pull("d", paths=["input.dxf"], trees=["out"])
    assert (wd / "input.dxf").read_bytes() == b"dxf"
    (wd / "out" / "plans").mkdir(parents=True)
    (wd / "out" / "model.glb").write_bytes(b"glb1")
    (wd / "out" / "plans" / "floor_c0.json").write_text("{}")
    s3.push("d", "out")
    assert s3.get_bytes("drawings/d/out/model.glb") == b"glb1"
    # worker B (another host) rebuilds: gets A's files, changes one, drops one
    monkeypatch.setenv("DWG3D_SCRATCH", str(tmp_path / "b"))
    wd_b = s3.pull("d", paths=["input.dxf"], trees=["out"])
    assert (wd_b / "out" / "plans" / "floor_c0.json").exists()
    (wd_b / "out" / "model.glb").write_bytes(b"glb2")
    (wd_b / "out" / "plans" / "floor_c0.json").unlink()
    s3.put_bytes("drawings/d/out/debug/overlay.png", b"png")        # rendered on demand, not in the manifest
    s3.push("d", "out")
    assert s3.get_bytes("drawings/d/out/model.glb") == b"glb2"
    assert set(s3.list("drawings/d/out/")) == {"drawings/d/out/model.glb", "drawings/d/out/.manifest.json"}
    # worker A again: its stale copy is brought up to date
    monkeypatch.setenv("DWG3D_SCRATCH", str(tmp_path / "a"))
    wd = s3.pull("d", paths=["input.dxf"], trees=["out"])
    assert (wd / "out" / "model.glb").read_bytes() == b"glb2" and not (wd / "out" / "plans" / "floor_c0.json").exists()


def test_api_on_s3(s3, pg, tmp_path):
    """Upload, build, files, detail model, export and a catalog model — all through S3."""
    from fastapi.testclient import TestClient
    from dwg3d import api

    c = TestClient(api.app)
    sample = make(tmp_path / "sample.dxf")
    pid = c.post("/api/projects", json={"name": "S3"}).json()["id"]
    did = c.post(f"/api/projects/{pid}/drawings", files={"file": ("plan.dxf", sample.read_bytes())}).json()["id"]
    assert s3.size(files.drawing_key(did, "input.dxf")) == sample.stat().st_size
    t = time.time()
    while (d := c.get(f"/api/drawings/{did}").json())["status"] not in ("done", "error"):
        assert time.time() - t < 120
        time.sleep(0.2)
    assert d["status"] == "done", d.get("error")
    glb = c.get(d["model_url"])
    assert glb.status_code == 200 and glb.content[:4] == b"glTF"
    assert glb.content == s3.get_bytes(files.drawing_key(did, "out/model.glb"))
    fid = d["result"]["floors"][0]["id"]
    assert c.get(f"/api/drawings/{did}/files/plans/floor_{fid}.json").json()["walls"]
    png = c.get(f"/api/drawings/{did}/files/debug/floor_{fid}.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert s3.size(files.drawing_key(did, f"out/debug/floor_{fid}.png"))
    for bad in ("../input.dxf", "cache/debug_index.json", ".manifest.json", "nope.glb"):
        assert c.get(f"/api/drawings/{did}/files/{bad}").status_code == 404, bad

    assert c.post(f"/api/drawings/{did}/detail", files={"file": ("f.glb", glb.content)}).status_code == 200
    assert c.get(f"/api/drawings/{did}/detail.glb").content == glb.content

    r = c.post(f"/api/drawings/{did}/rebuild", json={"edits": {fid: {"rooms": [{"at": [5, 5], "name": "Холл"}]}}})
    assert r.status_code == 200
    while (d := c.get(f"/api/drawings/{did}").json())["status"] not in ("done", "error"):
        time.sleep(0.2)
    assert d["status"] == "done" and d["build"] == 2
    dxf = c.get(f"/api/drawings/{did}/drawing.dxf")
    assert dxf.status_code == 200 and b"SECTION" in dxf.content[:200]
    assert any(k.endswith("/edited.dxf") for k in s3.list(files.drawing_key(did, "export/")))

    r = c.post("/api/catalog/items/doc.couch/model", files={"file": ("m.glb", glb.content)})
    assert r.status_code == 200
    url = r.json()["modelUrl"]
    assert c.get(url).content == glb.content
    assert c.get("/api/catalog/models/..%2Fx.glb").status_code == 404


def test_backup_mirror(s3, tmp_path):
    from dwg3d import backup

    s3.put_bytes("drawings/d/input.dxf", b"abc")
    s3.put_bytes("catalog/m.glb", b"glb")
    dst = tmp_path / "bk"
    (dst / "drawings" / "old").mkdir(parents=True)
    (dst / "drawings" / "old" / "gone.txt").write_text("x")
    assert backup.mirror_files(dst) == {"copied": 2, "removed": 1, "total": 2}
    assert (dst / "drawings" / "d" / "input.dxf").read_bytes() == b"abc"
    assert backup.mirror_files(dst) == {"copied": 0, "removed": 0, "total": 2}


def test_local_list(tmp_path, monkeypatch):
    monkeypatch.setenv("DWG3D_DATA", str(tmp_path))
    st = files.LocalStore()
    st.put_bytes("drawings/d/out/model.glb", b"1")
    st.put_bytes("catalog/m.glb", b"22")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "x").write_text("not a stored file")
    assert st.list("") == {"drawings/d/out/model.glb": 1, "catalog/m.glb": 2}
    assert st.list("drawings/d/") == {"drawings/d/out/model.glb": 1}
    assert (tmp_path / "jobs" / "d" / "out" / "model.glb").exists()


def test_restore_from_backup(s3, tmp_path):
    src = tmp_path / "files"
    (src / "drawings" / "d").mkdir(parents=True)
    (src / "drawings" / "d" / "input.dxf").write_bytes(b"abc")
    (src / "junk.txt").write_text("x")
    assert files.restore_from(s3, src)["files"] == 1
    assert s3.list("") == {"drawings/d/input.dxf": 3}
    assert files.restore_from(s3, src) == {"files": 0, "skipped": 1, "bytes": 0}
