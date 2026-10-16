"""Программный интерфейс файлов для других модулей."""

import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.config import config
from app.core.errors import AppError, NotFound
from app.modules.files.models import StoredFile

MAX_SIZE = 300 * 1024 * 1024

# что принимается и как узнаётся по первым байтам; модули выше передают, какие виды ждут
KINDS: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "webp": ("image/webp", (b"RIFF",)),
    "dwg": ("application/acad", (b"AC10",)),
    "dxf": ("application/dxf", (b"AutoCAD Binary DXF",)),
    "glb": ("model/gltf-binary", (b"glTF",)),
}
TITLES = {"pdf": "PDF", "png": "PNG", "jpeg": "JPEG", "webp": "WebP", "dwg": "DWG",
          "dxf": "DXF", "glb": "GLB"}


def _root() -> Path:
    return config().data_dir / "files"


def path_of(sha256: str) -> Path:
    return _root() / sha256[:2] / sha256[2:4] / sha256


def _sniff(head: bytes) -> str | None:
    # текстовый DXF: группы «код — значение», начинается с секции или комментария
    text = head.lstrip()
    if (text.startswith(b"0") and b"SECTION" in text[:40]) or text.startswith(b"999"):
        return "dxf"
    for kind, (_, signatures) in KINDS.items():
        if any(head.startswith(s) for s in signatures):
            if kind == "webp" and head[8:12] != b"WEBP":
                continue
            return kind
    return None


def store(session: Session, actor: Actor | None, stream: BinaryIO, name: str,
          accept: set[str]) -> StoredFile:
    """Сохранить загруженный файл; `accept` — какие виды допустимы ("pdf", "png"…)."""
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    head = b""
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as tmp:
        try:
            while chunk := stream.read(1024 * 1024):
                if not head:
                    head = chunk[:64]
                size += len(chunk)
                if size > MAX_SIZE:
                    raise AppError(f"Файл больше {MAX_SIZE // 1024 // 1024} МБ.",
                                   code="too_large")
                digest.update(chunk)
                tmp.write(chunk)
            kind = _sniff(head)
            if kind is None or kind not in accept:
                wanted = ", ".join(TITLES[k] for k in sorted(accept))
                raise AppError(f"Файл «{name}» — не {wanted}. Проверьте, тот ли файл выбран.",
                               code="bad_file_type")
        except BaseException:
            os.unlink(tmp.name)
            raise
    sha = digest.hexdigest()
    target = path_of(sha)
    if target.exists():
        os.unlink(tmp.name)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp.name, target)
    record = StoredFile(id=uuid.uuid4(), sha256=sha, size=size, content_type=KINDS[kind][0],
                        name=name[:300], created_by=actor.user_id if actor else None)
    session.add(record)
    session.flush()
    return record


def get(session: Session, file_id: uuid.UUID) -> StoredFile:
    record = session.get(StoredFile, file_id)
    if record is None or not path_of(record.sha256).exists():
        raise NotFound("Файл не найден.")
    return record


def view(record: StoredFile) -> dict[str, object]:
    return {"id": record.id, "name": record.name, "size": record.size,
            "content_type": record.content_type, "url": f"/api/files/{record.id}"}
