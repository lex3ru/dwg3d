/**
 * Dimension chains along the faces of a wall, as on a working drawing: from
 * the corner to an opening, the opening, on to the next one, to the corner.
 * Distances are measured along the wall's centre line from its node a.
 */
import { ends, openingsOf, type Floor, type WallOutline } from '../plan/index.ts'
import { dot, sub, unit, type XY } from '../plan/vec.ts'

export interface Span { from: number; to: number; opening: boolean }

/** The chain of one face of the wall ('plus' — left of a→b, 'minus' — right); empty when the wall has no openings. */
export function faceChain(f: Floor, wall: string, o: WallOutline, side: 'plus' | 'minus'): Span[] {
  const ids = openingsOf(f, wall)
  if (!ids.length) return []
  const [a, b] = ends(f, f.walls[wall])
  const d = unit(sub(b, a))
  const at = (p: XY) => dot(sub(p, a), d)
  const start = at(side === 'plus' ? o.aPlus : o.aMinus), end = at(side === 'plus' ? o.bPlus : o.bMinus)
  const gaps = ids.map(id => f.openings[id]).map(op => [Math.max(start, op.at - op.width / 2), Math.min(end, op.at + op.width / 2)] as const)
    .filter(([x0, x1]) => x1 > x0).sort((x, y) => x[0] - y[0])
  const out: Span[] = []
  let x = start
  for (const [x0, x1] of gaps) {
    if (x0 > x + 1e-9) out.push({ from: x, to: x0, opening: false })
    out.push({ from: Math.max(x0, x), to: x1, opening: true })
    x = Math.max(x, x1)
  }
  if (end > x + 1e-9) out.push({ from: x, to: end, opening: false })
  return out
}

/** The outer extents of the floor's walls: [x0, y0, x1, y1], or null with no walls. */
export function extents(lines: Record<string, WallOutline>): [number, number, number, number] | null {
  const ps = Object.values(lines).flatMap(o => o.poly)
  if (!ps.length) return null
  const xs = ps.map(p => p[0]), ys = ps.map(p => p[1])
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
}
