/**
 * Wall outlines: the centre lines given their thickness, with the corners
 * where walls meet worked out.
 *
 * At each node the walls are taken in turn counter-clockwise; between two
 * neighbours the left face of one and the right face of the next meet at a
 * corner, which both of them end at. A wall alone at its node ends square;
 * two walls in line of different thickness step. When two walls meet at so
 * sharp an angle that the corner would run far out, both end square instead.
 *
 * "Plus" is the face to the left of a→b, "minus" the one to the right.
 */
import type { Floor } from './model.ts'
import { add, angle, dot, lineHit, mul, perp, sub, unit, type XY } from './vec.ts'

export interface WallOutline {
  aPlus: XY
  aMinus: XY
  bPlus: XY
  bMinus: XY
  /** the outline, counter-clockwise: a, aMinus, bMinus, b, bPlus, aPlus (the nodes keep junctions filled) */
  poly: XY[]
}

/** A corner further than this many half-thicknesses along the wall is cut square. */
const MITER_LIMIT = 6

interface End { wall: string; atA: boolean; dir: XY; h: number }

export function outlines(f: Floor): Record<string, WallOutline> {
  const byNode: Record<string, End[]> = {}
  for (const [id, w] of Object.entries(f.walls)) {
    const a = f.nodes[w.a], b = f.nodes[w.b]
    const d = unit(sub(b, a))
    ;(byNode[w.a] ??= []).push({ wall: id, atA: true, dir: d, h: w.thickness / 2 })
    ;(byNode[w.b] ??= []).push({ wall: id, atA: false, dir: mul(d, -1), h: w.thickness / 2 })
  }
  // corners of each wall end: left / right looking out of the node along the wall
  const left = new Map<End, XY>(), right = new Map<End, XY>()
  for (const [node, list] of Object.entries(byNode)) {
    const p = f.nodes[node]
    list.sort((x, y) => angle(x.dir) - angle(y.dir))
    for (let i = 0; i < list.length; i++) {
      const e = list[i], g = list[(i + 1) % list.length]
      const eLeft = add(p, mul(perp(e.dir), e.h))
      const gRight = add(p, mul(perp(g.dir), -g.h))
      if (e === g) { left.set(e, eLeft); right.set(g, gRight); continue }
      const hit = lineHit(eLeft, e.dir, gRight, g.dir)
      const limit = MITER_LIMIT * Math.max(e.h, g.h)
      if (hit && Math.abs(hit.s) <= limit && Math.abs(hit.u) <= limit) {
        const c = add(eLeft, mul(e.dir, hit.s))
        left.set(e, c)
        right.set(g, c)
      } else {
        // in line (a step when the thickness differs), or too sharp a corner
        left.set(e, eLeft)
        right.set(g, gRight)
      }
    }
  }
  const out: Record<string, WallOutline> = {}
  for (const list of Object.values(byNode))
    for (const e of list) {
      const o = (out[e.wall] ??= { aPlus: [0, 0], aMinus: [0, 0], bPlus: [0, 0], bMinus: [0, 0], poly: [] })
      if (e.atA) { o.aPlus = left.get(e)!; o.aMinus = right.get(e)! }
      else { o.bMinus = left.get(e)!; o.bPlus = right.get(e)! }
    }
  for (const [id, o] of Object.entries(out)) {
    const w = f.walls[id]
    o.poly = [f.nodes[w.a], o.aMinus, o.bMinus, f.nodes[w.b], o.bPlus, o.aPlus]
  }
  return out
}

export interface WallSides {
  /** centre line */
  center: number
  /** the face left of a→b, from corner to corner, measured along the wall */
  plus: number
  minus: number
  /** where along the centre line (distance from a) both faces exist: openings fit only here */
  from: number
  to: number
}

/** Lengths of a wall's faces, as dimension lines along the wall show them. */
export function wallSides(f: Floor, id: string, o: WallOutline): WallSides {
  const w = f.walls[id]
  const a = f.nodes[w.a], b = f.nodes[w.b]
  const d = unit(sub(b, a))
  const at = (p: XY) => dot(sub(p, a), d)
  const center = at(b)
  return {
    center,
    plus: at(o.bPlus) - at(o.aPlus),
    minus: at(o.bMinus) - at(o.aMinus),
    from: Math.max(0, at(o.aPlus), at(o.aMinus)),
    to: Math.min(center, at(o.bPlus), at(o.bMinus)),
  }
}

export function allSides(f: Floor, lines: Record<string, WallOutline> = outlines(f)): Record<string, WallSides> {
  const out: Record<string, WallSides> = {}
  for (const id of Object.keys(f.walls)) out[id] = wallSides(f, id, lines[id])
  return out
}
