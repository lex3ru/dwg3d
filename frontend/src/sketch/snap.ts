/**
 * Where a point under the cursor lands while drawing: on a node, on a wall's
 * centre line, straight on from the previous point, in line with other nodes,
 * or on the centimetre grid. The tolerance is the snap radius in plan meters
 * (a few screen pixels at the current zoom).
 */
import { ends, type Floor } from '../plan/index.ts'
import { dist, lineHit, project, lerp, sub, type XY } from '../plan/vec.ts'

export type SnapKind = 'node' | 'wall' | 'cross' | 'straight' | 'align' | 'free'

export interface Snap {
  p: XY
  kind: SnapKind
  node?: string
  wall?: string
  /** lines to draw as a hint: from the node the point lines up with, to the point */
  guides: [XY, XY][]
}

export interface SnapOptions {
  tol: number
  /** the previous point of the wall being drawn */
  from?: XY | null
  /** nodes not to snap to (the one being dragged) */
  skip?: string[]
  /** no snapping at all (Alt held): only the centimetre grid */
  free?: boolean
}

/** Within this angle of the axes a wall being drawn goes straight. */
const STRAIGHT_DEG = 6

const cm = (v: number) => Math.round(v * 100) / 100
const onGrid = (p: XY): XY => [cm(p[0]), cm(p[1])]

export function snap(f: Floor, raw: XY, o: SnapOptions): Snap {
  if (o.free) return { p: onGrid(raw), kind: 'free', guides: [] }
  const skip = new Set(o.skip)
  const nodes = Object.entries(f.nodes).filter(([id]) => !skip.has(id))
  const walls = Object.entries(f.walls).filter(([, w]) => !skip.has(w.a) && !skip.has(w.b))

  let node: [string, XY] | null = null, nd = o.tol
  for (const [id, p] of nodes) {
    const d = dist(p, raw)
    if (d <= nd) { node = [id, p]; nd = d }
  }
  if (node) return { p: node[1], kind: 'node', node: node[0], guides: [] }

  // straight on from the previous point: along that line, stop at nodes in line and at walls it crosses
  if (o.from) {
    const dx = raw[0] - o.from[0], dy = raw[1] - o.from[1]
    const deg = Math.abs((Math.atan2(dy, dx) * 180) / Math.PI) % 90
    if (Math.hypot(dx, dy) > o.tol && (deg < STRAIGHT_DEG || deg > 90 - STRAIGHT_DEG)) {
      const horiz = Math.abs(dx) >= Math.abs(dy)
      const from = o.from
      const line: XY = horiz ? [raw[0], from[1]] : [from[0], raw[1]]
      let best: Snap | null = null, bd = o.tol
      const dir: XY = horiz ? [1, 0] : [0, 1]
      for (const [id, w] of walls) {
        const [a, b] = ends(f, w)
        const hit = lineHit(from, dir, a, sub(b, a))
        if (!hit || hit.u < 0 || hit.u > 1) continue
        const q = lerp(a, b, hit.u)
        const d = dist(q, line)
        if (d < bd) { bd = d; best = { p: q, kind: 'cross', wall: id, guides: [] } }
      }
      // a wall reached wins over a corner in line with the same point
      if (!best) {
        for (const [, p] of nodes) {
          const q: XY = horiz ? [p[0], from[1]] : [from[0], p[1]]
          const d = dist(q, line) + dist(p, q) * 1e-6   // of corners in line, the nearest draws the guide
          if (d < bd) { bd = d; best = { p: q, kind: 'align', guides: [[p, q]] } }
        }
      }
      if (best) return best
      return { p: horiz ? [cm(line[0]), from[1]] : [from[0], cm(line[1])], kind: 'straight', guides: [] }
    }
  }

  let wall: { id: string; p: XY } | null = null, wd = o.tol
  for (const [id, w] of walls) {
    const [a, b] = ends(f, w)
    const { t, d } = project(raw, a, b)
    if (t > 0 && t < 1 && d < wd) { wall = { id, p: lerp(a, b, t) }; wd = d }
  }
  if (wall) return { p: wall.p, kind: 'wall', wall: wall.id, guides: [] }

  // in line with other nodes: x of one, y of another
  let x: XY | null = null, y: XY | null = null, xd = o.tol, yd = o.tol
  for (const [, p] of nodes) {
    // of corners in line, the nearest draws the guide
    const ddx = Math.abs(p[0] - raw[0]) + Math.abs(p[1] - raw[1]) * 1e-6, ddy = Math.abs(p[1] - raw[1]) + Math.abs(p[0] - raw[0]) * 1e-6
    if (ddx < xd) { xd = ddx; x = p }
    if (ddy < yd) { yd = ddy; y = p }
  }
  if (x || y) {
    const p: XY = [x ? x[0] : cm(raw[0]), y ? y[1] : cm(raw[1])]
    const guides: [XY, XY][] = []
    if (x) guides.push([x, p])
    if (y) guides.push([y, p])
    return { p, kind: 'align', guides }
  }
  return { p: onGrid(raw), kind: 'free', guides: [] }
}

/** The point at `length` from `from` in the direction of `toward` (a length typed while drawing). */
export function atLength(from: XY, toward: XY, length: number): XY | null {
  const d = dist(from, toward)
  if (d < 1e-9 || !(length > 0)) return null
  return lerp(from, toward, length / d)
}
