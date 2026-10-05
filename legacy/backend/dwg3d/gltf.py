"""Minimal GLB (binary glTF 2.0) writer with named node hierarchy + extras."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
FLOAT, UINT32 = 5126, 5125


class GLBWriter:
    def __init__(self):
        self.nodes: list[dict] = []
        self.meshes: list[dict] = []
        self.materials: list[dict] = []
        self.accessors: list[dict] = []
        self.views: list[dict] = []
        self.bin = bytearray()
        self._mat_index: dict[str, int] = {}
        self.extensions: set[str] = set()

    def _view(self, data: bytes, target: int) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        self.views.append({"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data), "target": target})
        self.bin += data
        return len(self.views) - 1

    def _accessor(self, arr: np.ndarray, target: int, kind: str) -> int:
        comp = UINT32 if arr.dtype == np.uint32 else FLOAT
        acc = {"bufferView": self._view(arr.tobytes(), target), "componentType": comp,
               "count": int(arr.shape[0]), "type": kind}
        if kind == "VEC3":
            acc["min"] = arr.min(axis=0).tolist()
            acc["max"] = arr.max(axis=0).tolist()
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def material(self, name: str, rgba, metallic=0.0, roughness=0.85, blend=False, double_sided=False,
                 unlit=False) -> int:
        if name in self._mat_index:
            return self._mat_index[name]
        m = {"name": name, "pbrMetallicRoughness": {
            "baseColorFactor": [float(c) for c in rgba], "metallicFactor": metallic, "roughnessFactor": roughness}}
        if unlit:
            m["extensions"] = {"KHR_materials_unlit": {}}
            self.extensions.add("KHR_materials_unlit")
        if blend:
            m["alphaMode"] = "BLEND"
        if double_sided:
            m["doubleSided"] = True
        self.materials.append(m)
        self._mat_index[name] = len(self.materials) - 1
        return self._mat_index[name]

    def mesh(self, name: str, positions: np.ndarray, normals: np.ndarray | None, indices: np.ndarray,
             material: int, mode: int = 4) -> int:
        """mode 4 = TRIANGLES, 1 = LINES (normals may be None)."""
        attrs = {"POSITION": self._accessor(positions.astype(np.float32), ARRAY_BUFFER, "VEC3")}
        if normals is not None:
            attrs["NORMAL"] = self._accessor(normals.astype(np.float32), ARRAY_BUFFER, "VEC3")
        prim = {
            "attributes": attrs,
            "indices": self._accessor(indices.astype(np.uint32).ravel(), ELEMENT_ARRAY_BUFFER, "SCALAR"),
            "material": material,
            "mode": mode,
        }
        self.meshes.append({"name": name, "primitives": [prim]})
        return len(self.meshes) - 1

    def node(self, name: str, mesh: int | None = None, children: list[int] | None = None,
             extras: dict | None = None) -> int:
        n: dict = {"name": name}
        if mesh is not None:
            n["mesh"] = mesh
        if children:
            n["children"] = children
        if extras:
            n["extras"] = extras
        self.nodes.append(n)
        return len(self.nodes) - 1

    def save(self, path: Path, roots: list[int], extras: dict | None = None):
        while len(self.bin) % 4:
            self.bin.append(0)
        gltf = {
            "asset": {"version": "2.0", "generator": "dwg3d"},
            "scene": 0,
            "scenes": [{"name": "building", "nodes": roots, **({"extras": extras} if extras else {})}],
            "nodes": self.nodes, "meshes": self.meshes, "materials": self.materials,
            "accessors": self.accessors, "bufferViews": self.views,
            "buffers": [{"byteLength": len(self.bin)}],
        }
        if self.extensions:
            gltf["extensionsUsed"] = sorted(self.extensions)
        js = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        js += b" " * ((4 - len(js) % 4) % 4)
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A))
            f.write(js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942))
            f.write(self.bin)
