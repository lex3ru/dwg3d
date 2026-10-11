/**
 * Edits of the wall graph. Every operation takes a floor and returns a new one
 * (the input is not changed), so the editor's undo is a list of floors.
 *
 * The graph stays planar: a new wall is cut where it crosses or touches other
 * walls and those are cut there too, so walls only meet at nodes.
 */
import { newId, type Floor, type Wall } from './model.ts'
import { EPS, dist, lerp, lineHit, perp, project, sub, unit, add, mul, type XY } from './vec.ts'

/** Points closer than this are one node: 5 mm. */
export const JOIN_TOL = 0.005

/** A copy of the floor whose maps can be changed in place. */
export function draft(f: Floor): Floor {
  return { ...f, nodes: { ...f.nodes }, walls: { ...f.walls }, openings: { ...f.openings }, rooms: { ...f.rooms } }
}

export function ends(f: Floor, w: Wall): [XY, XY] {
  return [f.nodes[w.a], f.nodes[w.b]]
}

export function wallLength(f: Floor, id: string): number {
  const [a, b] = ends(f, f.walls[id])
  return dist(a, b)
}

/** Walls that end at the node. */
export function wallsAt(f: Floor, node: string): string[] {
  return Object.keys(f.walls).filter(id => f.walls[id].a === node || f.walls[id].b === node)
}

export function wallBetween(f: Floor, n1: string, n2: string): string | null {
  for (const [id, w] of Object.entries(f.walls))
    if ((w.a === n1 && w.b === n2) || (w.a === n2 && w.b === n1)) return id
  return null
}

export function openingsOf(f: Floor, wall: string): string[] {
  return Object.keys(f.openings).filter(id => f.openings[id].wall === wall)
}

export function nodeAt(f: Floor, p: XY, tol = JOIN_TOL): string | null {
  let best: string | null = null, bestD = tol
  for (const [id, q] of Object.entries(f.nodes)) {
    const d = dist(p, q)
    if (d <= bestD) { best = id; bestD = d }
  }
  return best
}

/** The wall whose centre line passes within `tol` of p, away from its ends. */
export function wallAt(f: Floor, p: XY, tol = JOIN_TOL): { id: string; t: number } | null {
  let best: { id: string; t: number } | null = null, bestD = tol
  for (const [id, w] of Object.entries(f.walls)) {
    const [a, b] = ends(f, w)
    const { t, d } = project(p, a, b)
    const l = dist(a, b)
    if (t * l <= tol || (1 - t) * l <= tol) continue
    if (d <= bestD) { best = { id, t }; bestD = d }
  }
  return best
}

// ------------------------------------------------- changes made in place on a draft

/** Turns the wall around (a ↔ b) keeping its openings where they are. */
function reverse(d: Floor, id: string): void {
  const w = d.walls[id]
  const l = wallLength(d, id)
  d.walls[id] = { ...w, a: w.b, b: w.a }
  for (const o of openingsOf(d, id)) {
    const op = d.openings[o]
    d.openings[o] = { ...op, at: l - op.at, hinge: op.hinge === 'a' ? 'b' : 'a', side: op.side === 'left' ? 'right' : 'left' }
  }
}

/** Cuts the wall at t (0..1 along a→b) with a new node; returns the node. The part a→node keeps the id. */
function split(d: Floor, id: string, t: number): string {
  const w = d.walls[id]
  const [a, b] = ends(d, w)
  const n = newId(d.nodes)
  d.nodes[n] = lerp(a, b, t)
  const cut = t * dist(a, b)
  const rest = newId(d.walls)
  d.walls[id] = { ...w, b: n }
  d.walls[rest] = { ...w, a: n }
  for (const o of openingsOf(d, id)) {
    const op = d.openings[o]
    if (op.at > cut) d.openings[o] = { ...op, wall: rest, at: op.at - cut }
  }
  return n
}

/** The node at p: an existing one, one cut into a wall passing there, or a new one. */
function resolve(d: Floor, p: XY, tol: number): string {
  const n = nodeAt(d, p, tol)
  if (n) return n
  const on = wallAt(d, p, tol)
  if (on) return split(d, on.id, on.t)
  const id = newId(d.nodes)
  d.nodes[id] = p
  return id
}

function sameRun(x: Wall, y: Wall): boolean {
  return x.kind === y.kind && x.height === y.height && Math.abs(x.thickness - y.thickness) < EPS
}

/** Joins the two walls meeting at the node into one when they are in line and alike. */
function heal(d: Floor, node: string): void {
  const at = wallsAt(d, node)
  if (at.length !== 2) return
  const [w1, w2] = at
  if (!sameRun(d.walls[w1], d.walls[w2])) return
  if (d.walls[w1].b !== node) reverse(d, w1)
  if (d.walls[w2].a !== node) reverse(d, w2)
  const a = d.nodes[d.walls[w1].a], m = d.nodes[node], b = d.nodes[d.walls[w2].b]
  const { d: off, t } = project(m, a, b)
  if (off > EPS * 10 || t <= 0 || t >= 1) return
  if (wallBetween(d, d.walls[w1].a, d.walls[w2].b)) return
  const l1 = dist(a, m)
  d.walls[w1] = { ...d.walls[w1], b: d.walls[w2].b }
  for (const o of openingsOf(d, w2)) d.openings[o] = { ...d.openings[o], wall: w1, at: d.openings[o].at + l1 }
  delete d.walls[w2]
  delete d.nodes[node]
}

function dropWall(d: Floor, id: string): void {
  const w = d.walls[id]
  delete d.walls[id]
  for (const o of openingsOf(d, id)) delete d.openings[o]
  for (const n of [w.a, w.b]) {
    if (!(n in d.nodes)) continue
    if (wallsAt(d, n).length === 0) delete d.nodes[n]
    else heal(d, n)
  }
}

/** Moves every wall end from node `from` to node `into`; walls that become a point or a duplicate are dropped. */
function mergeNodes(d: Floor, from: string, into: string): void {
  for (const id of wallsAt(d, from)) {
    const w = d.walls[id]
    const other = w.a === from ? w.b : w.a
    if (other === into || wallBetween(d, other, into)) { dropWall(d, id); continue }
    d.walls[id] = w.a === from ? { ...w, a: into } : { ...w, b: into }
  }
  if (from in d.nodes && wallsAt(d, from).length === 0) delete d.nodes[from]
}

// ------------------------------------------------------------ operations

export interface Added { floor: Floor; walls: string[] }

/**
 * A wall from p to q. It is cut where it crosses, touches or runs along other
 * walls; parts that run along an existing wall are not added again. Returns
 * the new walls in order from p to q.
 */
export function addWall(f: Floor, p: XY, q: XY, props: Omit<Wall, 'a' | 'b'>, tol = JOIN_TOL): Added {
  const total = dist(p, q)
  if (total <= tol) return { floor: f, walls: [] }
  const r = sub(q, p)
  // where on p→q other walls meet it (0..1), found on the walls as they are now
  const stops: number[] = [0, 1]
  for (const w of Object.values(f.walls)) {
    const [a, b] = ends(f, w)
    const v = sub(b, a)
    const hit = lineHit(p, r, a, v)
    if (hit) {
      const sl = tol / total, ul = tol / dist(a, b)
      if (hit.s >= -sl && hit.s <= 1 + sl && hit.u >= -ul && hit.u <= 1 + ul) stops.push(Math.max(0, Math.min(1, hit.s)))
      continue
    }
    // parallel: overlapping when on one line
    if (project(a, p, q).d > tol && project(b, p, q).d > tol && project(p, a, b).d > tol && project(q, a, b).d > tol) continue
    for (const e of [a, b]) {
      const { t, d } = project(e, p, q)
      if (d <= tol && t > 0 && t < 1) stops.push(t)
    }
  }
  const d = draft(f)
  const nodes: string[] = []
  for (const s of [...new Set(stops)].sort((x, y) => x - y)) {
    const n = resolve(d, lerp(p, q, s), tol)
    if (nodes[nodes.length - 1] !== n) nodes.push(n)
  }
  const made: string[] = []
  for (let i = 1; i < nodes.length; i++) {
    if (wallBetween(d, nodes[i - 1], nodes[i])) continue
    const id = newId(d.walls)
    d.walls[id] = { ...props, a: nodes[i - 1], b: nodes[i] }
    made.push(id)
  }
  return { floor: d, walls: made }
}

/** A chain of walls through the points; `closed` also joins the last point to the first. */
export function addChain(f: Floor, points: XY[], props: Omit<Wall, 'a' | 'b'>, closed = false, tol = JOIN_TOL): Added {
  let floor = f
  const walls: string[] = []
  const pts = closed ? [...points, points[0]] : points
  for (let i = 1; i < pts.length; i++) {
    const r = addWall(floor, pts[i - 1], pts[i], props, tol)
    floor = r.floor
    walls.push(...r.walls)
  }
  return { floor, walls }
}

/** Removes the wall and its openings; nodes left without walls go too, and two walls left in line are joined. */
export function removeWall(f: Floor, id: string): Floor {
  if (!(id in f.walls)) return f
  const d = draft(f)
  dropWall(d, id)
  return d
}

/** Moves a node. With `join`, dropping it onto another node merges the two. */
export function moveNode(f: Floor, id: string, p: XY, join = false, tol = JOIN_TOL): Floor {
  if (!(id in f.nodes)) return f
  const d = draft(f)
  d.nodes[id] = p
  if (join) {
    const other = Object.keys(d.nodes).find(n => n !== id && dist(d.nodes[n], p) <= tol)
    if (other) mergeNodes(d, id, other)
  }
  return d
}

/** Shifts the wall (both its nodes, so walls meeting it stretch). */
export function moveWall(f: Floor, id: string, delta: XY): Floor {
  const w = f.walls[id]
  if (!w) return f
  const d = draft(f)
  d.nodes[w.a] = add(d.nodes[w.a], delta)
  d.nodes[w.b] = add(d.nodes[w.b], delta)
  return d
}

/** Shifts the wall sideways by `offset` (positive: to the left of a→b). */
export function offsetWall(f: Floor, id: string, offset: number): Floor {
  const w = f.walls[id]
  if (!w) return f
  const [a, b] = ends(f, w)
  return moveWall(f, id, mul(perp(unit(sub(b, a))), offset))
}

/** Sets the length of the centre line keeping the end `keep` where it is. */
export function setWallLength(f: Floor, id: string, length: number, keep: 'a' | 'b' = 'a'): Floor {
  const w = f.walls[id]
  if (!w || length <= JOIN_TOL) return f
  const [a, b] = ends(f, w)
  const [fixed, moving] = keep === 'a' ? [a, b] : [b, a]
  const p = add(fixed, mul(unit(sub(moving, fixed)), length))
  return moveNode(f, keep === 'a' ? w.b : w.a, p)
}

export function setWall(f: Floor, id: string, patch: Partial<Pick<Wall, 'thickness' | 'height' | 'kind'>>): Floor {
  if (!(id in f.walls)) return f
  const d = draft(f)
  d.walls[id] = { ...d.walls[id], ...patch }
  return d
}

/** Cuts the wall at the point nearest to p; returns the new node. */
export function splitWall(f: Floor, id: string, p: XY): { floor: Floor; node: string | null } {
  const w = f.walls[id]
  if (!w) return { floor: f, node: null }
  const [a, b] = ends(f, w)
  const { t } = project(p, a, b)
  const l = dist(a, b)
  if (t * l <= JOIN_TOL || (1 - t) * l <= JOIN_TOL) return { floor: f, node: null }
  const d = draft(f)
  return { floor: d, node: split(d, id, t) }
}


/**
 * The floor's bearing walls alone, as the start of the floor above: partitions,
 * openings and room names go, and a bearing wall a partition had cut in two is
 * whole again.
 */
export function bearingOnly(f: Floor): Floor {
  let out = f
  for (const [id, w] of Object.entries(f.walls)) if (w.kind !== 'bearing') out = removeWall(out, id)
  return { ...out, openings: {}, rooms: {} }
}
