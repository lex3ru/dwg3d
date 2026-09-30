/** Routes of people across floors and the checks of functional layers.
 *
 * A route is a list of stops; between two stops on one floor the way is the
 * A* path over the floor plan (route.ts); between floors it goes to a
 * staircase or lift that is found on both floors at about the same place,
 * and the fastest such connection wins. The result is stored with the route
 * (the server keeps it as a cache: see backend/dwg3d/shapes.py).
 *
 * Checks: routes of flows that must not meet (clean / dirty...) crossing or
 * running side by side, and flows entering zones forbidden to them. */
import type { FloorMeta, Result, XY } from '../api'
import { findPath, type Grid } from './route'

export interface RouteStop { floor: string; at: XY; room?: number | null; label?: string }
export interface Segment { floor: string; pts: XY[] }
export interface RouteProps {
  flow: string
  name: string
  stops: RouteStop[]
  path?: Segment[] | null
  length?: number
  time?: number
  floors_changed?: number
  build?: number
  problem?: string
}
export interface ZoneProps { zone: string; name: string }
export interface CableProps { cable: string; name: string; reserve?: number }

export interface Rules {
  flows: Record<string, { name: string; color: string }>
  flow_conflicts: [string, string][]
  zone_kinds: Record<string, { name: string; color: string }>
  zone_forbidden: Record<string, string[]>
  cables: Record<string, { name: string; color: string }>
}

export const WALK_SPEED = 1.3               // m/s
const STAIR_S_PER_FLOOR = 15
const LIFT_WAIT_S = 30, LIFT_S_PER_FLOOR = 4
const SAME_SHAFT_M = 4                      // a stair / lift on two floors: within this distance in plan

export interface Connector { kind: 'stair' | 'lift'; floor: string; at: XY }

/** Stairs and lifts of a build in plan coordinates. */
export function connectors(result: Result): Connector[] {
  const [cx, cy] = result.center ?? [0, 0]
  return (result.pois ?? []).map((p) => ({ kind: p.kind, floor: p.floor, at: [p.pos[0] + cx, -p.pos[2] + cy] as XY }))
}

const dist = (a: XY, b: XY) => Math.hypot(a[0] - b[0], a[1] - b[1])

export interface Computed { path: Segment[]; length: number; time: number; floors_changed: number; problem?: string }

/** The way through all stops. `grid(floor)` gives the walkable grid of a floor. */
export async function computeRoute(stops: RouteStop[], floors: FloorMeta[], conns: Connector[],
  grid: (floor: string) => Promise<Grid | null>, label: (st: RouteStop, i: number) => string): Promise<Computed> {
  const order = [...floors].sort((a, b) => (a.elevation ?? 0) - (b.elevation ?? 0)).map((f) => f.id)
  const out: Computed = { path: [], length: 0, time: 0, floors_changed: 0 }
  const add = (floor: string, pts: XY[]) => {
    const last = out.path[out.path.length - 1]
    if (last && last.floor === floor) last.pts.push(...pts.slice(1))
    else out.path.push({ floor, pts: [...pts] })
  }
  for (let i = 1; i < stops.length; i++) {
    const a = stops[i - 1], b = stops[i]
    const ga = await grid(a.floor)
    if (a.floor === b.floor) {
      const p = ga ? findPath(ga, a.at, b.at) : null
      if (!p) return { ...out, problem: `Нет прохода от «${label(a, i - 1)}» до «${label(b, i)}»` }
      add(a.floor, p.pts)
      out.length += p.length
      out.time += p.length / WALK_SPEED
      continue
    }
    const gb = await grid(b.floor)
    const n = Math.abs(order.indexOf(a.floor) - order.indexOf(b.floor))
    // the nearest connectors of the start floor that also exist on the other floor
    const pairs = conns.filter((c) => c.floor === a.floor)
      .map((ca) => ({ ca, cb: conns.find((c) => c.floor === b.floor && c.kind === ca.kind && dist(c.at, ca.at) < SAME_SHAFT_M) }))
      .filter((x): x is { ca: Connector; cb: Connector } => !!x.cb)
      .sort((x, y) => dist(a.at, x.ca.at) + dist(x.cb.at, b.at) - dist(a.at, y.ca.at) - dist(y.cb.at, b.at))
      .slice(0, 4)
    let best: { t: number; len: number; pa: XY[]; pb: XY[] } | null = null
    for (const { ca, cb } of pairs) {
      const pa = ga ? findPath(ga, a.at, ca.at) : null
      const pb = gb ? findPath(gb, cb.at, b.at) : null
      if (!pa || !pb) continue
      const vertical = ca.kind === 'lift' ? LIFT_WAIT_S + LIFT_S_PER_FLOOR * n : STAIR_S_PER_FLOOR * n
      const t = (pa.length + pb.length) / WALK_SPEED + vertical
      if (!best || t < best.t) best = { t, len: pa.length + pb.length, pa: pa.pts, pb: pb.pts }
    }
    if (!best) {
      const fa = floors.find((f) => f.id === a.floor)?.name ?? a.floor, fb = floors.find((f) => f.id === b.floor)?.name ?? b.floor
      return { ...out, problem: `Нет лестницы или лифта, соединяющих «${fa}» и «${fb}» на пути к «${label(b, i)}»` }
    }
    add(a.floor, best.pa)
    add(b.floor, best.pb)
    out.length += best.len
    out.time += best.t
    out.floors_changed += n
  }
  out.length = Math.round(out.length * 10) / 10
  out.time = Math.round(out.time)
  return out
}

// ---------------------------------------------------------------- checks ---
export interface RouteRef { id: string; name: string; flow: string; path: Segment[] }
export interface ZoneRef { id: string; name: string; zone: string; floor: string; pts: XY[] }
export interface Conflict {
  kind: 'flows' | 'zone'
  a: string                  // route id
  b: string                  // route id or zone id
  floor: string
  at: XY
  text: string
}

/** Points along a polyline, about every `step` metres. */
function samples(pts: XY[], step = 0.5): XY[] {
  const out: XY[] = pts.length ? [pts[0]] : []
  for (let k = 1; k < pts.length; k++) {
    const [x0, y0] = pts[k - 1], [x1, y1] = pts[k]
    const n = Math.max(1, Math.ceil(dist(pts[k - 1], pts[k]) / step))
    for (let j = 1; j <= n; j++) out.push([x0 + ((x1 - x0) * j) / n, y0 + ((y1 - y0) * j) / n])
  }
  return out
}

function segDist(p: XY, a: XY, b: XY): number {
  const dx = b[0] - a[0], dy = b[1] - a[1]
  const l2 = dx * dx + dy * dy
  const t = l2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)) : 0
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
}

function inPolygon(p: XY, poly: XY[]): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j]
    if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

const NEAR_M = 0.6          // ways closer than this share the corridor

/** Where routes of flows that must not meet cross or run side by side, and
 * where routes enter zones forbidden to their flow (one point per pair and floor). */
export function checkFlows(routes: RouteRef[], zones: ZoneRef[], rules: Rules): Conflict[] {
  const bad = new Set(rules.flow_conflicts.flatMap(([x, y]) => [`${x}|${y}`, `${y}|${x}`]))
  const flow = (f: string) => rules.flows[f]?.name ?? f
  const out: Conflict[] = []
  for (let i = 0; i < routes.length; i++) {
    for (let j = i + 1; j < routes.length; j++) {
      const a = routes[i], b = routes[j]
      if (!bad.has(`${a.flow}|${b.flow}`)) continue
      for (const sa of a.path) {
        for (const sb of b.path) {
          if (sa.floor !== sb.floor || sb.pts.length < 2) continue
          const hit = samples(sa.pts).find((p) => sb.pts.some((q, k) => k > 0 && segDist(p, sb.pts[k - 1], q) < NEAR_M))
          if (hit) {
            out.push({ kind: 'flows', a: a.id, b: b.id, floor: sa.floor, at: hit,
              text: `«${a.name || flow(a.flow)}» (${flow(a.flow).toLowerCase()}) и «${b.name || flow(b.flow)}» (${flow(b.flow).toLowerCase()}) пересекаются` })
            break
          }
        }
      }
    }
  }
  for (const r of routes) {
    for (const z of zones) {
      if (!(rules.zone_forbidden[z.zone] ?? []).includes(r.flow)) continue
      const hit = r.path.filter((sg) => sg.floor === z.floor).flatMap((sg) => samples(sg.pts)).find((p) => inPolygon(p, z.pts))
      if (hit) {
        out.push({ kind: 'zone', a: r.id, b: z.id, floor: z.floor, at: hit,
          text: `«${r.name || flow(r.flow)}» (${flow(r.flow).toLowerCase()}) заходит в зону «${z.name || rules.zone_kinds[z.zone]?.name || z.zone}»` })
      }
    }
  }
  return out
}

export const fmtTime = (s: number) => (s < 60 ? `${Math.round(s)} с` : `${Math.round(s / 60)} мин`)
