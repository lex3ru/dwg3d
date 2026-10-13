/**
 * Curved walls (model.ts `Curve`): the arc through two ends standing a bulge
 * off its chord, the chain of faces that follows it, and keeping the faces on
 * the arc when its ends move. Only geometry here — the edits are in curves.ts.
 */
import type { Floor } from './model.ts'
import { add, dist, dot, lerp, mul, perp, sub, unit, type XY } from './vec.ts'

const STEP = (10 * Math.PI) / 180          // a face turns at most this much
const MIN_FACE = 0.1                       // meters
export const MAX_SEGMENTS = 64

/** The arc's centre and radius, or null when it is straight. */
export function arcCircle(a: XY, b: XY, bulge: number): { center: XY; r: number } | null {
  const c = dist(a, b)
  if (c < 1e-9 || Math.abs(bulge) < 1e-6) return null
  const n = perp(unit(sub(b, a)))
  const r = (c * c / 4 + bulge * bulge) / (2 * Math.abs(bulge))
  return { center: add(lerp(a, b, 0.5), mul(n, bulge - Math.sign(bulge) * r)), r }
}

/** The angle the arc turns through, radians. */
export const arcSweep = (a: XY, b: XY, bulge: number): number => {
  const c = dist(a, b)
  return c < 1e-9 ? 0 : 4 * Math.atan((2 * Math.abs(bulge)) / c)
}

/** The arc's length along its middle. */
export function arcLength(a: XY, b: XY, bulge: number): number {
  const circle = arcCircle(a, b, bulge)
  return circle ? circle.r * arcSweep(a, b, bulge) : dist(a, b)
}

/** segments + 1 points from a to b along the arc, equally apart. */
export function arcPoints(a: XY, b: XY, bulge: number, segments: number): XY[] {
  const circle = arcCircle(a, b, bulge)
  const pts: XY[] = []
  for (let i = 0; i <= segments; i++) {
    if (i === 0) pts.push(a)
    else if (i === segments) pts.push(b)
    else if (!circle) pts.push(lerp(a, b, i / segments))
    else {
      const { center, r } = circle
      // from a over the bulge to b: clockwise when the arc stands to the left of a→b
      const t = Math.atan2(a[1] - center[1], a[0] - center[0]) - Math.sign(bulge) * arcSweep(a, b, bulge) * (i / segments)
      pts.push([center[0] + r * Math.cos(t), center[1] + r * Math.sin(t)])
    }
  }
  return pts
}

/** How many faces an arc wants: none turning more than 10°, none shorter than 10 cm. */
export function defaultSegments(a: XY, b: XY, bulge: number): number {
  const byAngle = Math.ceil(arcSweep(a, b, bulge) / STEP - 1e-9)
  const byLength = Math.floor(arcLength(a, b, bulge) / MIN_FACE)
  return Math.max(2, Math.min(MAX_SEGMENTS, byAngle, Math.max(2, byLength)))
}

/** The bulge of the arc from a to b through p (no more than the chord: the arc stays under three quarters of a circle). */
export function bulgeThrough(a: XY, b: XY, p: XY): number {
  const c = dist(a, b)
  if (c < 1e-9) return 0
  const n = perp(unit(sub(b, a)))
  const m = lerp(a, b, 0.5)
  const h = dot(sub(p, m), n)
  // the circle through a, b and p has its centre on the chord's bisector, where it is as far from p as from a
  const u = sub(p, m)
  const along = dot(u, unit(sub(b, a)))
  if (Math.abs(h) < 1e-6) return 0
  const k = (along * along + h * h - c * c / 4) / (2 * h)    // the centre: m + n·k
  const r = Math.hypot(c / 2, k)
  const s = k + Math.sign(h) * r
  return Math.max(-c, Math.min(c, s))
}

// ------------------------------------------------------------ the chain of faces

/** The faces of the curve from its end a to its end b: their nodes and walls in order, or null when broken. */
export function curveChain(f: Floor, id: string): { nodes: string[]; walls: string[] } | null {
  const c = f.curves?.[id]
  if (!c || !(c.a in f.nodes) || !(c.b in f.nodes)) return null
  const mine = Object.keys(f.walls).filter(w => f.walls[w].curve === id)
  const nodes = [c.a], walls: string[] = []
  const used = new Set<string>()
  let at = c.a
  while (at !== c.b) {
    const next = mine.find(w => !used.has(w) && (f.walls[w].a === at || f.walls[w].b === at))
    if (!next) return null
    used.add(next)
    walls.push(next)
    at = f.walls[next].a === at ? f.walls[next].b : f.walls[next].a
    nodes.push(at)
  }
  return walls.length === mine.length ? { nodes, walls } : null
}

/** The nodes inside the chain where other walls meet it: the faces cannot be moved there. */
export function curveJoints(f: Floor, chain: { nodes: string[]; walls: string[] }): string[] {
  const set = new Set(chain.walls)
  return chain.nodes.slice(1, -1).filter(n => Object.entries(f.walls).some(([id, w]) => !set.has(id) && (w.a === n || w.b === n)))
}

/** The curve a node lies inside (not at its ends), if any. */
export function curveThrough(f: Floor, node: string): string | null {
  for (const w of Object.values(f.walls)) {
    if (!w.curve || (w.a !== node && w.b !== node)) continue
    const c = f.curves?.[w.curve]
    if (c && c.a !== node && c.b !== node) return w.curve
  }
  return null
}

/**
 * Puts the faces of each curve back on its arc (in place, on a draft whose nodes and openings may be changed):
 * after its ends moved, or its bulge changed. A curve other walls meet inside keeps its faces where they are.
 */
export function fitCurves(d: Floor): void {
  for (const id of Object.keys(d.curves ?? {})) {
    const c = d.curves![id]
    const chain = curveChain(d, id)
    if (!chain || curveJoints(d, chain).length) continue
    const pts = arcPoints(d.nodes[c.a], d.nodes[c.b], c.bulge, chain.walls.length)
    const before = chain.walls.map(w => dist(d.nodes[d.walls[w].a], d.nodes[d.walls[w].b]))
    chain.nodes.slice(1, -1).forEach((n, i) => { d.nodes[n] = pts[i + 1] })
    chain.walls.forEach((w, i) => {
      const k = before[i] > 1e-9 ? dist(d.nodes[d.walls[w].a], d.nodes[d.walls[w].b]) / before[i] : 1
      if (Math.abs(k - 1) < 1e-12) return
      for (const [o, op] of Object.entries(d.openings)) if (op.wall === w) d.openings[o] = { ...op, at: op.at * k }
    })
  }
}
