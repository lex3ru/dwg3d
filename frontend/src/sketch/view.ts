/**
 * The plan on screen: a centre in plan meters and a scale in pixels per meter.
 * The plan's Y goes up, the screen's down.
 */
import type { XY } from '../plan/index.ts'

export interface View { cx: number; cy: number; scale: number }

export const MIN_SCALE = 2      // px per m: a 500 m site fits a screen
export const MAX_SCALE = 2000   // px per m: 1 cm is 20 px

export function toPlan(v: View, size: XY, s: XY): XY {
  return [v.cx + (s[0] - size[0] / 2) / v.scale, v.cy - (s[1] - size[1] / 2) / v.scale]
}

export function toScreen(v: View, size: XY, p: XY): XY {
  return [size[0] / 2 + (p[0] - v.cx) * v.scale, size[1] / 2 - (p[1] - v.cy) * v.scale]
}

/** The SVG transform that draws plan meters at this view. */
export function planTransform(v: View, size: XY): string {
  const s = v.scale
  return `matrix(${s} 0 0 ${-s} ${size[0] / 2 - v.cx * s} ${size[1] / 2 + v.cy * s})`
}

/** Zooms by `k` keeping the plan point under the screen point `at` where it is. */
export function zoomAt(v: View, size: XY, at: XY, k: number): View {
  const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.scale * k))
  const p = toPlan(v, size, at)
  return { scale, cx: p[0] - (at[0] - size[0] / 2) / scale, cy: p[1] + (at[1] - size[1] / 2) / scale }
}

/** The view showing the box [x0, y0, x1, y1] with a margin; an empty plan shows 10 × 10 m around the origin. */
export function fitView(box: [number, number, number, number] | null, size: XY): View {
  const [x0, y0, x1, y1] = box ?? [-5, -5, 5, 5]
  const w = Math.max(x1 - x0, 1), h = Math.max(y1 - y0, 1)
  const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.min(size[0] / (w * 1.2), size[1] / (h * 1.2))))
  return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, scale }
}

/** Grid steps for the scale: thin lines at least 12 px apart, every tenth bolder. */
export function gridSteps(scale: number): { minor: number; major: number } {
  const minor = [0.1, 0.5, 1, 5, 10, 50].find(m => m * scale >= 12) ?? 100
  return { minor, major: minor * 10 }
}
