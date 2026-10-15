/**
 * Walls drawn along their faces: a room is measured inside, from wall to wall,
 * so it is drawn by its inner faces and the walls go outside them. These are
 * the centre lines for such a drawing.
 */
import { add, lineHit, mul, perp, signedArea, sub, unit, type XY } from './vec.ts'

/** A corner further out than this many offsets is cut (a very sharp turn). */
const MITER_LIMIT = 8

/** The polyline moved by `d` to its left (negative: to its right), its corners mitred. */
export function offsetPolyline(points: XY[], d: number, closed: boolean): XY[] {
  const n = points.length
  if (n < 2) return points.slice()
  const seg = (i: number): [XY, XY] => [points[i], points[(i + 1) % n]]
  const count = closed ? n : n - 1
  const normals = Array.from({ length: count }, (_, i) => { const [a, b] = seg(i); return mul(perp(unit(sub(b, a))), d) })
  const out: XY[] = []
  for (let i = 0; i < n; i++) {
    const before = closed ? (i - 1 + count) % count : i - 1
    const after = closed ? i % count : i
    if (!closed && i === 0) { out.push(add(points[0], normals[0])); continue }
    if (!closed && i === n - 1) { out.push(add(points[n - 1], normals[count - 1])); continue }
    const [a0, b0] = seg(before), [a1, b1] = seg(after)
    const p = add(a0, normals[before]), q = add(a1, normals[after])
    const hit = lineHit(p, sub(b0, a0), q, sub(b1, a1))
    const c = hit ? add(p, mul(sub(b0, a0), hit.s)) : add(points[i], normals[after])
    // in line, or so sharp the corner would run off: the plain offset
    out.push(!hit || Math.hypot(c[0] - points[i][0], c[1] - points[i][1]) > MITER_LIMIT * Math.abs(d) ? add(points[i], normals[after]) : c)
  }
  return out
}

/**
 * The centre lines of walls `thickness` thick whose faces are the drawn points. A closed outline
 * is a room: the walls go outside it, whichever way it was drawn. An open line has the walls on
 * the side asked, looking along it.
 */
export function wallsFromFaces(points: XY[], thickness: number, closed: boolean, side: 'left' | 'right' = 'right'): XY[] {
  const h = thickness / 2
  if (closed && points.length >= 3) return offsetPolyline(points, signedArea(points) > 0 ? -h : h, true)
  return offsetPolyline(points, side === 'left' ? h : -h, false)
}
