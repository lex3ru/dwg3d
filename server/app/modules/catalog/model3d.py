"""3D-модель типа (5.2.2): файл GLB (glTF 2.0). При загрузке считается размер модели по
её узлам, чтобы сверить с габаритами типа и дать подогнать масштаб и поворот."""

import json
import struct
import uuid
from typing import Any, BinaryIO

import numpy as np
from sqlalchemy.orm import Session

from app.core import uploads
from app.core.actor import Actor
from app.core.errors import AppError
from app.modules.catalog import api
from app.modules.catalog.models import ItemType
from app.modules.files import api as files
from app.modules.system import api as system


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


MAX_DEPTH = 256  # глубина дерева узлов; у настоящих моделей — единицы и десятки


def _broken(what: str) -> AppError:
    return AppError(f"GLB повреждён: {what}. Пересохраните модель в редакторе 3D.",
                    code="bad_glb")


def _item(items: list[Any], index: Any, what: str) -> Any:
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
        raise _broken(f"{what} {index} нет в файле")
    return items[index]


def size_of(data: bytes) -> list[float]:
    """Размер модели в единицах файла (по стандарту glTF — метры): [x, y, z], y — вверх.
    Испорченный файл — «GLB повреждён», а не внутренняя ошибка (R-025)."""
    try:
        return _size_of(data)
    except AppError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, struct.error):
        raise _broken("описание сцены не читается") from None


def _size_of(data: bytes) -> list[float]:
    if len(data) < 20 or data[:4] != b"glTF":
        raise AppError("Это не GLB (glTF 2.0 в двоичном виде).", code="bad_glb")
    (version,) = struct.unpack_from("<I", data, 4)
    if version != 2:
        raise AppError("Нужен glTF версии 2.", code="bad_glb")
    length, kind = struct.unpack_from("<I4s", data, 12)
    if kind != b"JSON":
        raise _broken("нет описания сцены")
    doc = json.loads(data[20 : 20 + length])
    nodes = doc.get("nodes", [])
    meshes = doc.get("meshes", [])
    accessors = doc.get("accessors", [])
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)

    scenes = doc.get("scenes", [])
    if scenes:
        roots = _item(scenes, doc.get("scene", 0), "Сцены").get("nodes", [])
    else:  # сцены нет — корни те узлы, что ничьи не потомки
        children = {c for node in nodes for c in node.get("children", [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    # обход без рекурсии; у узла glTF 2.0 один родитель — узел, встреченный дважды (цикл или
    # общий потомок), повреждение: иначе 25 узлов дают 2^24 путей обхода
    seen: set[int] = set()
    stack = [(root, np.eye(4), 1) for root in reversed(roots)]
    while stack:
        index, parent, depth = stack.pop()
        node = _item(nodes, index, "Узла")
        if index in seen:
            raise _broken(f"узел {index} входит в сцену дважды")
        if depth > MAX_DEPTH:
            raise _broken(f"дерево узлов глубже {MAX_DEPTH}")
        seen.add(index)
        world = parent @ _matrix(node)
        if "mesh" in node:
            for prim in _item(meshes, node["mesh"], "Сетки").get("primitives", []):
                attributes = prim.get("attributes", {})
                if "POSITION" not in attributes:
                    continue
                acc = _item(accessors, attributes["POSITION"], "Координат")
                if "min" not in acc:
                    continue
                a, b = acc["min"], acc["max"]
                corners = np.array(
                    [[x, y, z, 1] for x in (a[0], b[0]) for y in (a[1], b[1]) for z in (a[2], b[2])]
                ).T
                pts = (world @ corners)[:3]
                lo = np.minimum(lo, pts.min(axis=1))
                hi = np.maximum(hi, pts.max(axis=1))
        stack.extend((child, world, depth + 1) for child in reversed(node.get("children", [])))
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
    limit: int | None = None,
) -> ItemType:
    """limit — наибольший размер в байтах; по умолчанию — из настроек (7.3 п. 4)."""
    api._admin(actor)
    api.get_type(session, type_id)
    what, most = system.upload_limit(session, "model3d")
    most = limit or most
    data = stream.read(most + 1)
    if len(data) > most:
        raise uploads.too_large(what, most)
    size = size_of(data)
    import io

    record = files.store(session, actor, io.BytesIO(data), name, {"glb"})
    return api.attach_model3d(session, actor, type_id, record.id, size, credit, transform)
