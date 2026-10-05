"""2D debug rendering of reconstructed plans (matplotlib -> PNG)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
import numpy as np  # noqa: E402

from .geometry import FloorPlan, _polys  # noqa: E402

OPENING_COLORS = {"door": "#d9480f", "window": "#1c7ed6", "vitrage": "#15aabf", "passage": "#ae3ec9"}


def _patch(poly, **kw):
    verts, codes = [], []
    for ring in [poly.exterior, *poly.interiors]:
        c = np.asarray(ring.coords)
        verts += c.tolist()
        codes += [MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY]
    return PathPatch(MPath(verts, codes), **kw)


def plot_plan(plan: FloorPlan, path, title="", show_lines=True, size=14):
    fig, ax = plt.subplots(figsize=(size, size), dpi=90)
    for p in _polys(plan.footprint):
        ax.add_patch(_patch(p, fc="#f1f3f5", ec="none"))
    cmap = plt.get_cmap("Pastel2")
    for i, r in enumerate(plan.rooms):
        ax.add_patch(_patch(r.poly, fc=cmap(i % 8), ec="none", alpha=0.8))
        if r.name:
            c = r.poly.representative_point()
            ax.text(c.x, c.y, r.name, fontsize=6, ha="center", va="center")
    for p in _polys(plan.wall_parts.get("wall", plan.walls)):
        ax.add_patch(_patch(p, fc="#343a40", ec="#000", lw=0.3))
    for p in _polys(plan.wall_parts.get("partition")):
        ax.add_patch(_patch(p, fc="#5c7cfa", ec="#000", lw=0.3))
    for st in plan.stairs:
        for t in st.treads:
            ax.add_patch(_patch(t, fc="#ffe066", ec="#e67700", lw=0.3))
    for p in _polys(plan.columns):
        ax.add_patch(_patch(p, fc="#868e96", ec="#000", lw=0.3))
    for o in plan.openings:
        ax.add_patch(_patch(o.poly, fc=OPENING_COLORS.get(o.kind, "#868e96"), ec="none", alpha=0.85))
        for h, t in o.leaves:
            ax.plot([h[0], t[0]], [h[1], t[1]], color="#d9480f", lw=1.2)
    if show_lines and plan.debug.get("segments"):
        ax.add_collection(LineCollection([np.asarray(s.coords) for s in plan.debug["segments"]],
                                         colors="#fa5252", linewidths=0.25, alpha=0.6))
    ax.set_aspect("equal")
    ax.autoscale()
    ax.set_title(f"{title}\n{plan.stats}", fontsize=8)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_overlay(plans: list[tuple[str, FloorPlan]], path):
    """All floors' walls overlaid (checks cross-floor alignment)."""
    fig, ax = plt.subplots(figsize=(14, 14), dpi=90)
    cmap = plt.get_cmap("tab20")
    for i, (name, plan) in enumerate(plans):
        first = True
        for p in _polys(plan.walls):
            for ring in [p.exterior, *p.interiors]:
                c = np.asarray(ring.coords)
                ax.plot(c[:, 0], c[:, 1], color=cmap(i % 20), lw=0.5, label=name if first else None)
                first = False
    handles, labels = ax.get_legend_handles_labels()
    uniq = dict(zip(labels, handles))
    ax.legend(uniq.values(), uniq.keys(), fontsize=7, loc="upper right")
    ax.set_aspect("equal")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
