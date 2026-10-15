/** Plane vector helpers for the plan core. Plan coordinates, meters, Y up. */
export type XY = [number, number]

/** Below this two lengths are equal: 0.01 mm. */
export const EPS = 1e-5

export const add = (a: XY, b: XY): XY => [a[0] + b[0], a[1] + b[1]]
export const sub = (a: XY, b: XY): XY => [a[0] - b[0], a[1] - b[1]]
export const mul = (a: XY, k: number): XY => [a[0] * k, a[1] * k]
export const dot = (a: XY, b: XY): number => a[0] * b[0] + a[1] * b[1]
export const cross = (a: XY, b: XY): number => a[0] * b[1] - a[1] * b[0]
export const len = (a: XY): number => Math.hypot(a[0], a[1])
export const dist = (a: XY, b: XY): number => Math.hypot(a[0] - b[0], a[1] - b[1])
export const lerp = (a: XY, b: XY, t: number): XY => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
/** Left normal: the vector turned 90° counter-clockwise. */
export const perp = (a: XY): XY => [-a[1], a[0]]

export function unit(a: XY): XY {
  const l = len(a)
  return l < EPS ? [0, 0] : [a[0] / l, a[1] / l]
}

/** Angle of a vector, radians in [0, 2π). */
export function angle(a: XY): number {
  const r = Math.atan2(a[1], a[0])
  return r < 0 ? r + 2 * Math.PI : r
}

/** Where on segment ab the point p projects: t along ab (0 at a, 1 at b), unclamped, and the distance to the clamped point. */
export function project(p: XY, a: XY, b: XY): { t: number; d: number } {
  const ab = sub(b, a)
  const l2 = dot(ab, ab)
  const t = l2 < EPS * EPS ? 0 : dot(sub(p, a), ab) / l2
  return { t, d: dist(p, lerp(a, b, Math.max(0, Math.min(1, t)))) }
}

/** Intersection of the lines p + s·r and q + u·v: the parameters s and u, or null when parallel. */
export function lineHit(p: XY, r: XY, q: XY, v: XY): { s: number; u: number } | null {
  const den = cross(r, v)
  if (Math.abs(den) < 1e-12) return null
  const qp = sub(q, p)
  return { s: cross(qp, v) / den, u: cross(qp, r) / den }
}

/** Signed area of a ring: positive when counter-clockwise. */
export function signedArea(ring: XY[]): number {
  let s = 0
  for (let i = 0, n = ring.length; i < n; i++) {
    const a = ring[i], b = ring[(i + 1) % n]
    s += a[0] * b[1] - b[0] * a[1]
  }
  return s / 2
}

/** Point in ring, even-odd rule; points on the border count as inside or outside arbitrarily. */
export function inRing(p: XY, ring: XY[]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j]
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}
