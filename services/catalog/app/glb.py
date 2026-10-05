"""A look inside a GLB without loading it: enough to warn about a model of the wrong size."""
from __future__ import annotations

import json
import struct

MAX_SIZE = 50 * 1024 * 1024
BIG = 20 * 1024 * 1024


def bounds(data: bytes) -> tuple[float, float, float] | None:
    """Extents of the model along its axes, by the declared bounds of its meshes
    (node transforms are not applied: this is for a warning, not for placing)."""
    try:
        if data[:4] != b"glTF":
            return None
        length, kind = struct.unpack_from("<II", data, 12)
        if kind != 0x4E4F534A:                       # "JSON"
            return None
        doc = json.loads(data[20:20 + length])
        lo, hi = [float("inf")] * 3, [float("-inf")] * 3
        for mesh in doc.get("meshes") or []:
            for primitive in mesh.get("primitives") or []:
                accessor = (doc.get("accessors") or [])[primitive["attributes"]["POSITION"]]
                for i in range(3):
                    lo[i], hi[i] = min(lo[i], accessor["min"][i]), max(hi[i], accessor["max"][i])
        return None if lo[0] == float("inf") else tuple(round(hi[i] - lo[i], 4) for i in range(3))
    except (KeyError, IndexError, ValueError, TypeError, struct.error):
        return None


def warnings(data: bytes, declared: tuple[float, float, float]) -> list[str]:
    out = []
    if len(data) > BIG:
        mb = len(data) // (1024 * 1024)
        out.append(f"Модель большая ({mb} МБ): сцена с такими объектами будет открываться медленно")
    size = bounds(data)
    if size is None:
        out.append("Размеры модели определить не удалось")
    else:
        got, want = sorted(size), sorted(declared)
        if any(g > 2 * w or w > 2 * g for g, w in zip(got, want, strict=True) if w > 0 and g > 0):
            out.append("Размеры модели ({} м) расходятся с габаритами типа ({} м) больше чем вдвое — "
                       "проверьте единицы модели".format(" × ".join(f"{v:g}" for v in size),
                                                         " × ".join(f"{v:g}" for v in declared)))
    return out
