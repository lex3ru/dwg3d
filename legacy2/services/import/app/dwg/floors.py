"""Floor detection, naming, elevations and cross-floor alignment."""
from __future__ import annotations

import collections
import logging
import re
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Point, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .extract import Drawing

log = logging.getLogger(__name__)

STRUCT_ROLES = ("walls", "columns")

# ---------------------------------------------------------------- naming ---
_RE_LEVEL = [
    re.compile(r"(\d{1,3})\s*[-‐–]?\s*(?:г?о|й|ой|ий|ый)?\s*этаж", re.I),
    re.compile(r"этаж\w*\s*(?:№\s*)?(\d{1,3})", re.I),
    re.compile(r"(?:floor|level|storey|etage|geschoss)\s*[#№]?\s*(\d{1,3})", re.I),
    re.compile(r"(\d{1,3})\s*(?:st|nd|rd|th)?\s*(?:floor|level|storey)", re.I),
    re.compile(r"^\s*(?:L|ЭТ\.?|Эт\.?)\s*[-_]?(\d{1,3})\s*$", re.I),
]
_RE_BASEMENT = re.compile(r"подвал|basement|underground|подземн", re.I)
_RE_PLINTH = re.compile(r"цокол|souterrain|lower\s*ground", re.I)
_RE_TECH = re.compile(r"техн|чердак|мансард|attic|mansard|technical|mechanical", re.I)
_RE_ROOF = re.compile(r"кровл|крыш|roof", re.I)
_RE_PLAN = re.compile(r"план|plan|этаж|floor|level|подвал|кровл|roof|basement", re.I)
_RE_MARK = re.compile(r"^\s*([+\-±]?)\s*(\d{1,3})[.,](\d{3})\s*$")
_RE_HEIGHT = re.compile(
    r"(?:высота\s*этажа|h\s*эт\w*|floor\s*height|h\s*=)\s*[=:]?\s*(\d+(?:[.,]\d+)?)\s*(мм|mm|см|cm|м|m)?", re.I)


def parse_floor_name(text: str) -> tuple[int | None, str] | None:
    """-> (level, kind) or None if text doesn't look like a floor title.
    kind: floor | basement | tech | roof"""
    t = " ".join(text.split())
    if _RE_ROOF.search(t):
        return None, "roof"
    if _RE_BASEMENT.search(t):
        return -1, "basement"
    if _RE_PLINTH.search(t):
        return 0, "basement"
    if _RE_TECH.search(t):
        return None, "tech"
    for rx in _RE_LEVEL:
        if m := rx.search(t):
            return int(m.group(1)), "floor"
    return None


def parse_mark(text: str) -> float | None:
    """Elevation mark like "+4,150" / "-0,050" / "±0,000" (meters)."""
    m = _RE_MARK.match(text)
    if not m:
        return None
    v = int(m.group(2)) + int(m.group(3)) / 1000
    return -v if m.group(1) == "-" else v


def parse_height(text: str) -> float | None:
    m = _RE_HEIGHT.search(text)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "").lower()
    if unit in ("мм", "mm") or (not unit and v > 100):
        v /= 1000
    elif unit in ("см", "cm"):
        v /= 100
    return v if 1.8 <= v <= 20 else None


# ------------------------------------------------------------ candidates ---
@dataclass
class FloorCandidate:
    id: str
    source: str                        # cluster | layout | block | all
    bbox: tuple[float, float, float, float]
    space: str = "Model"
    owner: str | None = None
    name: str = ""
    title_source: str = ""
    level: int | None = None
    kind: str = "floor"
    include: bool = True
    marks: list[float] = field(default_factory=list)
    mark: float | None = None           # elevation read from the plan
    height_hint: float | None = None
    # resolved
    elevation: float | None = None
    height: float | None = None
    height_source: str = ""
    elevation_source: str = ""
    offset: tuple[float, float] = (0.0, 0.0)   # alignment shift (meters)
    alignment: str = ""
    n_shapes: int = 0
    manual: dict = field(default_factory=dict)

    def contains(self, item, margin: float = 0.0) -> bool:
        if item.space != self.space:
            return False
        if self.owner is not None:
            return item.owner == self.owner
        if self.source == "all":
            return True
        x, y = (item.x, item.y) if hasattr(item, "x") else item.center
        x0, y0, x1, y1 = self.bbox
        return x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source": self.source, "space": self.space, "owner": self.owner, "name": self.name,
            "title_source": self.title_source, "level": self.level, "kind": self.kind,
            "include": self.include, "bbox": [round(v, 3) for v in self.bbox],
            "mark": self.mark, "height_hint": self.height_hint,
            "elevation": self.elevation, "height": self.height,
            "elevation_source": self.elevation_source, "height_source": self.height_source,
            "offset": [round(v, 4) for v in self.offset], "alignment": self.alignment,
            "n_shapes": self.n_shapes,
        }


def _struct_shapes(d: Drawing, space="Model", owner=None):
    return [s for s in d.shapes if s.role in STRUCT_ROLES and s.space == space and s.owner == owner]


def _clusters(shapes, gap: float, min_ratio: float):
    """Group structural shapes into spatially separated plans."""
    if not shapes:
        return []
    boxes = []
    for s in shapes:
        x0, y0 = s.pts.min(axis=0)
        x1, y1 = s.pts.max(axis=0)
        boxes.append(box(x0, y0, x1, y1))
    g = gap / 2
    merged = unary_union([box(b.bounds[0] - g, b.bounds[1] - g, b.bounds[2] + g, b.bounds[3] + g) for b in boxes])
    comps = list(getattr(merged, "geoms", [merged]))
    tree = STRtree(comps)
    members = collections.defaultdict(list)
    for i, s in enumerate(shapes):
        members[int(tree.query(Point(s.pts[0]), predicate="intersects")[0])].append(i)
    weight = {k: sum(float(np.linalg.norm(np.diff(shapes[i].pts, axis=0), axis=1).sum()) for i in v)
              for k, v in members.items()}
    wmax = max(weight.values())
    big = [k for k in members if weight[k] >= min_ratio * wmax]
    out = []
    for k in big:
        idx = members[k]
        pts = np.vstack([shapes[i].pts for i in idx])
        out.append(((*pts.min(axis=0), *pts.max(axis=0)), len(idx)))
    # small clusters (details, legends) are dropped unless adjacent to a big one
    for k in set(members) - set(big):
        c = comps[k]
        near = min(big, key=lambda b: comps[b].distance(c))
        if comps[near].distance(c) < gap * 2:
            j = big.index(near)
            pts = np.vstack([shapes[i].pts for i in members[k]])
            bb = out[j][0]
            out[j] = ((min(bb[0], pts[:, 0].min()), min(bb[1], pts[:, 1].min()),
                       max(bb[2], pts[:, 0].max()), max(bb[3], pts[:, 1].max())), out[j][1] + len(members[k]))
    return out


def detect_candidates(d: Drawing, cfg: dict) -> list[FloorCandidate]:
    fc = cfg["floors"]
    mode = fc.get("mode", "auto")
    cands: list[FloorCandidate] = []

    def mk_bbox(shapes):
        pts = np.vstack([s.pts for s in shapes])
        return (*pts.min(axis=0), *pts.max(axis=0))

    if mode in ("auto", "blocks") and d.floor_blocks:
        for i, fb in enumerate(d.floor_blocks):
            sh = _struct_shapes(d, fb.space, fb.handle)
            if sh:
                c = FloorCandidate(f"b{i}", "block", mk_bbox(sh), fb.space, fb.handle, n_shapes=len(sh))
                c.name = fb.block
                for v in [fb.block, *fb.attribs.values()]:
                    if (p := parse_floor_name(v)) is not None:
                        c.level, c.kind = p
                        c.name, c.title_source = v, "block"
                        break
                for tag, v in fb.attribs.items():
                    if re.search(r"height|высот", tag, re.I):
                        c.height_hint = parse_height(f"h={v}")
                cands.append(c)
    if not cands and mode in ("auto", "layouts"):
        for lname in d.layouts:
            if lname == "Model":
                continue
            sh = _struct_shapes(d, lname)
            if len(sh) >= 10:
                c = FloorCandidate(f"l{len(cands)}", "layout", mk_bbox(sh), lname, n_shapes=len(sh), name=lname)
                cands.append(c)
        if len(cands) < 2 and mode == "auto":
            cands = []
    if not cands and mode != "single":
        sh = _struct_shapes(d)
        for bb, n in _clusters(sh, fc.get("cluster_gap", 4.0), fc.get("min_cluster_ratio", 0.2)):
            cands.append(FloorCandidate("", "cluster", bb, n_shapes=n))
        # reading order: rows top->bottom, then left->right
        if cands:
            hmax = max(c.bbox[3] - c.bbox[1] for c in cands)
            cands.sort(key=lambda c: (-round(c.bbox[3] / hmax), c.bbox[0]))
            for i, c in enumerate(cands):
                c.id = f"c{i}"
    if not cands:
        sh = _struct_shapes(d)
        if not sh:
            return []
        cands = [FloorCandidate("all", "all", mk_bbox(sh), n_shapes=len(sh))]

    _name_candidates(d, cands)
    _read_marks(d, cands)
    return cands


def _name_candidates(d: Drawing, cands):
    for c in cands:
        x0, y0, x1, y1 = c.bbox
        w, h = x1 - x0, y1 - y0
        if c.title_source:
            continue
        # 1) title text near/above the plan
        best = None
        for t in d.texts:
            if t.space != c.space or (c.owner and t.owner != c.owner):
                continue
            if not (x0 - 0.1 * w <= t.x <= x1 + 0.1 * w and y0 - 0.15 * h <= t.y <= y1 + 0.2 * h):
                continue
            if not _RE_PLAN.search(t.text):
                continue
            p = parse_floor_name(t.text)
            if p is None:
                continue
            # prefer texts that start with "план"/"plan" and sit high up
            score = (t.text.lower().lstrip().startswith(("план", "plan")), t.y)
            if best is None or score > best[0]:
                best = (score, t, p)
        if best:
            _, t, (lvl, kind) = best
            c.name, c.level, c.kind, c.title_source = " ".join(t.text.split()), lvl, kind, "text"
            continue
        # 2) paperspace layout whose viewport shows this plan
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for vp in d.viewports:
            vx0, vy0, vx1, vy1 = vp.bbox
            if vx0 <= cx <= vx1 and vy0 <= cy <= vy1:
                p = parse_floor_name(vp.layout)
                if p is not None:
                    c.name, (c.level, c.kind), c.title_source = vp.layout, p, "layout"
                    break
        if not c.title_source and c.source == "layout" and (p := parse_floor_name(c.space)):
            c.level, c.kind = p
            c.title_source = "layout"
    for c in cands:
        if c.kind == "roof":
            c.include = False
        if not c.name:
            c.name = f"Этаж ({c.id})"


def _read_marks(d: Drawing, cands):
    for c in cands:
        for t in d.texts:
            if not c.contains(t):
                continue
            if (v := parse_mark(t.text)) is not None:
                c.marks.append(v)
            elif c.height_hint is None and (h := parse_height(t.text)):
                c.height_hint = h
        if c.marks:
            cnt = collections.Counter(round(v, 3) for v in c.marks)
            top = cnt.most_common()
            best_n = top[0][1]
            ties = [v for v, n in top if n == best_n]
            c.mark = min(ties, key=abs) if len(ties) > 1 else ties[0]


# ------------------------------------------------------------- stacking ---
def apply_manual(cands, cfg):
    by_id = {c.id: c for c in cands}
    for item in cfg["floors"].get("items") or []:
        c = by_id.get(str(item.get("candidate", "")))
        if not c:
            log.warning("floors.items: unknown candidate %r", item.get("candidate"))
            continue
        c.manual = dict(item)
        for k in ("name", "level", "include", "kind"):
            if k in item and item[k] is not None:
                setattr(c, k, item[k])


def _choose_marks(floors):
    """A plan carries many marks (stair landings, pits...). The floor level is
    normally the most frequent one; ties are broken by picking the value that
    splits the gap between the neighbouring floors most evenly."""
    M = [collections.Counter(round(v, 3) for v in c.marks) for c in floors]
    chosen: list[float | None] = [None] * len(floors)
    ties: dict[int, list[float]] = {}
    for i, cnt in enumerate(M):
        if not cnt:
            continue
        top = max(cnt.values())
        best = [v for v, n in cnt.items() if n == top]
        if len(best) == 1:
            chosen[i] = best[0]
        else:
            ties[i] = best
    for i, best in ties.items():
        prev = next((chosen[j] for j in range(i - 1, -1, -1) if chosen[j] is not None), None)
        nxt = next((chosen[j] for j in range(i + 1, len(M)) if chosen[j] is not None), None)
        if prev is not None and nxt is not None:
            chosen[i] = min(best, key=lambda v: abs((v - prev) - (nxt - v)))
        else:
            chosen[i] = min(best, key=abs)
    for c, v in zip(floors, chosen):
        c.mark = v


def resolve_stack(cands, cfg) -> list[FloorCandidate]:
    """Assign level order, elevations and heights to included floors."""
    b = cfg["building"]
    default_h = float(b["floor_height"])
    floors = [c for c in cands if c.include]
    if not floors:
        return []
    known = [c.level for c in floors if c.level is not None]
    top = max(known) if known else 0
    for c in sorted([c for c in floors if c.level is None], key=lambda c: (c.kind != "tech", c.bbox[0])):
        top += 1
        c.level = top
    floors.sort(key=lambda c: (c.level, c.bbox[0]))

    use_marks = b.get("use_elevation_marks", True)
    _choose_marks(floors)
    marks = [c.mark if use_marks else None for c in floors]
    # keep only marks that increase with level
    last = None
    for i, m in enumerate(marks):
        if m is None:
            continue
        if last is not None and not (1.8 <= m - last <= 25):
            marks[i] = None
            continue
        last = m

    n = len(floors)
    heights, hsrc = [None] * n, [""] * n
    for i, c in enumerate(floors):
        if c.manual.get("height"):
            heights[i], hsrc[i] = float(c.manual["height"]), "manual"
        elif c.height_hint:
            heights[i], hsrc[i] = c.height_hint, "text"
        elif i + 1 < n and marks[i] is not None and marks[i + 1] is not None:
            dh = marks[i + 1] - marks[i]
            if 1.8 <= dh <= 25:
                heights[i], hsrc[i] = dh, "marks"
    mark_h = [h for h, s in zip(heights, hsrc) if s == "marks"]
    fill = float(np.median(mark_h)) if mark_h else default_h
    for i in range(n):
        if heights[i] is None:
            heights[i], hsrc[i] = (fill, "marks-median") if mark_h else (default_h, "default")

    elev = [None] * n
    esrc = [""] * n
    for i, c in enumerate(floors):
        if c.manual.get("elevation") is not None:
            elev[i], esrc[i] = float(c.manual["elevation"]), "manual"
        elif marks[i] is not None:
            elev[i], esrc[i] = marks[i], "mark"
    if all(e is None for e in elev):
        anchor = next((i for i, c in enumerate(floors) if c.level == 1), 0)
        elev[anchor], esrc[anchor] = 0.0, "anchor"
    first = next(i for i, e in enumerate(elev) if e is not None)
    for i in range(first + 1, n):
        if elev[i] is None:
            elev[i], esrc[i] = elev[i - 1] + heights[i - 1], "stacked"
    for i in range(first - 1, -1, -1):
        if elev[i] is None:
            elev[i], esrc[i] = elev[i + 1] - heights[i], "stacked"
    for i, c in enumerate(floors):
        c.elevation, c.height = round(elev[i], 4), round(heights[i], 4)
        c.elevation_source, c.height_source = esrc[i], hsrc[i]
    return floors


# ------------------------------------------------------------ alignment ---
def _grid_features(d: Drawing, c: FloorCandidate):
    """Vertical / horizontal axis positions, labelled where a bubble is found."""
    V, H = {}, {}
    Vu, Hu = [], []
    # axis bubbles sit outside the plan outline
    bubbles = [bb for bb in d.bubbles if c.contains(bb, margin=3.0)]
    for s in d.shapes:
        if s.role != "grid" or not c.contains(s, margin=1.0) or len(s.pts) != 2:
            continue
        (xa, ya), (xb, yb) = s.pts
        dx, dy = xb - xa, yb - ya
        L = np.hypot(dx, dy)
        if L < 1.0:
            continue
        vertical = abs(dx) < 0.01 * L
        horizontal = abs(dy) < 0.01 * L
        if not (vertical or horizontal):
            continue
        label = None
        for bb in bubbles:
            for (px, py) in s.pts:
                if bb.label and np.hypot(px - bb.x, py - bb.y) <= max(bb.r * 1.6, 0.3):
                    label = bb.label
        pos = (xa + xb) / 2 if vertical else (ya + yb) / 2
        (Vu if vertical else Hu).append(pos)
        if label:
            (V if vertical else H)[label] = pos
    cols = [s.center for s in d.shapes if s.role == "columns" and c.contains(s)]
    return V, H, Vu, Hu, cols


def _vote_shift(a: list[float], b: list[float], tol: float, prior: float) -> tuple[float, int]:
    """Shift t maximizing |{x in b : x + t ≈ some y in a}|."""
    a = np.unique(np.round(a, 3))
    b = np.unique(np.round(b, 3))
    if len(a) == 0 or len(b) == 0:
        return prior, 0
    cand = (a[:, None] - b[None, :]).ravel()
    best, best_s = prior, 0
    for t in np.unique(np.round(cand, 2)):
        s = int(np.sum(np.min(np.abs(a[:, None] - (b[None, :] + t)), axis=0) < tol))
        if s > best_s or (s == best_s and abs(t - prior) < abs(best - prior)):
            best, best_s = float(t), s
    # refine: mean residual of matched features
    res = [ai - (bi + best) for bi in b for ai in a if abs(ai - (bi + best)) < tol]
    return best + (float(np.mean(res)) if res else 0.0), best_s


def align_floors(d: Drawing, floors: list[FloorCandidate], cfg: dict):
    mode = cfg["floors"].get("alignment", "auto")
    for c in floors:
        c.offset, c.alignment = (0.0, 0.0), "none"
    if mode == "none" or len(floors) < 2 or all(c.source in ("block", "all") for c in floors):
        for c in floors:
            c.alignment = "shared-coordinates"
        return
    feats = {c.id: _grid_features(d, c) for c in floors}
    ref = next((c for c in floors if c.level == 1 and c.kind == "floor"), None) or \
        max(floors, key=lambda c: len(feats[c.id][2]) + len(feats[c.id][3]))
    rV, rH, rVu, rHu, rcols = feats[ref.id]
    rcx, rcy = (ref.bbox[0] + ref.bbox[2]) / 2, (ref.bbox[1] + ref.bbox[3]) / 2
    for c in floors:
        if c is ref:
            c.alignment = "reference"
            continue
        V, H, Vu, Hu, cols = feats[c.id]
        cx, cy = (c.bbox[0] + c.bbox[2]) / 2, (c.bbox[1] + c.bbox[3]) / 2
        prior = (rcx - cx, rcy - cy)
        dx = dy = None
        how = []
        if mode in ("auto", "grid"):
            cv = [rV[k] - V[k] for k in V.keys() & rV.keys()]
            ch = [rH[k] - H[k] for k in H.keys() & rH.keys()]
            if len(cv) >= 2 and np.ptp(cv) < 0.1:
                dx = float(np.median(cv)); how.append(f"grid-labels x({len(cv)})")
            if len(ch) >= 2 and np.ptp(ch) < 0.1:
                dy = float(np.median(ch)); how.append(f"grid-labels y({len(ch)})")
        if mode in ("auto", "grid", "features"):
            if dx is None:
                a = rVu + [p[0] for p in rcols]
                bb = Vu + [p[0] for p in cols]
                t, s = _vote_shift(a, bb, 0.06, prior[0])
                if s >= 3:
                    dx = t; how.append(f"features x({s})")
            if dy is None:
                a = rHu + [p[1] for p in rcols]
                bb = Hu + [p[1] for p in cols]
                t, s = _vote_shift(a, bb, 0.06, prior[1])
                if s >= 3:
                    dy = t; how.append(f"features y({s})")
        if dx is None:
            dx = prior[0]; how.append("bbox x")
        if dy is None:
            dy = prior[1]; how.append("bbox y")
        man = c.manual.get("offset") or [0, 0]
        c.offset = (dx + float(man[0]), dy + float(man[1]))
        c.alignment = ", ".join(how)
