/**
 * Columns and stairs of a drawn floor: their outlines on the plan, the
 * treads of a flight, and putting, moving, changing and taking them away.
 * Every edit returns a new floor, as the wall edits do.
 */
import { draft } from './graph.ts'
import { newId, type Column, type Floor, type Stair } from './model.ts'
import { add, mul, type XY } from './vec.ts'

export const COLUMN_DEFAULT: Omit<Column, 'at'> = { shape: 'rect', width: 0.4, depth: 0.4, angle: 0 }
/** a step this high or less: the flight's steps for a floor's height */
export const RISER = 0.17
export const STAIR_WIDTH = 1.0

const axes = (deg: number): { u: XY; v: XY } => {
  const r = (deg * Math.PI) / 180
  return { u: [Math.cos(r), Math.sin(r)], v: [-Math.sin(r), Math.cos(r)] }
}
const rect = (at: XY, deg: number, along: number, across: number): XY[] => {
  const { u, v } = axes(deg)
  const p = (a: number, b: number) => add(add(at, mul(u, (a * along) / 2)), mul(v, (b * across) / 2))
  return [p(-1, -1), p(1, -1), p(1, 1), p(-1, 1)]
}

/** The column's outline: its rectangle, or a circle as a 24-gon. */
export function columnRing(c: Column): XY[] {
  if (c.shape === 'round') {
    const r = c.width / 2
    return Array.from({ length: 24 }, (_, i) => add(c.at, [r * Math.cos((i * Math.PI) / 12), r * Math.sin((i * Math.PI) / 12)]))
  }
  return rect(c.at, c.angle, c.depth, c.width)
}

/** The flight's outline: from its foot (the first two points) to its head. */
export function stairRing(s: Stair): XY[] {
  return rect(s.at, s.angle, s.length, s.width)
}

/** The foot and the head of the flight, on its middle line. */
export function stairEnds(s: Stair): [XY, XY] {
  const { u } = axes(s.angle)
  return [add(s.at, mul(u, -s.length / 2)), add(s.at, mul(u, s.length / 2))]
}

/** The lines between the treads, foot to head. */
export function stairTreads(s: Stair): [XY, XY][] {
  const { u, v } = axes(s.angle)
  const [foot] = stairEnds(s)
  const going = s.length / s.steps
  return Array.from({ length: s.steps - 1 }, (_, i) => {
    const c = add(foot, mul(u, going * (i + 1)))
    return [add(c, mul(v, -s.width / 2)), add(c, mul(v, s.width / 2))] as [XY, XY]
  })
}

/** The steps a flight needs to climb `height`, none higher than RISER. */
export const stepsFor = (height: number) => Math.max(2, Math.ceil(height / RISER - 1e-9))

export function addColumn(f: Floor, at: XY, props: Partial<Omit<Column, 'at'>> = {}): { floor: Floor; id: string } {
  const d = draft(f)
  d.columns = { ...(f.columns ?? {}) }
  const id = newId(d.columns)
  d.columns[id] = { ...COLUMN_DEFAULT, ...props, at }
  return { floor: d, id }
}

/** A flight from its foot to its head, as wide as asked; as many steps as the floor's height needs. */
export function addStair(f: Floor, foot: XY, head: XY, width = STAIR_WIDTH): { floor: Floor; id: string } | null {
  const length = Math.hypot(head[0] - foot[0], head[1] - foot[1])
  if (length < 0.5) return null
  const d = draft(f)
  d.stairs = { ...(f.stairs ?? {}) }
  const id = newId(d.stairs)
  d.stairs[id] = {
    at: [(foot[0] + head[0]) / 2, (foot[1] + head[1]) / 2], width, length,
    angle: (Math.atan2(head[1] - foot[1], head[0] - foot[0]) * 180) / Math.PI, steps: stepsFor(f.height),
  }
  return { floor: d, id }
}

export function setColumn(f: Floor, id: string, patch: Partial<Column>): Floor {
  if (!f.columns?.[id]) return f
  return { ...f, columns: { ...f.columns, [id]: { ...f.columns[id], ...patch } } }
}

export function setStair(f: Floor, id: string, patch: Partial<Stair>): Floor {
  if (!f.stairs?.[id]) return f
  return { ...f, stairs: { ...f.stairs, [id]: { ...f.stairs[id], ...patch } } }
}

export function removeColumn(f: Floor, id: string): Floor {
  if (!f.columns?.[id]) return f
  return { ...f, columns: Object.fromEntries(Object.entries(f.columns).filter(([k]) => k !== id)) }
}

export function removeStair(f: Floor, id: string): Floor {
  if (!f.stairs?.[id]) return f
  return { ...f, stairs: Object.fromEntries(Object.entries(f.stairs).filter(([k]) => k !== id)) }
}
