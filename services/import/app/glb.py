"""A model cut down to some of its floors: what a guest of one floor is given instead of the whole drawing.

The model of a build has a root node per floor (`floor_<id>`, rooms and walls under it) and the roof.
The cut keeps the named roots with everything under them, and only the bytes those reference — the
other floors are not in the file at all, not merely hidden.
"""
from __future__ import annotations

import json
import struct

MAGIC, JSON_CHUNK, BIN_CHUNK = 0x46546C67, 0x4E4F534A, 0x004E4942


def read(data: bytes) -> tuple[dict, bytes]:
    magic, _, _ = struct.unpack_from("<III", data, 0)
    if magic != MAGIC:
        raise ValueError("not a GLB")
    at, gltf, binary = 12, None, b""
    while at < len(data):
        length, kind = struct.unpack_from("<II", data, at)
        chunk = data[at + 8:at + 8 + length]
        if kind == JSON_CHUNK:
            gltf = json.loads(chunk)
        elif kind == BIN_CHUNK:
            binary = chunk
        at += 8 + length
    return gltf, binary


def write(gltf: dict, binary: bytes) -> bytes:
    js = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    binary += b"\0" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (struct.pack("<III", MAGIC, 2, total) + struct.pack("<II", len(js), JSON_CHUNK) + js
            + struct.pack("<II", len(binary), BIN_CHUNK) + binary)


def cut(data: bytes, keep: set[str]) -> bytes:
    """The model with only the root nodes named in `keep` (and what is under them)."""
    gltf, binary = read(data)
    nodes = gltf.get("nodes") or []
    scene = gltf["scenes"][gltf.get("scene", 0)]
    roots = [i for i in scene.get("nodes") or [] if nodes[i].get("name") in keep]
    # the nodes under the kept roots, in their old order
    used_nodes, stack = set(), list(roots)
    while stack:
        i = stack.pop()
        if i not in used_nodes:
            used_nodes.add(i)
            stack.extend(nodes[i].get("children") or [])
    node_map = {old: new for new, old in enumerate(sorted(used_nodes))}
    used_meshes = sorted({nodes[i]["mesh"] for i in used_nodes if "mesh" in nodes[i]})
    mesh_map = {old: new for new, old in enumerate(used_meshes)}
    accessors = gltf.get("accessors") or []
    used_acc = set()
    for m in used_meshes:
        for p in gltf["meshes"][m].get("primitives") or []:
            used_acc.update(p.get("attributes", {}).values())
            if "indices" in p:
                used_acc.add(p["indices"])
    acc_map = {old: new for new, old in enumerate(sorted(used_acc))}
    views = gltf.get("bufferViews") or []
    used_views = sorted({accessors[a]["bufferView"] for a in used_acc if "bufferView" in accessors[a]})
    view_map, out_bin, out_views = {}, bytearray(), []
    for new, old in enumerate(used_views):
        v = views[old]
        while len(out_bin) % 4:
            out_bin.append(0)
        start = v.get("byteOffset", 0)
        out_views.append({**v, "buffer": 0, "byteOffset": len(out_bin)})
        out_bin += binary[start:start + v["byteLength"]]
        view_map[old] = new
    out_nodes = []
    for old in sorted(used_nodes):
        n = dict(nodes[old])
        if "mesh" in n:
            n["mesh"] = mesh_map[n["mesh"]]
        if n.get("children"):
            n["children"] = [node_map[c] for c in n["children"]]
        out_nodes.append(n)
    out_meshes = []
    for m in used_meshes:
        mesh = json.loads(json.dumps(gltf["meshes"][m]))
        for p in mesh.get("primitives") or []:
            p["attributes"] = {k: acc_map[v] for k, v in p.get("attributes", {}).items()}
            if "indices" in p:
                p["indices"] = acc_map[p["indices"]]
        out_meshes.append(mesh)
    out_acc = [{**accessors[a],
                **({"bufferView": view_map[accessors[a]["bufferView"]]} if "bufferView" in accessors[a] else {})}
               for a in sorted(used_acc)]
    out = {**gltf, "scenes": [{**scene, "nodes": [node_map[r] for r in roots]}], "scene": 0, "nodes": out_nodes,
           "meshes": out_meshes, "accessors": out_acc, "bufferViews": out_views,
           "buffers": [{"byteLength": len(out_bin)}]}
    return write(out, bytes(out_bin))
