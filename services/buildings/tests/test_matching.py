"""The set of five pairs «drawing before — drawing after» with the right answer known (docs/ACCEPTANCE.md, 9.2):
unchanged rooms are recognised (at least 95 %), and no room of the new drawing is taken for one it is not.

A floor of a hospital wing is generated: a corridor and rooms of different widths on both sides of it,
partitions 12–20 cm. Each pair changes it the way new revisions of drawings do."""
from __future__ import annotations

import random
from types import SimpleNamespace

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from app.publish import match_rooms


def floor(seed: int) -> list[dict]:
    rnd = random.Random(seed)
    rooms, n = [], 101
    for y0, y1 in ((0.3, 8.9), (11.1, 19.7)):                   # south and north rows
        x = 0.3
        while x < 70:
            w = rnd.choice((3.0, 3.6, 4.2, 4.8, 6.0, 7.2))
            rooms.append({"name": str(n), "poly": box(x, y0, min(x + w, 70.0), y1)})
            x += w + rnd.choice((0.12, 0.15, 0.2))
            n += 1
    rooms.append({"name": "Коридор", "poly": box(0.3, 9.1, 70.0, 10.9)})
    return rooms


def jitter(poly: Polygon, rnd: random.Random, d: float = 0.03) -> Polygon:
    return Polygon([(x + rnd.uniform(-d, d), y + rnd.uniform(-d, d)) for x, y in poly.exterior.coords[:-1]])


def plan(rooms: list[dict]) -> list[dict]:
    return [{"name": r["name"], "poly": [[list(p) for p in r["poly"].exterior.coords]]} for r in rooms]


def old_rows(rooms: list[dict]) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=i, name=r["name"], polygon=[[list(p) for p in r["poly"].exterior.coords]])
            for i, r in enumerate(rooms)]


def pairs():
    """(title, rooms before, rooms after, truth: for each room after — the rooms before it may continue)."""
    base = floor(1)
    rnd = random.Random(2)

    after = [{**r, "poly": jitter(r["poly"], rnd)} for r in base]
    yield "перестроен без изменений, вершины сдвинуты до 3 см", base, after, [{i} for i in range(len(base))]

    after = [{"name": f"Б-{i}", "poly": jitter(r["poly"], rnd)} for i, r in enumerate(base)]
    after.reverse()                                              # another order in the file as well
    yield "все помещения переименованы и перечислены в другом порядке", base, after, \
        [{len(base) - 1 - i} for i in range(len(base))]

    after, truth = [], []
    split, deleted = {3, 11, 20}, {6, 15}
    for i, r in enumerate(base):
        if i in deleted:
            continue
        p = jitter(r["poly"], rnd)
        if i in split:
            x0, y0, x1, y1 = p.bounds
            cut = x0 + (x1 - x0) * 0.45
            for part in (box(x0, y0, cut - 0.06, y1), box(cut + 0.06, y0, x1, y1)):
                after.append({"name": r["name"], "poly": part})
                truth.append({i})                                # either part may carry the room on
            continue
        after.append({"name": "Ординаторская" if i == 8 else r["name"], "poly": p})
        truth.append({i})
    yield "три разделены, два удалены, одно переименовано", base, after, truth

    after, truth, skip = [], [], set()
    for a, b in ((4, 5), (17, 18)):                              # the wall between two neighbours removed
        merged = unary_union([base[a]["poly"], base[b]["poly"]]).buffer(0.15).buffer(-0.15)
        after.append({"name": base[a]["name"], "poly": merged})
        truth.append({a, b})
        skip |= {a, b}
    moved = (9, 10)                                              # the partition between two moved by 40 cm
    for i, r in enumerate(base):
        if i in skip:
            continue
        p = r["poly"]
        if i in moved:
            x0, y0, x1, y1 = p.bounds
            p = box(x0, y0, x1 + 0.4, y1) if i == moved[0] else box(x0 + 0.4, y0, x1, y1)
        after.append({"name": r["name"], "poly": jitter(p, rnd)})
        truth.append({i})
    yield "две пары объединены, одна перегородка сдвинута на 40 см", base, after, truth

    after = [{**r, "poly": jitter(r["poly"], rnd)} for r in base]
    after[2]["name"], after[12]["name"] = base[12]["name"], base[2]["name"]       # names swapped by mistake
    truth = [{i} for i in range(len(base))]
    for k in range(2):                                           # a new annex: rooms nobody had before
        after.append({"name": base[k]["name"], "poly": box(72 + k * 5, 0.3, 76.8 + k * 5, 8.9)})
        truth.append(set())
    yield "имена двух перепутаны, пристроены два новых помещения", base, after, truth


def test_five_pairs_with_known_answers():
    report = []
    for title, before, after, truth in pairs():
        got = match_rooms(plan(after), old_rows(before))
        unchanged = [k for k, t in enumerate(truth) if len(t) == 1 and sum(1 for x in truth if x == t) == 1]
        recognised = sum(1 for k in unchanged if k in got and got[k].id in truth[k])
        false = [(k, got[k].id) for k in got if got[k].id not in truth[k]]
        share = recognised / len(unchanged)
        report.append(f"{title}: узнано {recognised} из {len(unchanged)} ({share:.0%}), ложных {len(false)}")
        assert share >= 0.95, report[-1]
        assert false == [], report[-1]
    print("\n".join(report))
