# ruff: noqa: E501
"""The server's check of a drawn plan and its repair: the editor's issues and the extra ones, fixed where a fix
is safe, reported where a person must decide."""
from __future__ import annotations

import copy

from app.sketch import read_sketch
from app.sketch_check import FIXABLE, check, repair, summary

from .test_sketches import API, new_sketch, two_rooms, wall


def broken() -> dict:
    s = two_rooms()
    f = s["floors"][0]
    f["nodes"].update({"s1": [1, 1], "s2": [1, 1.003], "x1": [0.5, 0.5], "x2": [1.5, 1.2], "y1": [3, 1], "y2": [3, 2.5],
                       "l1": [1, 2.8], "l2": [1, 2.2]})
    f["walls"].update({
        "short": wall("s1", "s2", 0.1, "partition"),                      # 3 mm long
        "twin": wall("a", "e"),                                            # the same as w1
        "cross": wall("x1", "x2", 0.1, "partition"),                       # crosses nothing? it does: w1? no — stands free
        "loose": wall("l1", "l2", 0.1, "partition"),                       # l1 is 5 cm from w5 (y = 3 − 0.125…), the end hangs
    })
    f["openings"].update({
        "off": {"wall": "w6", "kind": "window", "at": 2.9, "width": 1.0, "height": 1.5, "sill": 0.8, "hinge": "a", "side": "left"},
        "over": {"wall": "w3", "kind": "window", "at": 2.0, "width": 1.2, "height": 1.5, "sill": 0.8, "hinge": "a", "side": "left"},
        "tall": {"wall": "p", "kind": "passage", "at": 0.5, "width": 0.6, "height": 3.0, "sill": 0, "hinge": "a", "side": "left"},
    })
    f["openings"]["door"]["width"] = 0.7                                   # a narrow door
    f["rooms"].update({"r2": {"at": [3, 1.5], "name": "Склад", "number": "101", "type": None},   # the kitchen's number again
                       "stray": {"at": [9, 9], "name": "Нигде", "number": "", "type": None}})
    return s


def test_check_finds_everything():
    issues = check(read_sketch(broken()))
    by = {}
    for i in issues:
        by.setdefault(i["code"], []).append(i)
    assert set(by) >= {"short-wall", "twin-walls", "opening-off-wall", "openings-overlap", "opening-too-tall", "loose-end",
                       "duplicate-number", "narrow-door", "stray-label"}
    assert by["short-wall"][0]["ids"] == ["short"] and by["short-wall"][0]["level"] == "error"
    assert sorted(by["twin-walls"][0]["ids"]) == ["twin", "w1"]
    assert by["opening-off-wall"][0]["ids"] == ["off"]
    assert sorted(by["openings-overlap"][0]["ids"]) == ["over", "win"]
    assert by["opening-too-tall"][0]["ids"] == ["tall"] and by["opening-too-tall"][0]["level"] == "warning"
    loose = next(i for i in by["loose-end"] if i["ids"] == ["loose"])
    assert "см" in loose["message"]
    assert sorted(by["duplicate-number"][0]["ids"]) == ["r1", "r2"]
    assert by["stray-label"][0]["ids"] == ["stray"]
    assert all("at" in i and i["floor_id"] == "f1" for i in issues)


def test_repair_fixes_what_is_safe_and_leaves_the_rest():
    s = read_sketch(broken())
    fixed_sketch, fixed = repair(s)
    codes = {x["code"] for x in fixed}
    assert codes == {"short-wall", "twin-walls", "opening-off-wall", "openings-overlap", "opening-too-tall", "loose-end", "stray-label"}
    # the original is untouched; the result is still a plan
    assert "short" in s["floors"][0]["walls"]
    f = read_sketch(fixed_sketch)["floors"][0]
    assert "short" not in f["walls"] and "twin" not in f["walls"] and "stray" not in f["rooms"]
    assert f["openings"]["tall"]["height"] <= 2.7
    # the loose end now stands on a node of w5 (the wall was split there)
    loose = f["walls"]["loose"]
    assert f["nodes"][loose["a"]][1] == 3 or f["nodes"][loose["b"]][1] == 3
    left = {i["code"] for i in check(f and read_sketch(fixed_sketch))}
    assert left == {"duplicate-number", "narrow-door", "unnamed-room"} or left <= {"duplicate-number", "narrow-door", "unnamed-room", "crossing"}
    # a repair of one code only
    _, only = repair(read_sketch(broken()), ["stray-label"])
    assert [x["code"] for x in only] == ["stray-label"]


def test_bearing_walls_off_the_floor_below_and_the_summary():
    s = two_rooms()
    up = copy.deepcopy(s["floors"][0])
    up.update(id="f2", level=2, elevation=2.7, rooms={}, openings={})
    up["nodes"]["b"] = [4.5, 0]                        # the second floor's corner hangs half a metre out
    s["floors"].append(up)
    issues = check(read_sketch(s))
    off = [i for i in issues if i["code"] == "bearing-off"]
    assert {i["floor_id"] for i in off} == {"f2"} and {w for i in off for w in i["ids"]} == {"w2", "w3"}
    sm = summary(read_sketch(s))
    assert [f["level"] for f in sm["floors"]] == [1, 2]
    assert sm["floors"][0]["rooms"][0]["name"] in ("Кухня", "") and sm["floors"][0]["openings"] == {"door": 1, "window": 1}
    assert sm["floors"][1]["unnamed"] == 2


def test_fixable_is_what_repair_knows():
    assert set(FIXABLE) == {"short-wall", "twin-walls", "opening-off-wall", "openings-overlap", "opening-too-tall", "loose-end", "stray-label"}


async def test_check_and_repair_by_request(client, tokens):
    d = await new_sketch(client, tokens, name="Проверка")
    v0 = (await client.get(f"{API}/drawings/{d['id']}/sketch", headers=tokens.admin())).json()["version"]
    r = await client.put(f"{API}/drawings/{d['id']}/sketch", json={"sketch": broken(), "version": v0}, headers=tokens.admin())
    assert r.status_code == 200, r.text
    chk = (await client.get(f"{API}/drawings/{d['id']}/sketch/check", headers=tokens.admin())).json()
    assert chk["errors"] >= 4 and chk["warnings"] >= 4 and chk["version"] == v0 + 1
    assert "short-wall" in chk["fixable"] and chk["summary"]["floors"][0]["walls"] == 11
    rep = await client.post(f"{API}/drawings/{d['id']}/sketch/repair", json={}, headers=tokens.admin())
    assert rep.status_code == 200, rep.text
    body = rep.json()
    assert body["version"] == v0 + 1 and len(body["fixed"]) >= 7 and body["errors"] == 0
    # nothing was saved by the repair; the repaired plan is accepted by the save
    assert (await client.get(f"{API}/drawings/{d['id']}/sketch", headers=tokens.admin())).json()["version"] == v0 + 1
    r = await client.put(f"{API}/drawings/{d['id']}/sketch", json={"sketch": body["sketch"], "version": v0 + 1}, headers=tokens.admin())
    assert r.status_code == 200, r.text
    # a reader may check, not repair; a file drawing has no plan to check
    assert (await client.get(f"{API}/drawings/{d['id']}/sketch/check", headers=tokens.bearer("nobody"))).status_code in (403, 404)
