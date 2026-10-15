/** Openings in walls: placing them so they fit, and their shape on the plan. */
import { draft, ends, openingsOf } from './graph.ts'
import { newId, OPENING_DEFAULTS, type Floor, type Opening, type OpeningKind } from './model.ts'
import { outlines, wallSides, type WallOutline } from './outline.ts'
import { add, lerp, mul, perp, sub, unit, dist, type XY } from './vec.ts'

/** Openings keep at least this much wall between them: 1 cm. */
const GAP = 0.01

/**
 * Where on the wall an opening of `width` can stand nearest to `at`: inside the
 * wall's faces and clear of its other openings. null when there is no room.
 */
export function fitOpening(f: Floor, wall: string, at: number, width: number, ignore?: string, lines?: Record<string, WallOutline>): number | null {
  const w = f.walls[wall]
  if (!w) return null
  const s = wallSides(f, wall, (lines ?? outlines(f))[wall])
  // free stretches of the wall, between its ends and the other openings
  const taken = openingsOf(f, wall).filter(id => id !== ignore).map(id => f.openings[id])
    .map(o => [o.at - o.width / 2 - GAP, o.at + o.width / 2 + GAP] as const)
    .sort((x, y) => x[0] - y[0])
  const free: [number, number][] = []
  let from = s.from
  for (const [x0, x1] of taken) {
    if (x0 > from) free.push([from, x0])
    from = Math.max(from, x1)
  }
  if (s.to > from) free.push([from, s.to])
  let best: number | null = null
  for (const [x0, x1] of free) {
    if (x1 - x0 < width - 1e-9) continue
    const c = Math.min(Math.max(at, x0 + width / 2), x1 - width / 2)
    if (best === null || Math.abs(c - at) < Math.abs(best - at)) best = c
  }
  return best
}

export function addOpening(
  f: Floor, wall: string, at: number, kind: OpeningKind, patch: Partial<Omit<Opening, 'wall' | 'kind' | 'at'>> = {},
): { floor: Floor; id: string } | null {
  const props = { ...OPENING_DEFAULTS[kind], hinge: 'a' as const, side: 'left' as const, ...patch }
  const c = fitOpening(f, wall, at, props.width)
  if (c === null) return null
  const d = draft(f)
  const id = newId(d.openings)
  d.openings[id] = { wall, kind, at: c, ...props }
  return { floor: d, id }
}

/** Slides the opening along its wall, or onto another wall; stays where it was when it does not fit. */
export function moveOpening(f: Floor, id: string, at: number, wall?: string): Floor {
  const o = f.openings[id]
  if (!o) return f
  const target = wall ?? o.wall
  const c = fitOpening(f, target, at, o.width, id)
  if (c === null) return f
  const d = draft(f)
  d.openings[id] = { ...o, wall: target, at: c }
  return d
}

/** Changes the opening; a new width is refused when it no longer fits. */
export function setOpening(f: Floor, id: string, patch: Partial<Omit<Opening, 'wall' | 'at'>>): Floor {
  const o = f.openings[id]
  if (!o) return f
  const next = { ...o, ...patch }
  const c = fitOpening(f, o.wall, o.at, next.width, id)
  if (c === null) return f
  const d = draft(f)
  d.openings[id] = { ...next, at: c }
  return d
}

export function removeOpening(f: Floor, id: string): Floor {
  if (!(id in f.openings)) return f
  const d = draft(f)
  delete d.openings[id]
  return d
}

/** The opening cut through its wall: [a-side minus, b-side minus, b-side plus, a-side plus]. */
export function openingRect(f: Floor, id: string): [XY, XY, XY, XY] {
  const o = f.openings[id]
  const w = f.walls[o.wall]
  const [a, b] = ends(f, w)
  const d = unit(sub(b, a))
  const l = dist(a, b)
  const c0 = lerp(a, b, (o.at - o.width / 2) / l), c1 = lerp(a, b, (o.at + o.width / 2) / l)
  const n = mul(perp(d), w.thickness / 2)
  return [sub(c0, n), sub(c1, n), add(c1, n), add(c0, n)]
}
