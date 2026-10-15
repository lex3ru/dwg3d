"""A variant laid over the fact: the objects of the building as they would be, and two such states compared.

Pure functions over plain dicts: the fact is the objects as the assets service shows them, the operations
are rows of `variant_ops`. An object of the result is keyed `asset:<id>` (an existing object) or `new:<op id>`.
"""
from __future__ import annotations

PLACE = ("floor_id", "x", "y", "angle")
LABEL = {"floor_id": "этаж", "x": "место", "y": "место", "angle": "поворот", "note": "примечание", "props": "свойства"}


def key_of(asset_id) -> str:
    return f"asset:{asset_id}"


def fact_objects(fact: list[dict]) -> dict[str, dict]:
    return {key_of(a["id"]): {"key": key_of(a["id"]), "asset_id": a["id"], "op_id": None, "type_id": a["type_id"],
                              "type_name": a.get("type_name", ""), "product_id": a.get("product_id"),
                              "product_name": a.get("product_name") or "", "floor_id": a["floor_id"], "room_id": a.get("room_id"),
                              "x": a["x"], "y": a["y"], "angle": a.get("angle") or 0, "note": a.get("note") or "",
                              "props": a.get("props") or {}, "inventory_no": a.get("inventory_no"),
                              "version": a.get("version"), "change": None, "removed": False, "conflict": None}
            for a in fact if a.get("x") is not None and not a.get("container_id")}


def lay(fact: list[dict], ops: list[dict]) -> dict[str, dict]:
    """The objects with the operations of a variant applied (removed ones kept, marked)."""
    out = fact_objects(fact)
    for op in sorted(ops, key=lambda o: (o["sort"], str(o["id"]))):
        d = op["data"] or {}
        if op["op"] == "add":
            k = f"new:{op['id']}"
            out[k] = {"key": k, "asset_id": None, "op_id": str(op["id"]), "type_id": d.get("type_id"),
                      "type_name": d.get("type_name", ""), "product_id": d.get("product_id"),
                      "product_name": d.get("product_name") or "", "floor_id": d.get("floor_id"), "room_id": None,
                      "x": d.get("x"), "y": d.get("y"), "angle": d.get("angle") or 0, "note": d.get("note") or "",
                      "props": d.get("props") or {}, "inventory_no": d.get("inventory_no"), "version": None,
                      "change": "added", "removed": False, "conflict": None}
            continue
        k = key_of(op["asset_id"])
        o = out.get(k)
        if o is None:                                       # the object is gone from the fact
            out[f"gone:{op['id']}"] = {"key": f"gone:{op['id']}", "asset_id": str(op["asset_id"]), "op_id": str(op["id"]),
                                       "type_id": None, "type_name": "", "product_id": None, "product_name": "",
                                       "floor_id": None, "x": None, "y": None,
                                       "angle": 0, "note": "", "props": {}, "inventory_no": None, "version": None,
                                       "change": op["op"], "removed": True, "conflict": "gone"}
            continue
        if op.get("base_version") is not None and o["version"] is not None and op["base_version"] != o["version"]:
            o["conflict"] = "changed"
        if op["op"] == "move":
            o.update({k2: d[k2] for k2 in PLACE if k2 in d})
            o["change"] = o["change"] or "moved"
        elif op["op"] == "change":
            if "note" in d:
                o["note"] = d["note"]
            if "props" in d:
                o["props"] = {**o["props"], **d["props"]}
            o["change"] = "moved" if o["change"] == "moved" else "changed"
        elif op["op"] == "remove":
            o["removed"], o["change"] = True, "removed"
    return out


def compare(a: dict[str, dict], b: dict[str, dict], types: dict[str, dict], products: dict[str, dict] | None = None) -> dict:
    """What `b` adds, removes, moves and changes against `a`, and the specification of both with prices: a line
    per type and make and model, priced by the product's list price when it is named, else by the type's estimate."""
    products = products or {}
    objects, counts = [], {"added": 0, "removed": 0, "moved": 0, "changed": 0, "same": 0}
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        here_a = x is not None and not x["removed"] and x["x"] is not None
        here_b = y is not None and not y["removed"] and y["x"] is not None
        if not here_a and not here_b:
            continue
        what: list[str] = []
        if here_b and not here_a:
            change = "added"
        elif here_a and not here_b:
            change = "removed"
        else:
            moved = [f for f in PLACE if x[f] != y[f]]
            changed = [f for f in ("note", "props") if x[f] != y[f]]
            what = sorted({LABEL[f] for f in moved + changed})
            change = "moved" if moved else "changed" if changed else None
        if change is None:
            counts["same"] += 1
            continue
        counts[change] += 1
        o = y if here_b else x
        objects.append({"key": k, "change": change, "what": what, "asset_id": o["asset_id"], "op_id": o["op_id"],
                        "type_id": o["type_id"], "name": types.get(o["type_id"] or "", {}).get("name") or o["type_name"],
                        "inventory_no": o["inventory_no"], "floor_id": o["floor_id"], "at": [o["x"], o["y"]],
                        "from": {"floor_id": x["floor_id"], "at": [x["x"], x["y"]]} if change == "moved" else None})
    qty: dict[tuple[str, str], list[int]] = {}
    names: dict[tuple[str, str], str] = {}
    for side, objs in ((0, a), (1, b)):
        for o in objs.values():
            if not o["removed"] and o["x"] is not None and o["type_id"]:
                k = (o["type_id"], o.get("product_id") or "")
                qty.setdefault(k, [0, 0])[side] += 1
                names.setdefault(k, o.get("product_name") or "")
    items, totals = [], {}
    for (tid, pid), (qa, qb) in sorted(qty.items(), key=lambda kv: (types.get(kv[0][0], {}).get("name", ""), kv[0][1])):
        t, p = types.get(tid, {}), products.get(pid, {})
        product = f"{p.get('vendor') or ''} {p.get('name') or ''}".strip() if p else names[(tid, pid)]
        price = p.get("price") if p and p.get("price") is not None else t.get("price")
        cur = (p.get("currency") if p and p.get("price") is not None else t.get("currency")) or "RUB"
        row = {"type_id": tid, "product_id": pid or None, "name": t.get("name", "?"), "product": product,
               "category_id": t.get("category_id"), "price": price, "currency": cur, "qty_a": qa, "qty_b": qb, "delta": qb - qa}
        if price is not None:
            row.update(sum_a=round(price * qa, 2), sum_b=round(price * qb, 2))
            tot = totals.setdefault(cur, {"a": 0.0, "b": 0.0, "delta": 0.0})
            tot["a"] += row["sum_a"]
            tot["b"] += row["sum_b"]
            tot["delta"] = round(tot["b"] - tot["a"], 2)
        items.append(row)
    return {"counts": counts, "objects": objects, "items": items, "totals": totals}
