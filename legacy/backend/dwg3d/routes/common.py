"""What the routers share: who is asking, project and drawing lookups with the
access check, files of the store as responses, uploads, small validators."""
from __future__ import annotations

import logging
import os
import time
import urllib.parse
import uuid
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select

from .. import access, auth, db, files, store
from ..models import Drawing, Layer, Project

log = logging.getLogger("dwg3d.api")
RETENTION_DAYS = float(os.environ.get("DWG3D_RETENTION_DAYS", "0"))

# streamed answers (SSE, NDJSON): no caching, no proxy buffering
STREAM_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def mb(env: str, default: int) -> int:
    """A size limit from DWG3D_MAX_*_MB, in bytes."""
    return int(os.environ.get(env, str(default))) * 1024 * 1024


def whoami(request: Request) -> auth.Me | None:
    """The user of the session cookie, else the guest of a share-link cookie."""
    if not auth.enabled():
        return auth.ANONYMOUS_ADMIN
    return (auth.resolve(request.cookies.get(auth.COOKIE))
            or access.resolve_share(request.cookies.get(access.SHARE_COOKIE)))


def base_url(request: Request) -> str:
    """This site as the browser sees it (for redirects back from Keycloak)."""
    if url := os.environ.get("DWG3D_PUBLIC_URL"):
        return url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def admin():
    me = auth.current.get()
    if me is None or me.share is not None or not me.can("admin"):
        raise HTTPException(403, "Недостаточно прав: нужна роль «администратор»")


def project(s, pid: str, lock: bool = False, need: str | None = None) -> Project:
    """The project, if the current user may do this in it (`need`: the role
    it takes; by default viewer for reading, editor for changes)."""
    p = store.get_project(s, pid, lock=lock)
    if p is None:
        raise HTTPException(404, "Проект не найден")
    access.check(s, pid, need)
    return p


def drawing(s, did: str, lock: bool = False, need: str | None = None) -> Drawing:
    d = store.get_drawing(s, did, lock=lock)
    if d is None:
        raise HTTPException(404, "Чертёж не найден")
    access.check_drawing(s, d, need)
    return d


def layer_of(s, pid: str, lid: str, lock: bool = False) -> Layer | None:
    q = select(Layer).where(Layer.id == lid, Layer.project_id == pid)
    return s.scalar(q.with_for_update() if lock else q)


def layer(s, pid: str, lid: str) -> Layer:
    """The project's layer, locked for a change."""
    if (x := layer_of(s, pid, lid, lock=True)) is None:
        raise HTTPException(404, "Слой не найден")
    return x


def text(v: dict, key: str, n: int, required: bool = False) -> str | None:
    x = v.get(key)
    if x is None and not required:
        return None
    if not isinstance(x, str) or len(x.strip()) > n or (required and not x.strip()):
        raise HTTPException(400, f"{key}: строка до {n} символов" + (" (обязательно)" if required else ""))
    return x.strip()


def bad(fn, *a):
    """fn(*a) with ValueError as 400 and LookupError as 404."""
    try:
        return fn(*a)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    except LookupError:
        raise HTTPException(404, "Не найдено")


def serve(key: str, media_type: str, filename: str | None = None, headers: dict | None = None):
    """A file of the store as the response: from disk, or streamed from S3."""
    st = files.store()
    if (p := st.local_path(key)) is not None:
        return FileResponse(p, media_type=media_type, filename=filename, headers=headers)
    size = st.size(key)
    if size is None:
        raise HTTPException(404)
    h = {"Content-Length": str(size), **(headers or {})}
    if filename:
        h["Content-Disposition"] = f"attachment; filename*=utf-8''{urllib.parse.quote(filename)}"
    return StreamingResponse(st.stream(key), media_type=media_type, headers=h)


def tmp_path(suffix: str = "") -> Path:
    """A fresh local temp file path for an upload on its way into the store."""
    d = files.data_root() / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{uuid.uuid4().hex}{suffix}.part"


async def save_upload(file: UploadFile, dst: Path, limit: int) -> tuple[int, bytes]:
    """Stream an upload to `dst` (removed again when it is over `limit` bytes):
    its size and first 12 bytes."""
    size, head = 0, b""
    with open(dst, "wb") as f:
        while chunk := await file.read(1 << 20):
            if not head:
                head = chunk[:12]
            size += len(chunk)
            if size > limit:
                f.close()
                dst.unlink(missing_ok=True)
                raise HTTPException(413, "Файл слишком большой")
            f.write(chunk)
    return size, head


_last_cleanup = 0.0


def cleanup():
    """Delete projects untouched for RETENTION_DAYS (disabled when 0); at most hourly."""
    global _last_cleanup
    if RETENTION_DAYS <= 0 or time.time() - _last_cleanup < 3600:
        return
    _last_cleanup = time.time()
    with db.session() as s:
        gone = store.delete_stale(s, RETENTION_DAYS)
    for did in gone:
        files.store().delete_prefix(files.drawing_key(did))
    if gone:
        log.info("%d drawing(s) of stale projects removed (retention %s days)", len(gone), RETENTION_DAYS)
