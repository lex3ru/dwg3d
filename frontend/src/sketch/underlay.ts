/**
 * The picture under a floor: where it lies on the plan, its scale set by two
 * points of known distance, and its SVG transform. Plan meters, Y up; the
 * picture's pixels go right and down from its top-left corner.
 */
import type { Underlay } from '../plan/index.ts'
import { add, dist, mul, sub, type XY } from '../plan/vec.ts'

/** How wide a new picture is laid on an empty plan, meters: a flat or a small house fits. */
const DEFAULT_WIDTH_M = 20

/**
 * A new picture laid where it is likely meant: over the walls already drawn (as wide as they
 * are, a little more), or 20 m wide around the origin. Its scale is a guess to correct by two points.
 */
export function placeUnderlay(image: string, width: number, height: number, walls: [number, number, number, number] | null): Underlay {
  const across = walls ? Math.max((walls[2] - walls[0]) * 1.15, 1) : DEFAULT_WIDTH_M
  const scale = across / width
  const c: XY = walls ? [(walls[0] + walls[2]) / 2, (walls[1] + walls[3]) / 2] : [0, 0]
  return { image, at: [c[0] - (width * scale) / 2, c[1] - (height * scale) / 2], scale, width, height, opacity: 0.5, hidden: false }
}

/** The SVG transform that lays the picture's pixels on the plan (inside the plan's own transform). */
export function underlayTransform(u: Underlay): string {
  return `matrix(${u.scale} 0 0 ${-u.scale} ${u.at[0]} ${u.at[1] + u.height * u.scale})`
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

/** Whether a plan point is on the picture. */
export function onUnderlay(u: Underlay, p: XY): boolean {
  return p[0] >= u.at[0] && p[0] <= u.at[0] + u.width * u.scale && p[1] >= u.at[1] && p[1] <= u.at[1] + u.height * u.scale
}

/** The plan point of a pixel of the picture (for tests and hints). */
export function pixelAt(u: Underlay, px: XY): XY {
  return [u.at[0] + px[0] * u.scale, u.at[1] + (u.height - px[1]) * u.scale]
}
