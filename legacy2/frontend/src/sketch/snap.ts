/**
 * Where a point under the cursor lands while drawing: on a node, on a wall's
 * centre line, straight on from the previous point, in line with other nodes,
 * or on the centimetre grid. The tolerance is the snap radius in plan meters
 * (a few screen pixels at the current zoom).
 */
import { ends, fitOpening, outlines, wallSides, type Floor, type Wall, type WallOutline } from '../plan/index.ts'
import { cross, dist, lineHit, project, lerp, sub, type XY } from '../plan/vec.ts'

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

/**
 * What was typed while drawing: a length in centimetres, then «<» and an angle in degrees
 * (counter-clockwise from the right, as on a protractor) — «300», «300<45», «<45».
 */
export function readTyped(text: string): { length: number | null; angle: number | null } {
  const [l, a] = text.split('<')
  const num = (v: string | undefined) => (v === undefined || v.trim() === '' || !Number.isFinite(Number(v)) ? null : Number(v))
  const length = num(l)
  return { length: length !== null && length > 0 ? length / 100 : null, angle: num(a) }
}

/** Where a wall typed in goes: the length (or as far as the cursor) in the angle typed (or towards the cursor). */
export function typedPoint(from: XY, cursor: XY, text: string): XY | null {
  const { length, angle } = readTyped(text)
  if (angle === null) return length === null ? null : atLength(from, cursor, length)
  const r = (angle * Math.PI) / 180
  const dir: XY = [Math.cos(r), Math.sin(r)]
  const l = length ?? Math.max(0, (cursor[0] - from[0]) * dir[0] + (cursor[1] - from[1]) * dir[1])
  return l > 0 ? [from[0] + dir[0] * l, from[1] + dir[1] * l] : null
}

/** The point at `length` from `from` in the direction of `toward` (a length typed while drawing). */
export function atLength(from: XY, toward: XY, length: number): XY | null {
  const d = dist(from, toward)
  if (d < 1e-9 || !(length > 0)) return null
  return lerp(from, toward, length / d)
}

export interface OpeningSpot {
  wall: string
  /** the centre's distance from the wall's node a */
  at: number
  /** the side of the wall the cursor is on, looking from a to b */
  side: 'left' | 'right'
}

/**
 * Where an opening of `width` goes for the cursor: on the wall under it (or
 * within `tol` of its faces), centred under the cursor with its edge a whole
 * number of centimetres from the corner,
 * in the middle of the wall's face when near it, moved clear of the wall's
 * ends and other openings. null when no wall is near or none has room.
 */
export function openingSpot(f: Floor, raw: XY, width: number, tol: number, ignore?: string, lines: Record<string, WallOutline> = outlines(f)): OpeningSpot | null {
  let best: { id: string; t: number; d: number } | null = null
  for (const [id, w] of Object.entries(f.walls)) {
    const [a, b] = ends(f, w)
    const { t, d } = project(raw, a, b)
    if (t < 0 || t > 1 || d > w.thickness / 2 + tol) continue
    if (!best || d < best.d) best = { id, t, d }
  }
  if (!best) return null
  const w = f.walls[best.id]
  const [a, b] = ends(f, w)
  const l = dist(a, b)
  const s = wallSides(f, best.id, lines[best.id])
  const mid = (s.from + s.to) / 2
  // whole centimetres from the opening's edge to the corner, as it is measured on site
  const edge = Math.round((best.t * l - width / 2 - s.from) * 100) / 100
  let at = s.from + edge + width / 2
  if (Math.abs(at - mid) <= tol) at = mid
  const fit = fitOpening(f, best.id, at, width, ignore, lines)
  if (fit === null) return null
  return { wall: best.id, at: fit, side: cross(sub(b, a), sub(raw, a)) >= 0 ? 'left' : 'right' }
}

/**
 * The faces of the walls as a floor of their own: their corners as nodes, each face as a wall —
 * what a line drawn along faces snaps to. `extra` are points to snap to besides (the line so far).
 */
export function facesFloor(f: Floor, lines: Record<string, WallOutline>, extra: XY[] = []): Floor {
  const nodes: Record<string, XY> = {}
  const walls: Record<string, Wall> = {}
  for (const [id, o] of Object.entries(lines)) {
    for (const [side, a, b] of [['p', o.aPlus, o.bPlus], ['m', o.aMinus, o.bMinus]] as const) {
      nodes[`${id}${side}a`] = a
      nodes[`${id}${side}b`] = b
      if (dist(a, b) > 1e-6) walls[`${id}${side}`] = { a: `${id}${side}a`, b: `${id}${side}b`, thickness: 0, height: null, kind: f.walls[id].kind }
    }
  }
  extra.forEach((p, i) => { nodes[`x${i}`] = p })
  return { ...f, nodes, walls, openings: {}, rooms: {} }
}
