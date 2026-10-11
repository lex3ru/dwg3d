/**
 * How openings look on the plan, as SVG path data in plan meters: the gap
 * cut through the wall, and the symbol in it — a door's leaf and its swing,
 * a window's panes, a vitrage's glass, a passage's lintel.
 */
import { ends, type Floor, type Opening } from '../plan/index.ts'
import { add, cross, dist, lerp, mul, perp, sub, unit, type XY } from '../plan/vec.ts'

const P = (p: XY) => `${p[0]} ${p[1]}`
const line = (a: XY, b: XY) => `M${P(a)}L${P(b)}`

export interface OpeningShape {
  /** the gap through the wall, a little deeper than the wall so no hairline of it stays */
  gap: string
  /** jambs, panes, the leaf */
  lines: string
  /** the door's swing, drawn lighter */
  swing: string
  /** the middle of the gap, for its label */
  center: XY
}

export function openingShape(f: Floor, o: Opening, overlap = 0): OpeningShape {
  const w = f.walls[o.wall]
  const [a, b] = ends(f, w)
  const d = unit(sub(b, a))
  const n = perp(d)
  const l = dist(a, b)
  const h = w.thickness / 2
  const c0 = lerp(a, b, (o.at - o.width / 2) / l), c1 = lerp(a, b, (o.at + o.width / 2) / l)
  const off = (p: XY, k: number): XY => add(p, mul(n, k))
  const gap = `M${P(off(c0, -h - overlap))}L${P(off(c1, -h - overlap))}L${P(off(c1, h + overlap))}L${P(off(c0, h + overlap))}Z`
  const jambs = line(off(c0, -h), off(c0, h)) + line(off(c1, -h), off(c1, h))
  let lines = jambs, swing = ''
  if (o.kind === 'door') {
    const s = o.side === 'left' ? 1 : -1
    const [hinge, free] = o.hinge === 'a' ? [c0, c1] : [c1, c0]
    const H = off(hinge, s * h)
    const open = add(H, mul(n, s * o.width))
    const closed = off(free, s * h)
    lines += line(H, open)
    // the swing from the open leaf to where it closes, the short way round (angles counter-clockwise on the plan)
    const sweep = cross(sub(open, H), sub(closed, H)) > 0 ? 1 : 0
    swing = `M${P(open)}A${o.width} ${o.width} 0 0 ${sweep} ${P(closed)}`
  } else if (o.kind === 'window') {
    const k = h / 3
    lines += line(off(c0, -k), off(c1, -k)) + line(off(c0, k), off(c1, k)) + line(off(c0, -h), off(c1, -h)) + line(off(c0, h), off(c1, h))
  } else if (o.kind === 'vitrage') {
    lines += line(c0, c1) + line(off(c0, -h), off(c1, -h)) + line(off(c0, h), off(c1, h))
  } else {
    swing = line(c0, c1)   // a passage: the lintel above, dashed
  }
  return { gap, lines, swing, center: lerp(c0, c1, 0.5) }
}

/** The distances from the opening's edges to the ends of its wall's faces: what the dimension hints show. */
export function clearances(o: Opening, from: number, to: number): [number, number] {
  return [o.at - o.width / 2 - from, to - (o.at + o.width / 2)]
}
