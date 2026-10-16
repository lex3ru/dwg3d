"""3D-модель типа (5.2.2): файл GLB (glTF 2.0). При загрузке считается размер модели по
её узлам, чтобы сверить с габаритами типа и дать подогнать масштаб и поворот."""

import json
import struct
import uuid
from typing import Any, BinaryIO

import numpy as np
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError
from app.modules.catalog import api
from app.modules.catalog.models import ItemType
from app.modules.files import api as files

MAX_SIZE = 20 * 1024 * 1024  # 7.3: 3D-модель — до 20 МБ


def _matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    t = np.eye(4)
    t[:3, 3] = node.get("translation", [0, 0, 0])
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    r = np.eye(4)
    r[:3, :3] = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    s = np.diag([*node.get("scale", [1, 1, 1]), 1.0])
    return t @ r @ s


def size_of(data: bytes) -> list[float]:
    """Размер модели в единицах файла (по стандарту glTF — метры): [x, y, z], y — вверх."""
    if len(data) < 20 or data[:4] != b"glTF":
        raise AppError("Это не GLB (glTF 2.0 в двоичном виде).", code="bad_glb")
    (version,) = struct.unpack_from("<I", data, 4)
    if version != 2:
        raise AppError("Нужен glTF версии 2.", code="bad_glb")
    length, kind = struct.unpack_from("<I4s", data, 12)
    if kind != b"JSON":
        raise AppError("GLB повреждён: нет описания сцены.", code="bad_glb")
    doc = json.loads(data[20 : 20 + length])
    nodes = doc.get("nodes", [])
    meshes = doc.get("meshes", [])
    accessors = doc.get("accessors", [])
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)

    def walk(index: int, parent: np.ndarray) -> None:
        nonlocal lo, hi
        node = nodes[index]
        world = parent @ _matrix(node)
        if "mesh" in node:
            for prim in meshes[node["mesh"]].get("primitives", []):
                acc = (
                    accessors[prim.get("attributes", {}).get("POSITION", -1)]
                    if "POSITION" in prim.get("attributes", {})
                    else None
                )
                if not acc or "min" not in acc:
                    continue
                a, b = acc["min"], acc["max"]
                corners = np.array(
                    [[x, y, z, 1] for x in (a[0], b[0]) for y in (a[1], b[1]) for z in (a[2], b[2])]
                ).T
                pts = (world @ corners)[:3]
                lo = np.minimum(lo, pts.min(axis=1))
                hi = np.maximum(hi, pts.max(axis=1))
        for child in node.get("children", []):
            walk(child, world)

    scenes = doc.get("scenes", [])
    roots = scenes[doc.get("scene", 0)].get("nodes", []) if scenes else range(len(nodes))
    for root in roots:
        walk(root, np.eye(4))
    if not np.all(np.isfinite(lo)):
        raise AppError("В модели нет геометрии.", code="bad_glb")
    return [round(float(v), 4) for v in (hi - lo)]


def attach(
    session: Session,
    actor: Actor,
    type_id: uuid.UUID,
    stream: BinaryIO,
    name: str,
    credit: str = "",
    transform: dict[str, Any] | None = None,
) -> ItemType:
    api._admin(actor)
    api.get_type(session, type_id)
    data = stream.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise AppError("3D-модель больше 20 МБ.", code="too_large")
    size = size_of(data)
    import io

    record = files.store(session, actor, io.BytesIO(data), name, {"glb"})
    return api.attach_model3d(session, actor, type_id, record.id, size, credit, transform)
