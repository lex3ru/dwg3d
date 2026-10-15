"""A guest by a link to a building, a floor or a room: the model only — of a floor, that floor cut out of it."""
from __future__ import annotations

import io
from uuid import uuid4

import trimesh

from app import glb, storage

from .conftest import BUILDING, upload

API = "/api/import/v1"
FLOOR_1, FLOOR_2 = str(uuid4()), str(uuid4())              # the floors as the buildings service knows them


async def built(client, worker, tokens, sample, buildings) -> tuple[dict, list[dict]]:
    """A drawing built and placed in the building: its build and the floors of the result;
    the buildings service knows floor 1 and floor 2 of it."""
    drawing = (await upload(client, tokens, sample)).json()
    assert await worker.run_once() is True
    build = (await client.get(f"{API}/drawings/{drawing['id']}", headers=tokens.admin())).json()["build"]
    floors = (await client.get(f"{API}/builds/{build['id']}/result", headers=tokens.admin())).json()["result"]["floors"]
    for floor_id, f in zip((FLOOR_1, FLOOR_2), floors, strict=True):
        buildings[f"/floors/{floor_id}/plan"] = {"floor": {"id": floor_id, "drawing_id": drawing["id"],
                                                           "candidate": f["id"]}}
    buildings[f"/buildings/{BUILDING}/drawings"] = {"items": [{"id": drawing["id"], "build_id": build["id"]}]}
    return build, floors


def roots(model: bytes) -> list[str]:
    gltf, _ = glb.read(model)
    return [gltf["nodes"][i]["name"] for i in gltf["scenes"][gltf.get("scene", 0)]["nodes"]]


def names(model: bytes) -> set[str]:
    return {n.get("name", "") for n in glb.read(model)[0]["nodes"]}


async def test_a_guest_of_the_building_gets_the_whole_model(client, worker, tokens, sample, buildings):
    build, floors = await built(client, worker, tokens, sample, buildings)
    url = f"{API}/builds/{build['id']}/files/model.glb"
    whole = (await client.get(url, headers=tokens.admin())).content
    guest = tokens.guest("building", BUILDING, BUILDING)
    r = await client.get(url, headers=guest)
    assert r.status_code == 200 and r.content == whole
    assert {f["node"] for f in floors} <= set(roots(r.content))
    # whatever floor it names: the building is its own
    assert (await client.get(url, params={"floor": FLOOR_2}, headers=guest)).content == whole


async def test_a_guest_of_a_floor_gets_that_floor_only(client, worker, tokens, sample, buildings):
    build, floors = await built(client, worker, tokens, sample, buildings)
    url = f"{API}/builds/{build['id']}/files/model.glb"
    mine, other = floors[0]["node"], floors[1]["node"]
    guest = tokens.guest("floor", FLOOR_1, BUILDING, FLOOR_1)
    r = await client.get(url, params={"floor": FLOOR_1}, headers=guest)
    assert r.status_code == 200 and r.headers["content-type"] == "model/gltf-binary"
    # its floor with the walls and the glass, and no trace of the other floor or the roof
    assert roots(r.content) == [mine]
    assert {mine, f"{mine}_walls", f"{mine}_glass"} <= names(r.content)
    assert not any(n.startswith(other) or n == "roof" for n in names(r.content))
    assert len(r.content) < len((await client.get(url, headers=tokens.admin())).content)
    # the cut is kept for the next guest, and is a model a viewer opens
    kept = storage.bucket().get_bytes(f"builds/{build['id']}/guest/floor_{floors[0]['id']}.glb")
    assert kept == r.content
    assert trimesh.load(io.BytesIO(r.content), file_type="glb").geometry
    assert (await client.get(url, params={"floor": FLOOR_1}, headers=guest)).content == r.content
    # a guest of a room of the floor gets the same
    room = tokens.guest("room", str(uuid4()), BUILDING, FLOOR_1)
    assert (await client.get(url, params={"floor": FLOOR_1}, headers=room)).content == r.content


async def test_a_guest_of_a_floor_gets_no_other_floor_and_no_other_file(client, worker, tokens, sample, buildings):
    build, floors = await built(client, worker, tokens, sample, buildings)
    files = f"{API}/builds/{build['id']}/files"
    guest = tokens.guest("floor", FLOOR_1, BUILDING, FLOOR_1)
    # another floor, or no floor named — the whole model: there is no such file for this guest
    assert (await client.get(f"{files}/model.glb", params={"floor": FLOOR_2}, headers=guest)).status_code == 404
    assert (await client.get(f"{files}/model.glb", headers=guest)).status_code == 404
    # a floor it is the guest of, which the buildings service does not know any more
    buildings.pop(f"/floors/{FLOOR_1}/plan")
    assert (await client.get(f"{files}/model.glb", params={"floor": FLOOR_1}, headers=guest)).status_code == 404
    # the plans, the other formats, the result, the settings of the drawing — not for a guest at all
    for path in (floors[0]["plan"], "model.ifc", "model_obj.zip", "metadata.json",
                 f"guest/floor_{floors[1]['id']}.glb"):
        r = await client.get(f"{files}/{path}", params={"floor": FLOOR_1}, headers=guest)
        assert (r.status_code, r.json()["code"]) == (403, "guest"), path
    result = await client.get(f"{API}/builds/{build['id']}/result", headers=guest)
    assert (result.status_code, result.json()["code"]) == (403, "guest")
    whole = tokens.guest("building", BUILDING, BUILDING)
    config = await client.get(f"{API}/drawings/{build['drawing_id']}/config", headers=whole)
    assert (config.status_code, config.json()["code"]) == (403, "guest")
    # nor anything of a building it has no link to
    stranger = tokens.guest("building", str(uuid4()), str(uuid4()))
    assert (await client.get(f"{files}/model.glb", headers=stranger)).status_code == 404
    # nor a change
    rebuild = await client.post(f"{API}/drawings/{build['drawing_id']}/builds", json={}, headers=whole)
    assert rebuild.status_code == 403


async def test_a_build_not_placed_in_the_building_is_not_cut_for_a_guest(client, worker, tokens, sample, buildings):
    build, _ = await built(client, worker, tokens, sample, buildings)
    # the building shows another build of the drawing: this one is no guest's
    placed = buildings[f"/buildings/{BUILDING}/drawings"]["items"][0]
    placed["build_id"] = str(uuid4())
    guest = tokens.guest("floor", FLOOR_1, BUILDING, FLOOR_1)
    r = await client.get(f"{API}/builds/{build['id']}/files/model.glb", params={"floor": FLOOR_1}, headers=guest)
    assert r.status_code == 404


def test_cut_keeps_the_named_floors_and_only_their_bytes():
    model = small_model()
    one = glb.cut(model, {"floor_a"})
    gltf, binary = glb.read(one)
    assert [n["name"] for n in gltf["nodes"]] == ["floor_a", "floor_a_walls"]
    assert gltf["scenes"][0]["nodes"] == [0] and gltf["nodes"][0]["children"] == [1]
    assert len(gltf["meshes"]) == 1 and len(gltf["accessors"]) == 2 and len(gltf["bufferViews"]) == 2
    assert gltf["buffers"][0]["byteLength"] == 42 and len(binary) == 44       # the chunk padded to 4 bytes
    # the bytes kept are floor a's positions and indices, nothing of floor b
    positions = gltf["bufferViews"][gltf["accessors"][0]["bufferView"]]
    assert binary[positions["byteOffset"]:positions["byteOffset"] + positions["byteLength"]] == bytes(range(36))
    assert bytes([200]) * 36 not in binary
    # both floors and the roof: all of it; nothing named — an empty scene
    assert sorted(n["name"] for n in glb.read(glb.cut(model, {"floor_a", "floor_b", "roof"}))[0]["nodes"]) == [
        "floor_a", "floor_a_walls", "floor_b", "floor_b_walls", "roof"]
    assert glb.read(glb.cut(model, set()))[0]["nodes"] == []


def small_model() -> bytes:
    """Two floors, each a root with its walls under it (a mesh of a triangle), and a roof without a mesh."""
    binary = bytes(range(36)) + bytes(6) + bytes(2) + bytes([200]) * 36 + bytes([201]) * 6 + bytes(2)
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 6},
             {"buffer": 0, "byteOffset": 44, "byteLength": 36}, {"buffer": 0, "byteOffset": 80, "byteLength": 6}]
    accessors = [{"bufferView": v, "componentType": 5126 if v % 2 == 0 else 5123, "count": 3,
                  "type": "VEC3" if v % 2 == 0 else "SCALAR"} for v in range(4)]
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 2, 4]}],
            "nodes": [{"name": "floor_a", "children": [1]}, {"name": "floor_a_walls", "mesh": 0},
                      {"name": "floor_b", "children": [3]}, {"name": "floor_b_walls", "mesh": 1}, {"name": "roof"}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]},
                       {"primitives": [{"attributes": {"POSITION": 2}, "indices": 3}]}],
            "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(binary)}]}
    return glb.write(gltf, binary)

