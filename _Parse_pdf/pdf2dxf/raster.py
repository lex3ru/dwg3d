"""Raster pages (scans, pictures inside a PDF): trace lines out of pixels.

Pipeline: render -> binarize -> skeletonize -> walk the skeleton into pixel paths
-> Douglas-Peucker simplification -> polylines. The result is approximate: curves
become polylines, text is not recognized.
"""
from __future__ import annotations

import math

import pymupdf

from .convert import Writer
from .geometry import Seg

MAX_SIDE_PX = 9000
_NEIGHBORS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]

PixelPath = list[tuple[int, int]]


def binarize(gray):
    """Ink mask. The paper level is estimated at large scale (fixes uneven scan lighting)
    so thin lines and solid areas up to ~30 mm both survive."""
    import cv2
    import numpy as np

    h, w = gray.shape
    small = cv2.resize(gray, (max(1, w // 8), max(1, h // 8)), interpolation=cv2.INTER_AREA)
    paper = cv2.dilate(small, np.ones((41, 41), np.uint8))
    paper = cv2.GaussianBlur(paper, (0, 0), 8)
    paper = cv2.resize(paper, (w, h), interpolation=cv2.INTER_LINEAR)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    return blur.astype(np.float32) < 0.75 * paper.astype(np.float32)


def _simple(p, pixels) -> bool:
    """True if p has >= 2 neighbours and they stay connected without p (p is redundant)."""
    ns = [(p[0] + dx, p[1] + dy) for dx, dy in _NEIGHBORS if (p[0] + dx, p[1] + dy) in pixels]
    if len(ns) < 2:
        return False
    seen = {ns[0]}
    stack = [ns[0]]
    while stack:
        a = stack.pop()
        for b in ns:
            if b not in seen and max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1:
                seen.add(b)
                stack.append(b)
    return len(seen) == len(ns)


def thin_corners(pixels: set[tuple[int, int]]) -> None:
    """Remove staircase / corner pixels so every line is a clean 8-connected chain."""
    for _ in range(2):
        for p in sorted(pixels):
            if _simple(p, pixels):
                pixels.discard(p)


def skeleton_paths(skel, min_len_px: float) -> list[tuple[PixelPath, bool]]:
    """Walk a 1-pixel-wide skeleton into paths. Returns (path, closed) pairs.

    Isolated specks and short spurs (< min_len_px with a free end) are dropped.
    """
    import numpy as np

    ys, xs = np.nonzero(skel)
    pixels = set(zip(xs.tolist(), ys.tolist()))
    thin_corners(pixels)
    nbrs = {p: [(p[0] + dx, p[1] + dy) for dx, dy in _NEIGHBORS if (p[0] + dx, p[1] + dy) in pixels] for p in pixels}
    is_node = {p: len(n) != 2 for p, n in nbrs.items()}
    seen: set[tuple[int, int]] = set()
    used: set[tuple] = set()
    out: list[tuple[PixelPath, bool]] = []

    def plen(path: PixelPath) -> float:
        return sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))

    for start in (p for p in pixels if is_node[p]):
        for first in nbrs[start]:
            if (start, first) in used:
                continue
            used.add((start, first))
            path = [start, first]
            prev, cur = start, first
            while not is_node[cur] and cur not in seen:
                seen.add(cur)
                nxt = [q for q in nbrs[cur] if q != prev]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
                path.append(cur)
            used.add((cur, prev))
            free_end = len(nbrs[start]) == 1 or len(nbrs[path[-1]]) == 1
            if free_end and plen(path) < min_len_px:
                continue
            if not free_end and len(path) <= 3:
                continue  # sub-pixel link inside a junction cluster
            out.append((path, False))

    for p in pixels:  # remaining pure loops
        if p in seen or is_node[p]:
            continue
        path = [p]
        seen.add(p)
        prev, cur = p, nbrs[p][0]
        while cur != p and cur not in seen:
            seen.add(cur)
            path.append(cur)
            nxt = [q for q in nbrs[cur] if q != prev]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
        path.append(p)
        if plen(path) >= min_len_px:
            out.append((path, True))
    return out


SOLID_MM = 1.5  # ink thicker than this is a filled area, not a pen stroke


def _solid_regions(ink, px_mm: float, writer: Writer):
    """Emit filled areas as HATCH and return the ink without them."""
    import cv2
    import numpy as np

    d = max(3, int(SOLID_MM / px_mm) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
    ink8 = ink.astype(np.uint8)
    solid = cv2.morphologyEx(ink8, cv2.MORPH_OPEN, kernel)
    if not solid.any():
        return ink
    k = px_mm * writer.opts.scale
    height = ink.shape[0]
    eps = max(1.0, writer.opts.simplify / px_mm)
    contours, hier = cv2.findContours(solid, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    layer = writer.layer((0, 0, 0), "F", None, writer.opts.fill_layer)
    tops: dict[int, list] = {}
    for i, c in enumerate(contours):
        parent = hier[0][i][3]
        pts = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(pts) < 3:
            continue
        xy = [((x + 0.5) * k, (height - y - 0.5) * k) for x, y in pts.tolist()]
        ring = [Seg(xy[j], xy[(j + 1) % len(xy)]) for j in range(len(xy))]
        tops.setdefault(i if parent < 0 else parent, []).append(ring)
    for rings in tops.values():
        writer.emit_hatch(rings, (0, 0, 0), layer, True)
    grown = cv2.dilate(solid, np.ones((5, 5), np.uint8))
    return ink & (grown == 0)


def convert_raster_page(page: pymupdf.Page, writer: Writer) -> None:
    try:
        import cv2
        import numpy as np
        from skimage.morphology import skeletonize
    except ImportError as e:  # pragma: no cover
        raise SystemExit(f"для растрового режима нужны opencv и scikit-image: {e}")

    opts = writer.opts
    report = writer.report
    dpi = opts.dpi
    longest_in = max(page.rect.width, page.rect.height) / 72.0
    if longest_in * dpi > MAX_SIDE_PX:
        dpi = int(MAX_SIDE_PX / longest_in)
        report.warnings.append(f"страница большая, разрешение снижено до {dpi} dpi")

    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    ink = binarize(gray)

    px_mm = 25.4 / dpi
    if opts.fills:
        ink = _solid_regions(ink, px_mm, writer)
    skel = skeletonize(ink).astype(np.uint8)

    paths = skeleton_paths(skel, opts.min_len / px_mm)
    eps = max(1.0, opts.simplify / px_mm)
    k = px_mm * opts.scale
    height = pix.height
    layer = writer.layer((0, 0, 0), "RASTER", "RASTER", opts.stroke_layer)
    attribs = {"layer": layer}

    for path, closed in paths:
        if closed and path[0] == path[-1]:
            path = path[:-1]
        arr = np.array(path, dtype=np.int32).reshape(-1, 1, 2)
        pts = cv2.approxPolyDP(arr, eps, closed).reshape(-1, 2)
        if len(pts) < 2:
            continue
        xy = [((x + 0.5) * k, (height - y - 0.5) * k) for x, y in pts.tolist()]
        chain = [Seg(xy[i], xy[i + 1]) for i in range(len(xy) - 1)]
        if closed:
            chain.append(Seg(xy[-1], xy[0]))
        writer.emit_chain(chain, attribs, closed)

    report.warnings.append(
        "растровый режим: геометрия приблизительная (кривые — ломаные), текст не распознаётся"
    )
