/**
 * The picture under a floor: where it lies on the plan, its scale set by two
 * points of known distance, its turn, and its SVG transform. Plan meters, Y
 * up, angles counter-clockwise; the picture's pixels go right and down from
 * its top-left corner. `at` is where its bottom-left corner lies, and the
 * picture is turned about that corner.
 */
import type { Underlay } from '../plan/index.ts'
import { add, dist, mul, sub, type XY } from '../plan/vec.ts'

/** How wide a new picture is laid on an empty plan, meters: a flat or a small house fits. */
const DEFAULT_WIDTH_M = 20

const rad = (deg: number) => (deg * Math.PI) / 180
const turn = (p: XY, deg: number): XY => {
  const c = Math.cos(rad(deg)), s = Math.sin(rad(deg))
  return [p[0] * c - p[1] * s, p[0] * s + p[1] * c]
}
/** Angles kept in (−180, 180]. */
const norm = (deg: number) => {
  const d = ((((deg + 180) % 360) + 360) % 360) - 180
  return d === -180 ? 180 : d
}

/**
 * A new picture laid where it is likely meant: over the walls already drawn (as wide as they
 * are, a little more), or 20 m wide around the origin. Its scale is a guess to correct by two points.
 */
export function placeUnderlay(image: string, width: number, height: number, walls: [number, number, number, number] | null): Underlay {
  const across = walls ? Math.max((walls[2] - walls[0]) * 1.15, 1) : DEFAULT_WIDTH_M
  const scale = across / width
  const c: XY = walls ? [(walls[0] + walls[2]) / 2, (walls[1] + walls[3]) / 2] : [0, 0]
  return { image, at: [c[0] - (width * scale) / 2, c[1] - (height * scale) / 2], scale, rotation: 0, width, height, opacity: 0.5, hidden: false }
}

/** The plan point of a pixel of the picture. */
export function pixelAt(u: Underlay, px: XY): XY {
  return add(u.at, turn([px[0] * u.scale, (u.height - px[1]) * u.scale], u.rotation ?? 0))
}

/** The SVG transform that lays the picture's pixels on the plan (inside the plan's own transform). */
export function underlayTransform(u: Underlay): string {
  const c = Math.cos(rad(u.rotation ?? 0)), s = Math.sin(rad(u.rotation ?? 0)), k = u.scale
  const [e, f] = pixelAt(u, [0, 0])
  const r = (v: number) => Math.round(v * 1e9) / 1e9
  return `matrix(${r(c * k)} ${r(s * k)} ${r(s * k)} ${r(-c * k)} ${r(e)} ${r(f)})`
}

/** The picture scaled so that the points a and b, picked on it, are `length` meters apart; a stays where it is. */
export function calibrate(u: Underlay, a: XY, b: XY, length: number): Underlay {
  const d = dist(a, b)
  if (d < 1e-9 || !(length > 0)) return u
  const k = length / d
  return { ...u, scale: u.scale * k, at: add(a, mul(sub(u.at, a), k)) }
}

export function moveUnderlay(u: Underlay, delta: XY): Underlay {
  return { ...u, at: add(u.at, delta) }
}

/** The picture turned by `deg` about the point p (its middle when not given). */
export function rotateUnderlay(u: Underlay, deg: number, p: XY = pixelAt(u, [u.width / 2, u.height / 2])): Underlay {
  return { ...u, rotation: norm((u.rotation ?? 0) + deg), at: add(p, turn(sub(u.at, p), deg)) }
}

/** The picture turned about a so that the line a–b, picked on it, runs straight across or straight up — whichever is nearer. */
export function levelUnderlay(u: Underlay, a: XY, b: XY): Underlay {
  if (dist(a, b) < 1e-9) return u
  const angle = (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI
  const delta = Math.round(angle / 90) * 90 - angle
  return Math.abs(delta) < 1e-9 ? u : rotateUnderlay(u, delta, a)
}

/** Whether a plan point is on the picture. */
export function onUnderlay(u: Underlay, p: XY): boolean {
  const q = turn(sub(p, u.at), -(u.rotation ?? 0))
  return q[0] >= 0 && q[0] <= u.width * u.scale && q[1] >= 0 && q[1] <= u.height * u.scale
}
