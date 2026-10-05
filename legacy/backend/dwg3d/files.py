"""Where the files of drawings and the catalog live: a local directory
(development, tests) or S3-compatible object storage (the containers).

Keys:
  drawings/<id>/<path>   input*.dwg|dxf, builds/<job>/... (one tree per build:
                         model, plans, exports, converted DXF, caches; builds
                         before versioning have out/...), detail.glb, export/<key>/...
  catalog/<file>         uploaded catalog models (GLB)

Local mode keeps the old layout under DWG3D_DATA: jobs/<id>/<path>, catalog/<file>.

The build pipeline works on local files: `workdir(id)` is the local directory
of a drawing. In local mode it is the drawing's own directory; in S3 mode it
is a working copy under DWG3D_SCRATCH that `pull()` brings up to date and
`push()` sends back. A manifest (sha256 per file) keeps both transfers to
the files that changed.

A build's tree is written once, under a new name, before the build becomes
current (Build.out_dir), and is never changed afterwards: readers of the
current build never see files of the next one, and a build that fails to
commit leaves only an orphan tree (`prune()` removes it).

  DWG3D_S3_ENDPOINT     http://s3:9000 — S3 mode when set
  DWG3D_S3_BUCKET       bucket (dwg3d; created when missing)
  DWG3D_S3_ACCESS_KEY, DWG3D_S3_SECRET_KEY, DWG3D_S3_REGION (us-east-1)
  DWG3D_SCRATCH         working copies in S3 mode (default <DWG3D_DATA>/scratch)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ".manifest.json"
CHUNK = 1 << 20


def data_root() -> Path:
    return Path(os.environ.get("DWG3D_DATA", ROOT / "data"))


def drawing_key(did: str, path: str = "") -> str:
    return f"drawings/{did}/{path}" if path else f"drawings/{did}/"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


# a tree to pull: its name in the store, or (name in the store, local directory)
Tree = str | tuple[str, str]


def _tree_names(t: Tree) -> tuple[str, str]:
    return (t, t) if isinstance(t, str) else t


def _tree(base: Path) -> dict[str, Path]:
    return {p.relative_to(base).as_posix(): p for p in base.rglob("*")
            if p.is_file() and p.name != MANIFEST and not p.name.endswith(".part")}


class LocalStore:
    """Files under DWG3D_DATA, laid out as before object storage."""

    s3 = False

    def path(self, key: str) -> Path:
        root = data_root()
        if key.startswith("drawings/"):
            return root / "jobs" / key[len("drawings/"):]
        return root / key

    def put_file(self, key: str, src: Path, move: bool = False):
        dst = self.path(key)
        if Path(src).resolve() == dst.resolve():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f"{dst.name}.{uuid.uuid4().hex[:8]}.part")
        if move:
            shutil.move(str(src), tmp)
        else:
            shutil.copyfile(src, tmp)
        tmp.replace(dst)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None):
        dst = self.path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f"{dst.name}.{uuid.uuid4().hex[:8]}.part")
        tmp.write_bytes(data)
        tmp.replace(dst)

    def get_bytes(self, key: str) -> bytes | None:
        p = self.path(key)
        return p.read_bytes() if p.is_file() else None

    def download(self, key: str, dst: Path) -> bool:
        p = self.path(key)
        if not p.is_file():
            return False
        if p.resolve() != Path(dst).resolve():
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
        return True

    def size(self, key: str) -> int | None:
        p = self.path(key)
        return p.stat().st_size if p.is_file() else None

    def stream(self, key: str) -> Iterator[bytes]:
        with open(self.path(key), "rb") as f:
            while chunk := f.read(CHUNK):
                yield chunk

    def local_path(self, key: str) -> Path | None:
        p = self.path(key)
        return p if p.is_file() else None

    def delete(self, key: str):
        self.path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str):
        p = self.path(prefix.rstrip("/"))
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)

    def list(self, prefix: str) -> dict[str, int]:
        out = {}
        for top, key_top in (("jobs", "drawings"), ("catalog", "catalog")):
            if not (f"{key_top}/".startswith(prefix) or prefix.startswith(f"{key_top}/")):
                continue
            base = data_root() / top
            for rel, p in (_tree(base).items() if base.is_dir() else []):
                if (key := f"{key_top}/{rel}").startswith(prefix):
                    out[key] = p.stat().st_size
        return out

    def workdir(self, did: str) -> Path:
        return self.path(drawing_key(did).rstrip("/"))

    def pull(self, did: str, paths: list[str] = (), trees: list[Tree] = (),
             include: Callable[[str], bool] | None = None) -> Path:
        """The files are here already; a stored tree wanted under another
        local name (a build's tree as the working out/) is copied there
        when that directory does not exist yet."""
        wd = self.workdir(did)
        for stored, local in map(_tree_names, trees):
            src, dst = wd / stored, wd / local
            if stored != local and src.is_dir() and not dst.exists():
                shutil.copytree(src, dst)
        return wd

    def push(self, did: str, tree: str, to: str | None = None, base: str | None = None):
        """Store a working tree as `to` (a new build's tree: a full copy)."""
        if to is None or to == tree:
            return
        wd = self.workdir(did)
        tmp = wd / f"{to}.{uuid.uuid4().hex[:8]}.part"
        if (wd / tree).is_dir():
            shutil.copytree(wd / tree, tmp, ignore=shutil.ignore_patterns("*.part"))
        else:
            tmp.mkdir(parents=True)
        dst = wd / to
        shutil.rmtree(dst, ignore_errors=True)
        tmp.replace(dst)


class S3Store:
    """S3-compatible object storage (RustFS, MinIO, SeaweedFS, AWS...)."""

    s3 = True

    def __init__(self):
        import boto3
        from botocore.config import Config

        self.bucket = os.environ.get("DWG3D_S3_BUCKET", "dwg3d")
        self.client = boto3.client(
            "s3", endpoint_url=os.environ["DWG3D_S3_ENDPOINT"],
            aws_access_key_id=os.environ.get("DWG3D_S3_ACCESS_KEY"),
            aws_secret_access_key=os.environ.get("DWG3D_S3_SECRET_KEY"),
            region_name=os.environ.get("DWG3D_S3_REGION", "us-east-1"),
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5, "mode": "standard"},
                          signature_version="s3v4"))
        self._ready = False
        self._lock = threading.Lock()

    def _bucket(self) -> str:
        if not self._ready:
            with self._lock:
                if not self._ready:
                    from botocore.exceptions import ClientError
                    try:
                        self.client.head_bucket(Bucket=self.bucket)
                    except ClientError:
                        self.client.create_bucket(Bucket=self.bucket)
                    self._ready = True
        return self.bucket

    def _missing(self, ex) -> bool:
        return getattr(ex, "response", {}).get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound")

    def put_file(self, key: str, src: Path, move: bool = False):
        self.client.upload_file(str(src), self._bucket(), key)
        if move:
            Path(src).unlink(missing_ok=True)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None):
        kw = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self._bucket(), Key=key, Body=data, **kw)

    def get_bytes(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError
        try:
            return self.client.get_object(Bucket=self._bucket(), Key=key)["Body"].read()
        except ClientError as ex:
            if self._missing(ex):
                return None
            raise

    def download(self, key: str, dst: Path) -> bool:
        from botocore.exceptions import ClientError
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f"{dst.name}.{uuid.uuid4().hex[:8]}.part")
        try:
            self.client.download_file(self._bucket(), key, str(tmp))
        except ClientError as ex:
            tmp.unlink(missing_ok=True)
            if self._missing(ex):
                return False
            raise
        tmp.replace(dst)
        return True

    def size(self, key: str) -> int | None:
        from botocore.exceptions import ClientError
        try:
            return self.client.head_object(Bucket=self._bucket(), Key=key)["ContentLength"]
        except ClientError as ex:
            if self._missing(ex):
                return None
            raise

    def stream(self, key: str) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self._bucket(), Key=key)["Body"]
        try:
            yield from body.iter_chunks(CHUNK)
        finally:
            body.close()

    def local_path(self, key: str) -> Path | None:
        return None

    def delete(self, key: str):
        self.client.delete_object(Bucket=self._bucket(), Key=key)

    def delete_prefix(self, prefix: str):
        keys = list(self.list(prefix))
        for i in range(0, len(keys), 1000):
            self.client.delete_objects(Bucket=self._bucket(),
                                       Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True})

    def list(self, prefix: str) -> dict[str, int]:
        out = {}
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self._bucket(), Prefix=prefix):
            for o in page.get("Contents") or []:
                out[o["Key"]] = o["Size"]
        return out

    # ---- working copies of drawings
    def workdir(self, did: str) -> Path:
        scratch = Path(os.environ.get("DWG3D_SCRATCH") or data_root() / "scratch")
        return scratch / "drawings" / did

    def _manifest(self, did: str, tree: str) -> dict[str, str]:
        raw = self.get_bytes(drawing_key(did, f"{tree}/{MANIFEST}"))
        return json.loads(raw) if raw else {}

    def pull(self, did: str, paths: list[str] = (), trees: list[Tree] = (),
             include: Callable[[str], bool] | None = None) -> Path:
        """Bring the working copy up to date: single files (downloaded when
        missing or of another size) and whole trees (by the manifest; local
        files the manifest does not list are removed). A tree may land under
        another local name: ("builds/12", "out")."""
        wd = self.workdir(did)
        for rel in paths:
            local = wd / rel
            remote = self.size(drawing_key(did, rel))
            if remote is None:
                local.unlink(missing_ok=True)
            elif not local.is_file() or local.stat().st_size != remote:
                self.download(drawing_key(did, rel), local)
        for stored, local in map(_tree_names, trees):
            want = self._manifest(did, stored)
            base = wd / local
            have = _tree(base) if base.is_dir() else {}
            for rel, p in have.items():
                if rel not in want and (include is None or include(rel)):
                    p.unlink()
            for rel, digest in want.items():
                if include is not None and not include(rel):
                    continue
                p = base / rel
                if not p.is_file() or _sha256(p) != digest:
                    self.download(drawing_key(did, f"{stored}/{rel}"), p)
        return wd

    def push(self, did: str, tree: str, to: str | None = None, base: str | None = None):
        """Upload the files of a working-copy tree that changed, remove the
        stored ones that are gone locally, then write the manifest. `to`
        stores it under another name (a new build's tree); files equal to
        those of the stored tree `base` are copied inside the store."""
        to = to or tree
        src = self.workdir(did) / tree
        old = self._manifest(did, to)
        same = self._manifest(did, base) if base and base != to else {}
        new = {rel: _sha256(p) for rel, p in _tree(src).items()} if src.is_dir() else {}
        prefix = drawing_key(did, f"{to}/")
        stored = {k[len(prefix):] for k in self.list(prefix)} - {MANIFEST}
        for rel, digest in new.items():
            if old.get(rel) == digest and rel in stored:
                continue
            key = drawing_key(did, f"{to}/{rel}")
            if same.get(rel) == digest and self.copy(drawing_key(did, f"{base}/{rel}"), key):
                continue
            self.put_file(key, src / rel)
        for rel in stored - set(new):
            self.delete(drawing_key(did, f"{to}/{rel}"))
        self.put_bytes(drawing_key(did, f"{to}/{MANIFEST}"), json.dumps(new).encode(), "application/json")

    def copy(self, src: str, dst: str) -> bool:
        """Copy an object inside the bucket (False when `src` is missing)."""
        from botocore.exceptions import ClientError
        try:
            self.client.copy({"Bucket": self._bucket(), "Key": src}, self._bucket(), dst)
        except ClientError as ex:
            if self._missing(ex):
                return False
            raise
        return True


def prune(st: LocalStore | S3Store, did: str, keep: set[str]):
    """Remove the stored build trees of a drawing other than `keep` (the
    current and the previous build): old builds and orphans of builds that
    failed to commit. The legacy out/ tree is the working copy itself in
    local mode, so it goes only from S3."""
    prefix = drawing_key(did, "builds/")
    trees = {k[len(prefix):].split("/", 1)[0] for k in st.list(prefix)}
    for t in trees - {k.split("/", 1)[1] for k in keep if k.startswith("builds/")}:
        st.delete_prefix(drawing_key(did, f"builds/{t}/"))
    if st.s3 and "out" not in keep:
        st.delete_prefix(drawing_key(did, "out/"))


_store: LocalStore | S3Store | None = None
_store_lock = threading.Lock()
_dir_locks: dict[str, threading.Lock] = {}


def lock(did: str) -> threading.Lock:
    """Serialises work on one drawing's working copy within this process."""
    with _store_lock:
        return _dir_locks.setdefault(did, threading.Lock())


def store() -> LocalStore | S3Store:
    """The configured file store (chosen once per process, on first use)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = S3Store() if os.environ.get("DWG3D_S3_ENDPOINT") else LocalStore()
    return _store


def reset():
    """Forget the store (tests switch between local and S3)."""
    global _store
    _store = None


def copy_local_to(dst: LocalStore | S3Store, src: LocalStore | None = None, log=print) -> dict:
    """Upload everything of a local data directory into `dst` (moving to S3).
    Files already there with the same size are skipped; drawing out/ trees get
    their manifest. Returns counts."""
    src = src or LocalStore()
    root = data_root()
    st = {"files": 0, "skipped": 0, "bytes": 0}
    have = dst.list("")
    jobs = root / "jobs"
    for ddir in sorted(p for p in jobs.iterdir() if p.is_dir()) if jobs.is_dir() else []:
        did = ddir.name
        for rel, p in _tree(ddir).items():
            key = drawing_key(did, rel)
            if have.get(key) == p.stat().st_size:
                st["skipped"] += 1
                continue
            dst.put_file(key, p)
            st["files"] += 1
            st["bytes"] += p.stat().st_size
        if (ddir / "out").is_dir():
            manifest = {rel: _sha256(p) for rel, p in _tree(ddir / "out").items()}
            dst.put_bytes(drawing_key(did, f"out/{MANIFEST}"), json.dumps(manifest).encode(), "application/json")
        log(f"  {did}: готово")
    cat = root / "catalog"
    for rel, p in (_tree(cat).items() if cat.is_dir() else []):
        key = f"catalog/{rel}"
        if have.get(key) == p.stat().st_size:
            st["skipped"] += 1
            continue
        dst.put_file(key, p)
        st["files"] += 1
        st["bytes"] += p.stat().st_size
    return st


def restore_from(dst: LocalStore | S3Store, src_dir: Path) -> dict:
    """Upload a backup mirror (a directory laid out by keys: drawings/..., catalog/...)."""
    st = {"files": 0, "skipped": 0, "bytes": 0}
    have = dst.list("")
    for key, p in _tree(src_dir).items():
        if not key.startswith(("drawings/", "catalog/")):
            continue
        if have.get(key) == p.stat().st_size:
            st["skipped"] += 1
            continue
        dst.put_file(key, p)
        st["files"] += 1
        st["bytes"] += p.stat().st_size
    return st
