"""Совмещение этажей одного здания. На листе чертежа планы этажей лежат рядом, каждый в
своём месте; в здании они должны стоять друг над другом. Сдвиг каждого этажа находится
голосованием: колонны (а без них — узлы несущих стен) этажа и опорного этажа сравниваются
попарно, и сдвиг, при котором совпадает больше всего, — верный. Не нашлось совпадений —
этаж ставится центром к центру опорного."""

import math
from collections import Counter

from app.modules.building.plan import Plan

Pt = tuple[float, float]
BIN = 25.0  # мм: точность голосования
TOL = 60.0  # мм: точки ближе — совпали


def features(plan: Plan) -> tuple[list[Pt], list[Pt]]:
    columns = [(c.x, c.y) for c in plan.columns]
    nodes = sorted({plan.nodes[n] for w in plan.walls if w.kind == "bearing"
                    for n in (w.a, w.b) if n in plan.nodes})
    return columns, list(nodes)


def bbox(plan: Plan) -> tuple[float, float, float, float] | None:
    pts = list(plan.nodes.values()) + [(c.x, c.y) for c in plan.columns]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _vote(ref: list[Pt], part: list[Pt], need: int) -> Pt | None:
    if not ref or not part:
        return None
    votes: Counter[tuple[int, int]] = Counter()
    for r in ref:
        for p in part:
            votes[(round((r[0] - p[0]) / BIN), round((r[1] - p[1]) / BIN))] += 1
    (bx, by), _ = votes.most_common(1)[0]
    dx, dy = bx * BIN, by * BIN
    # уточнение и проверка: сколько точек этажа легло на опорные
    matched = [(r[0] - p[0], r[1] - p[1]) for p in part for r in ref
               if math.dist((p[0] + dx, p[1] + dy), r) <= TOL]
    if len(matched) < need:
        return None
    return (sum(m[0] for m in matched) / len(matched), sum(m[1] for m in matched) / len(matched))


def shift(ref: Plan, plan: Plan) -> tuple[Pt, str]:
    """Сдвиг plan к ref и чем он найден: «колонны», «стены», «по центру»."""
    rc, rn = features(ref)
    pc, pn = features(plan)
    found = _vote(rc, pc, max(3, int(0.3 * min(len(rc), len(pc)))))
    if found:
        return found, "колонны"
    found = _vote(rn, pn, max(8, int(0.25 * min(len(rn), len(pn)))))
    if found:
        return found, "стены"
    a, b = bbox(ref), bbox(plan)
    if a is None or b is None:
        return (0.0, 0.0), "по центру"
    return (((a[0] + a[2]) - (b[0] + b[2])) / 2, ((a[1] + a[3]) - (b[1] + b[3])) / 2), "по центру"


def translate(plan: Plan, dx: float, dy: float) -> None:
    plan.nodes = {k: (round(x + dx, 1), round(y + dy, 1)) for k, (x, y) in plan.nodes.items()}
    for c in plan.columns:
        c.x, c.y = round(c.x + dx, 1), round(c.y + dy, 1)
    for s in plan.stairs:
        s.x, s.y = round(s.x + dx, 1), round(s.y + dy, 1)
    for r in plan.rooms:
        r.x, r.y = round(r.x + dx, 1), round(r.y + dy, 1)
    if plan.underlay:
        plan.underlay.x += dx
        plan.underlay.y += dy


def merged(plans: list[Plan]) -> Plan:
    """Опорный «этаж» из нескольких: все их колонны и несущие стены."""
    out = Plan()
    for i, p in enumerate(plans):
        out.nodes.update({f"{i}:{k}": v for k, v in p.nodes.items()})
        out.walls += [w.model_copy(update={"id": f"{i}:{w.id}", "a": f"{i}:{w.a}",
                                           "b": f"{i}:{w.b}"}) for w in p.walls]
        out.columns += p.columns
    return out
