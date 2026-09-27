"""Drawing units detection -> scale factor to meters."""
from __future__ import annotations

import math

import numpy as np

UNIT_SCALE = {"mm": 0.001, "cm": 0.01, "dm": 0.1, "m": 1.0, "in": 0.0254, "ft": 0.3048}
# $INSUNITS codes (DXF reference)
INSUNITS = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m", 14: "dm"}


def _sample_wall_lengths(doc, mapper, limit=20000):
    lengths, xs, ys, segs = [], [], [], []
    for e in doc.modelspace():
        if len(lengths) >= limit:
            break
        if e.dxftype() != "LINE":
            continue
        role = mapper.layer_role(e.dxf.layer)
        if role not in ("walls", None):
            continue
        s, t = e.dxf.start, e.dxf.end
        L = math.hypot(t.x - s.x, t.y - s.y)
        if L > 0:
            lengths.append(L)
            xs += [s.x, t.x]
            ys += [s.y, t.y]
            if role == "walls":
                segs.append((s.x, s.y, t.x, t.y))
    return np.array(lengths), np.array(xs), np.array(ys), np.array(segs).reshape(-1, 4)


def wall_thickness_estimate(segs: np.ndarray, limit=3000) -> float | None:
    """Median distance from each axis-parallel wall line to its nearest
    parallel, overlapping neighbour ~ typical wall thickness (drawing units)."""
    out = []
    for axis in (0, 1):   # 0: horizontal lines (offset = y), 1: vertical (offset = x)
        d = segs[:, 2:] - segs[:, :2]
        L = np.hypot(d[:, 0], d[:, 1])
        ok = np.abs(d[:, 1 - axis]) <= 0.01 * L if axis == 0 else np.abs(d[:, 0]) <= 0.01 * L
        g = segs[ok][:limit]
        if len(g) < 2:
            continue
        if axis == 0:
            off = (g[:, 1] + g[:, 3]) / 2
            lo, hi = np.minimum(g[:, 0], g[:, 2]), np.maximum(g[:, 0], g[:, 2])
        else:
            off = (g[:, 0] + g[:, 2]) / 2
            lo, hi = np.minimum(g[:, 1], g[:, 3]), np.maximum(g[:, 1], g[:, 3])
        dist = np.abs(off[:, None] - off[None, :])
        overlap = np.minimum(hi[:, None], hi[None, :]) - np.maximum(lo[:, None], lo[None, :])
        dist[(overlap <= 0) | (dist <= 1e-9)] = np.inf
        m = dist.min(axis=1)
        out += m[np.isfinite(m)].tolist()
    return float(np.median(out)) if len(out) >= 4 else None


def guess_units(doc, mapper) -> str:
    """Heuristic: pick the unit under which typical wall segments and the
    overall extent look like a building (segments 0.3..6 m, extent 5..400 m)."""
    L, xs, ys, segs = _sample_wall_lengths(doc, mapper)
    if len(L) < 10:
        return "mm"
    med = float(np.median(L))
    thick = wall_thickness_estimate(segs) if len(segs) else None
    ext = max(np.percentile(xs, 98) - np.percentile(xs, 2), np.percentile(ys, 98) - np.percentile(ys, 2))

    def penalty(s):
        p = 0.0
        checks = [(med * s, 0.3, 6.0, 1.0), (ext * s, 5.0, 400.0, 1.0)]
        if thick:
            checks.append((thick * s, 0.05, 0.8, 3.0))   # the strongest cue
        for v, lo, hi, w in checks:
            if v < lo:
                p += w * math.log(lo / v)
            elif v > hi:
                p += w * math.log(v / hi)
        return p

    # prefer metric, mm first (most common in architectural DWGs)
    order = ["mm", "cm", "m", "in", "ft", "dm"]
    return min(order, key=lambda u: (round(penalty(UNIT_SCALE[u]), 3), order.index(u)))


def resolve_scale(doc, units_cfg: str, mapper) -> tuple[float, str, str]:
    """Returns (scale_to_meters, unit_name, source)."""
    u = (units_cfg or "auto").lower()
    if u in UNIT_SCALE:
        return UNIT_SCALE[u], u, "config"
    code = doc.header.get("$INSUNITS", 0)
    if code in INSUNITS:
        name = INSUNITS[code]
        return UNIT_SCALE[name], name, "header"
    name = guess_units(doc, mapper)
    return UNIT_SCALE[name], name, "heuristic"
