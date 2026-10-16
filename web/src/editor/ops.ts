// Правка плана: чистые функции над документом (мутируют переданный черновик).

import {
  centerline, dist, newId, pointAt, polylineLength, projectOnPolyline, type Plan, type Pt, type Wall,
} from "./plan";
import type { Sel, Snaps } from "./store";

export interface Hit {
  wall: Wall;
  s: number; // мм от начала стены
  p: Pt;
  d: number;
  length: number;
}

export function nodeAt(plan: Plan, p: Pt, tol: number, exclude: Set<string> = new Set()): string | null {
  let best: string | null = null;
  let bestD = tol;
  for (const [id, q] of Object.entries(plan.nodes)) {
    if (exclude.has(id)) continue;
    const d = dist(p, q);
    if (d <= bestD) {
      best = id;
      bestD = d;
    }
  }
  return best;
}

export function wallAt(plan: Plan, p: Pt, tol: number, exclude: Set<string> = new Set()): Hit | null {
  let best: Hit | null = null;
  for (const wall of plan.walls) {
    if (exclude.has(wall.id)) continue;
    const line = centerline(plan, wall);
    if (line.length < 2) continue;
    const r = projectOnPolyline(p, line);
    const reach = Math.max(tol, wall.thickness / 2);
    if (r.d <= reach && (!best || r.d < best.d)) best = { wall, s: r.s, p: r.p, d: r.d, length: polylineLength(line) };
  }
  return best;
}

export function splitWall(plan: Plan, wallId: string, s: number): string {
  const wall = plan.walls.find((w) => w.id === wallId)!;
  const line = centerline(plan, wall);
  const at = pointAt(line, s).p;
  const node = newId("n");
  plan.nodes[node] = at;
  const tail: Wall = { ...wall, id: newId("w"), a: node, bulge: 0 };
  // дуга делится на две дуги того же круга
  if (Math.abs(wall.bulge) > 1e-9) {
    const total = polylineLength(line);
    const theta = 4 * Math.atan(wall.bulge);
    const k = s / total;
    wall.bulge = Math.tan((theta * k) / 4);
    tail.bulge = Math.tan((theta * (1 - k)) / 4);
  }
  wall.b = node;
  plan.walls.push(tail);
  for (const op of plan.openings) {
    if (op.wall === wall.id && op.at > s) {
      op.wall = tail.id;
      op.at -= s;
    }
  }
  return node;
}

// Узел в точке: существующий рядом, на стене (стена разрезается) или новый
export function ensureNode(plan: Plan, p: Pt, tol: number): string {
  const existing = nodeAt(plan, p, tol);
  if (existing) return existing;
  const hit = wallAt(plan, p, tol);
  if (hit && hit.s > tol && hit.s < hit.length - tol && hit.d <= tol) return splitWall(plan, hit.wall.id, hit.s);
  const id = newId("n");
  plan.nodes[id] = p;
  return id;
}

export function addWall(plan: Plan, from: Pt, to: Pt, tol: number, props: Pick<Wall, "thickness" | "kind"> & { bulge?: number }): Wall | null {
  if (dist(from, to) < 5) return null;
  const a = ensureNode(plan, from, tol);
  const b = ensureNode(plan, to, tol);
  if (a === b) return null;
  const wall: Wall = { id: newId("w"), a, b, thickness: props.thickness, kind: props.kind, bulge: props.bulge ?? 0 };
  plan.walls.push(wall);
  return wall;
}

export function dropOrphanNodes(plan: Plan) {
  const used = new Set(plan.walls.flatMap((w) => [w.a, w.b]));
  for (const id of Object.keys(plan.nodes)) if (!used.has(id)) delete plan.nodes[id];
}

export function remove(plan: Plan, selection: Sel[]) {
  const ids = (kind: Sel["kind"]) => new Set(selection.filter((s) => s.kind === kind).map((s) => s.id));
  const walls = ids("wall");
  const nodes = ids("node");
  for (const w of plan.walls) if (nodes.has(w.a) || nodes.has(w.b)) walls.add(w.id);
  plan.walls = plan.walls.filter((w) => !walls.has(w.id));
  const openings = ids("opening");
  plan.openings = plan.openings.filter((o) => !openings.has(o.id) && !walls.has(o.wall));
  const columns = ids("column");
  plan.columns = plan.columns.filter((c) => !columns.has(c.id));
  const stairs = ids("stair");
  plan.stairs = plan.stairs.filter((s) => !stairs.has(s.id));
  const rooms = ids("room");
  plan.rooms = plan.rooms.filter((r) => !rooms.has(r.id));
  dropOrphanNodes(plan);
}

// Узлы, которые двигаются вместе с выделенным
export function nodesOf(plan: Plan, selection: Sel[]): Set<string> {
  const out = new Set<string>();
  for (const s of selection) {
    if (s.kind === "node") out.add(s.id);
    if (s.kind === "wall") {
      const w = plan.walls.find((x) => x.id === s.id);
      if (w) {
        out.add(w.a);
        out.add(w.b);
      }
    }
  }
  return out;
}

export function translate(plan: Plan, base: Plan, selection: Sel[], dx: number, dy: number) {
  for (const id of nodesOf(base, selection)) {
    const p = base.nodes[id];
    if (p) plan.nodes[id] = [p[0] + dx, p[1] + dy];
  }
  const moved = (kind: Sel["kind"], id: string) => selection.some((s) => s.kind === kind && s.id === id);
  plan.columns.forEach((c, i) => {
    if (moved("column", c.id)) Object.assign(c, { x: base.columns[i]!.x + dx, y: base.columns[i]!.y + dy });
  });
  plan.stairs.forEach((s, i) => {
    if (moved("stair", s.id)) Object.assign(s, { x: base.stairs[i]!.x + dx, y: base.stairs[i]!.y + dy });
  });
  plan.rooms.forEach((r, i) => {
    if (moved("room", r.id)) Object.assign(r, { x: base.rooms[i]!.x + dx, y: base.rooms[i]!.y + dy });
  });
}

// Буфер обмена: копия выделенного с новыми ключами
export interface Clip {
  plan: Plan;
}

export function copy(plan: Plan, selection: Sel[]): Clip | null {
  const walls = plan.walls.filter((w) => selection.some((s) => s.kind === "wall" && s.id === w.id));
  const nodes = Object.fromEntries([...new Set(walls.flatMap((w) => [w.a, w.b]))].map((id) => [id, plan.nodes[id]!]));
  const wallIds = new Set(walls.map((w) => w.id));
  const clip: Plan = {
    nodes,
    walls,
    openings: plan.openings.filter((o) => wallIds.has(o.wall)),
    columns: plan.columns.filter((c) => selection.some((s) => s.kind === "column" && s.id === c.id)),
    stairs: plan.stairs.filter((x) => selection.some((s) => s.kind === "stair" && s.id === x.id)),
    rooms: [],
    underlay: null,
  };
  if (!clip.walls.length && !clip.columns.length && !clip.stairs.length) return null;
  return { plan: structuredClone(clip) };
}

export function paste(plan: Plan, clip: Clip, offset: Pt): Sel[] {
  const nodeMap = new Map<string, string>();
  const wallMap = new Map<string, string>();
  const sel: Sel[] = [];
  for (const [id, p] of Object.entries(clip.plan.nodes)) {
    const n = newId("n");
    nodeMap.set(id, n);
    plan.nodes[n] = [p[0] + offset[0], p[1] + offset[1]];
  }
  for (const w of clip.plan.walls) {
    const id = newId("w");
    wallMap.set(w.id, id);
    plan.walls.push({ ...w, id, a: nodeMap.get(w.a)!, b: nodeMap.get(w.b)! });
    sel.push({ kind: "wall", id });
  }
  for (const o of clip.plan.openings) plan.openings.push({ ...o, id: newId("o"), wall: wallMap.get(o.wall)! });
  for (const c of clip.plan.columns) {
    const id = newId("c");
    plan.columns.push({ ...c, id, x: c.x + offset[0], y: c.y + offset[1] });
    sel.push({ kind: "column", id });
  }
  for (const s of clip.plan.stairs) {
    const id = newId("s");
    plan.stairs.push({ ...s, id, x: s.x + offset[0], y: s.y + offset[1] });
    sel.push({ kind: "stair", id });
  }
  return sel;
}

// ---------------------------------------------------------------- привязки (5.1.4 п. 6)

export interface Snap {
  p: Pt;
  kind: "node" | "middle" | "wall" | "grid" | "angle" | "free";
  node?: string;
}

export const GRID = 100;

export function snapPoint(plan: Plan, raw: Pt, scale: number, snaps: Snaps, from?: Pt | null, exclude: Set<string> = new Set()): Snap {
  const tol = 10 / scale;
  if (snaps.nodes) {
    const node = nodeAt(plan, raw, tol, exclude);
    if (node) return { p: plan.nodes[node]!, kind: "node", node };
    for (const w of plan.walls) {
      if (exclude.has(w.a) || exclude.has(w.b)) continue;
      const line = centerline(plan, w);
      if (line.length < 2) continue;
      const mid = pointAt(line, polylineLength(line) / 2).p;
      if (dist(mid, raw) <= tol) return { p: mid, kind: "middle" };
    }
  }
  let p = raw;
  let kind: Snap["kind"] = "free";
  if (from && snaps.angles) {
    const angle = Math.atan2(raw[1] - from[1], raw[0] - from[0]);
    const step = Math.PI / 4;
    const snapped = Math.round(angle / step) * step;
    if (Math.abs(snapped - angle) < (7 * Math.PI) / 180) {
      let len = dist(from, raw);
      if (snaps.grid) len = Math.round(len / GRID) * GRID;
      p = [from[0] + Math.cos(snapped) * len, from[1] + Math.sin(snapped) * len];
      kind = "angle";
    }
  }
  if (kind === "free" && snaps.grid) {
    p = [Math.round(raw[0] / GRID) * GRID, Math.round(raw[1] / GRID) * GRID];
    kind = "grid";
  }
  if (snaps.nodes) {
    const hit = wallAt(plan, raw, tol, new Set(plan.walls.filter((w) => exclude.has(w.a) || exclude.has(w.b)).map((w) => w.id)));
    if (hit && hit.d <= tol && kind !== "angle") return { p: hit.p, kind: "wall" };
  }
  return { p, kind };
}
