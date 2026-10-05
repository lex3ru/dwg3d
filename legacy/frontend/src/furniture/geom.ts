/** Plan geometry of placed furniture: footprints, snapping to walls, and
 * checks (item in a wall, items overlapping, a door swing blocked, service
 * zone obstructed). Plan coordinates, meters, Y up; angles counter-clockwise.
 * An item at angle 0 has its back towards +Y and its front towards -Y. */
import type { PlacedItem, PlanData, XY } from '../api'
import { catalogItem, type CatalogItem } from './catalog'

type Ring = [number, number][]
export type Quad = [XY, XY, XY, XY]

export function itemSize(p: PlacedItem, c: CatalogItem = catalogItem(p.item)): [number, number, number] {
  return p.size ?? [c.w, c.d, c.h]
}

/** Unit vectors of the item: along its width and out of its front. */
export function axes(angleDeg: number): { u: XY; f: XY } {
  const a = (angleDeg * Math.PI) / 180
  return { u: [Math.cos(a), Math.sin(a)], f: [Math.sin(a), -Math.cos(a)] }
}

/** Rectangle centred at `c`, half-sizes along u and f. */
function rect(c: XY, u: XY, f: XY, hu: number, hf: number): Quad {
  const p = (su: number, sf: number): XY => [c[0] + u[0] * hu * su + f[0] * hf * sf, c[1] + u[1] * hu * su + f[1] * hf * sf]
  return [p(-1, -1), p(1, -1), p(1, 1), p(-1, 1)]
}

export function footprint(at: XY, angle: number, w: number, d: number, shrink = 0): Quad {
  const { u, f } = axes(angle)
  return rect(at, u, f, Math.max(0.001, w / 2 - shrink), Math.max(0.001, d / 2 - shrink))
}

/** Service zone in front of the item (empty when the item has none). */
export function serviceZone(at: XY, angle: number, w: number, d: number, clear: number): Quad | null {
  if (!clear) return null
  const { u, f } = axes(angle)
  const c: XY = [at[0] + f[0] * (d / 2 + clear / 2), at[1] + f[1] * (d / 2 + clear / 2)]
  return rect(c, u, f, w / 2, clear / 2)
}

// ------------------------------------------------------------ primitives
const sub = (a: XY, b: XY): XY => [a[0] - b[0], a[1] - b[1]]
const dot = (a: XY, b: XY) => a[0] * b[0] + a[1] * b[1]
const cross = (a: XY, b: XY) => a[0] * b[1] - a[1] * b[0]

/** Separating-axis test for two convex polygons. */
export function convexOverlap(a: XY[], b: XY[]): boolean {
  for (const poly of [a, b]) {
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i], q = poly[(i + 1) % poly.length]
      const n: XY = [q[1] - p[1], p[0] - q[0]]
      let amin = Infinity, amax = -Infinity, bmin = Infinity, bmax = -Infinity
      for (const v of a) { const t = dot(v, n); amin = Math.min(amin, t); amax = Math.max(amax, t) }
      for (const v of b) { const t = dot(v, n); bmin = Math.min(bmin, t); bmax = Math.max(bmax, t) }
      if (amax <= bmin || bmax <= amin) return false
    }
  }
  return true
}

function segsCross(a: XY, b: XY, c: XY, d: XY): boolean {
  const r = sub(b, a), s = sub(d, c)
  const den = cross(r, s)
  if (Math.abs(den) < 1e-12) return false
  const t = cross(sub(c, a), s) / den, u = cross(sub(c, a), r) / den
  return t > 0 && t < 1 && u > 0 && u < 1
}

/** Even-odd point in polygon over all rings (holes included). */
export function inRings(p: XY, rings: Ring[]): boolean {
  let c = false
  for (const r of rings) {
    for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
      const [xi, yi] = r[i], [xj, yj] = r[j]
      if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) c = !c
    }
  }
  return c
}

function inConvex(p: XY, q: XY[]): boolean {
  let sign = 0
  for (let i = 0; i < q.length; i++) {
    const c = cross(sub(q[(i + 1) % q.length], q[i]), sub(p, q[i]))
    if (Math.abs(c) < 1e-12) continue
    if (sign === 0) sign = Math.sign(c)
    else if (Math.sign(c) !== sign) return false
  }
  return true
}

type Box = [number, number, number, number]
const bboxOf = (pts: XY[]): Box => {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y) }
  return [x0, y0, x1, y1]
}
const boxesHit = (a: Box, b: Box) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]

/** Convex quad vs arbitrary polygon (rings with holes). */
function quadHitsPoly(q: Quad, rings: Ring[]): boolean {
  for (const r of rings) {
    for (let i = 0; i < r.length - 1; i++) {
      for (let k = 0; k < 4; k++) if (segsCross(q[k], q[(k + 1) % 4], r[i] as XY, r[i + 1] as XY)) return true
      if (inConvex(r[i] as XY, q)) return true
    }
  }
  return q.some((p) => inRings(p, rings))
}

// ------------------------------------------------------------ plan index
export interface Obstacle { rings: Ring[]; box: Box }
export interface Swing { poly: XY[]; box: Box }
export interface PlanIndex {
  walls: Obstacle[]
  /** wall faces for snapping */
  faces: [XY, XY][]
  doors: Swing[]
  rooms: { name: string; area: number; rings: Ring[]; box: Box }[]
}

/** free depth kept in front of a doorway on each side, m */
const DOOR_CLEAR = 0.6

/** Door swing: sector from the open leaf to the closed position (towards the opening centre). */
function swingSector(hinge: XY, tip: XY, center: XY): XY[] {
  const r = Math.hypot(tip[0] - hinge[0], tip[1] - hinge[1])
  const a0 = Math.atan2(tip[1] - hinge[1], tip[0] - hinge[0])
  const a1 = Math.atan2(center[1] - hinge[1], center[0] - hinge[0])
  let da = a1 - a0
  while (da > Math.PI) da -= 2 * Math.PI
  while (da < -Math.PI) da += 2 * Math.PI
  const pts: XY[] = [hinge]
  for (let i = 0; i <= 6; i++) {
    const a = a0 + (da * i) / 6
    pts.push([hinge[0] + Math.cos(a) * r, hinge[1] + Math.sin(a) * r])
  }
  return pts
}

export function indexPlan(plan: PlanData): PlanIndex {
  const walls: Obstacle[] = []
  const faces: [XY, XY][] = []
  for (const poly of [...plan.walls, ...plan.partitions, ...plan.columns]) {
    const rings = poly as Ring[]
    walls.push({ rings, box: bboxOf(rings.flat() as XY[]) })
    for (const r of rings) for (let i = 0; i < r.length - 1; i++) faces.push([r[i] as XY, r[i + 1] as XY])
  }
  const doors: Swing[] = []
  for (const o of plan.openings) {
    if (o.kind === 'window') continue
    const opening = o.poly[0] as XY[]
    if (opening?.length >= 4) {
      // the way through: the opening plus DOOR_CLEAR on both sides of the wall
      const a = opening[0], b = opening[1], c = opening[2]
      const e1 = Math.hypot(b[0] - a[0], b[1] - a[1]), e2 = Math.hypot(c[0] - b[0], c[1] - b[1])
      const [along, across] = e1 >= e2 ? [sub(b, a), sub(c, b)] : [sub(c, b), sub(b, a)]
      const la = Math.hypot(...along) || 1, lc = Math.hypot(...across) || 1
      const u: XY = [along[0] / la, along[1] / la], f: XY = [across[0] / lc, across[1] / lc]
      const way = rect(o.center as XY, u, f, Math.max(0.05, la / 2 - 0.02), lc / 2 + DOOR_CLEAR)
      doors.push({ poly: way, box: bboxOf(way) })
    }
    for (const [hinge, tip] of o.leaves ?? []) {
      const s = swingSector(hinge as XY, tip as XY, o.center as XY)
      doors.push({ poly: s, box: bboxOf(s) })
    }
  }
  const rooms = plan.rooms.map((r) => ({ name: r.name, area: r.area, rings: r.poly as Ring[], box: bboxOf(r.poly.flat() as XY[]) }))
  return { walls, faces, doors, rooms }
}

export function roomAt(idx: PlanIndex, p: XY): string | null {
  for (const r of idx.rooms) if (p[0] >= r.box[0] && p[0] <= r.box[2] && p[1] >= r.box[1] && p[1] <= r.box[3] && inRings(p, r.rings)) return r.name || 'помещение'
  return null
}

// ------------------------------------------------------------ snapping
export interface Pose { at: XY; angle: number; wall: boolean }

const norm360 = (a: number) => ((a % 360) + 360) % 360
const round = (v: number, step: number) => Math.round(v / step) * step

/** Snap an item at the cursor: back to the nearest wall face (turning it to
 * face the room, sliding into a corner when a cross wall is near), else to a
 * 5 cm grid keeping the angle. */
export function snapPose(idx: PlanIndex | null, cursor: XY, angle: number, w: number, d: number, toWall: boolean): Pose {
  const grid = (): Pose => ({ at: [round(cursor[0], 0.05), round(cursor[1], 0.05)], angle, wall: false })
  if (!idx || !toWall) return grid()
  const reach = d / 2 + 0.35
  let best: { a: XY; b: XY; dist: number; n: XY; t: XY } | null = null
  for (const [a, b] of idx.faces) {
    const ab = sub(b, a)
    const L = Math.hypot(ab[0], ab[1])
    if (L < 0.3) continue
    const t: XY = [ab[0] / L, ab[1] / L]
    const s = dot(sub(cursor, a), t)
    if (s < -0.1 || s > L + 0.1) continue
    let n: XY = [-t[1], t[0]]
    let dist = dot(sub(cursor, a), n)
    if (dist < 0) { n = [-n[0], -n[1]]; dist = -dist }
    if (dist > reach || (best && dist >= best.dist)) continue
    // the room side of this face must be free (not the inside of the wall)
    const probe: XY = [a[0] + t[0] * (L / 2) + n[0] * 0.02, a[1] + t[1] * (L / 2) + n[1] * 0.02]
    if (idx.walls.some((wl) => probe[0] >= wl.box[0] && probe[0] <= wl.box[2] && probe[1] >= wl.box[1] && probe[1] <= wl.box[3] && inRings(probe, wl.rings))) continue
    best = { a, b, dist, n, t }
  }
  if (!best) return grid()
  // front = wall normal (into the room); f = (sin a, -cos a)
  const ang = norm360((Math.atan2(best.n[0], -best.n[1]) * 180) / Math.PI)
  const along = dot(sub(cursor, best.a), best.t)
  const gap = 0.005
  let at: XY = [best.a[0] + best.t[0] * along + best.n[0] * (d / 2 + gap), best.a[1] + best.t[1] * along + best.n[1] * (d / 2 + gap)]
  at = [round(at[0], 0.01), round(at[1], 0.01)]
  // corner: a face roughly across the wall near a side of the item
  const { u } = axes(ang)
  let shift = 0
  let sd = 0.25
  for (const [a, b] of idx.faces) {
    const ab = sub(b, a)
    const L = Math.hypot(ab[0], ab[1])
    if (L < 0.2) continue
    const t: XY = [ab[0] / L, ab[1] / L]
    if (Math.abs(dot(t, u)) > 0.1) continue                 // not perpendicular to the wall
    const s = dot(sub(at, a), t)
    if (s < -d / 2 - 0.05 || s > L + d / 2 + 0.05) continue
    const off = dot(sub(a, at), u)                          // face position along the item width
    for (const side of [-1, 1]) {
      const gapSide = side * off - w / 2
      if (Math.abs(gapSide) < sd && gapSide > -w / 2) {
        sd = Math.abs(gapSide)
        shift = side * (gapSide - gap)
      }
    }
  }
  at = [at[0] + u[0] * shift, at[1] + u[1] * shift]
  return { at, angle: ang, wall: true }
}

// ------------------------------------------------------------ checks
export type IssueKind = 'wall' | 'overlap' | 'door' | 'zone'
export interface Issue { kind: IssueKind; with?: string }

export const ISSUE_LABEL: Record<IssueKind, string> = {
  wall: 'пересекает стену',
  overlap: 'пересекается с другим предметом',
  door: 'мешает двери или проходу',
  zone: 'зона обслуживания занята',
}

/** Issues per placed item of one floor. Wall-hung items (mounted above
 * 1 m) only count against walls; flat zones only against each other. */
export function checkFloor(items: PlacedItem[], idx: PlanIndex | null): Map<string, Issue[]> {
  const out = new Map<string, Issue[]>()
  const geo = items.map((p) => {
    const c = catalogItem(p.item)
    const [w, d] = itemSize(p, c)
    const body = footprint(p.at, p.angle, w, d, 0.015)
    const zone = serviceZone(p.at, p.angle, w, d, c.clear ?? 0)
    const high = itemElev(p, c) >= 1
    return { p, c, body, bbox: bboxOf(body), zone, zbox: zone ? bboxOf(zone) : null, high, flat: c.kind === 'zone' }
  })
  const add = (id: string, i: Issue) => {
    const l = out.get(id) ?? []
    if (!l.some((x) => x.kind === i.kind && x.with === i.with)) l.push(i)
    out.set(id, l)
  }
  for (let i = 0; i < geo.length; i++) {
    const g = geo[i]
    if (idx) {
      if (!g.flat && idx.walls.some((wl) => boxesHit(g.bbox, wl.box) && quadHitsPoly(g.body, wl.rings))) add(g.p.id, { kind: 'wall' })
      if (!g.flat && !g.high && idx.doors.some((dr) => boxesHit(g.bbox, dr.box) && convexOverlap(g.body, dr.poly))) add(g.p.id, { kind: 'door' })
      if (g.zone && idx.walls.some((wl) => boxesHit(g.zbox!, wl.box) && quadHitsPoly(shrinkQuad(g.zone!, 0.02), wl.rings))) add(g.p.id, { kind: 'zone' })
    }
    for (let k = 0; k < geo.length; k++) {
      if (k === i) continue
      const o = geo[k]
      if (o.flat !== g.flat || o.high !== g.high) continue
      if (k > i && boxesHit(g.bbox, o.bbox) && convexOverlap(g.body, o.body)) {
        add(g.p.id, { kind: 'overlap', with: o.p.id })
        add(o.p.id, { kind: 'overlap', with: g.p.id })
      }
      if (g.zone && !o.flat && !o.high && boxesHit(g.zbox!, o.bbox) && convexOverlap(shrinkQuad(g.zone, 0.02), o.body)) add(g.p.id, { kind: 'zone', with: o.p.id })
    }
  }
  return out
}

const centroid = (q: Quad): XY => [(q[0][0] + q[2][0]) / 2, (q[0][1] + q[2][1]) / 2]
function shrinkQuad(q: Quad, s: number): Quad {
  const c = centroid(q)
  const k = (p: XY): XY => {
    const v = sub(p, c)
    const L = Math.hypot(v[0], v[1]) || 1
    return [p[0] - (v[0] / L) * s, p[1] - (v[1] / L) * s]
  }
  return [k(q[0]), k(q[1]), k(q[2]), k(q[3])]
}

// ------------------------------------------------------------ CCTV
/** Mounting height of an item (per-item override, else the catalog's). */
export const itemElev = (p: PlacedItem, c: CatalogItem = catalogItem(p.item)) => p.elev ?? c.elev ?? 0

export interface Coverage {
  apex: XY
  /** star-shaped around `apex`: what the camera sees up to its range / identification distance */
  full: XY[]
  ident: XY[]
  /** the far edge of the view (full / identification), from the left side of the angle */
  arc: XY[]
  arcIdent: XY[]
  /** panoramic: the arcs close around the apex */
  closed: boolean
  fov: number
  range: number
  /** what covers: a camera (its view), a Wi-Fi access point (good / usable
   * signal), a fire detector (the protected area), a light source (lit for work / lit) */
  kind?: 'cam' | 'radio' | 'detect' | 'light'
}

/** furniture this tall hides what is behind it */
const OCCLUDER_H = 1.7

export function camParams(p: PlacedItem, c: CatalogItem = catalogItem(p.item)) {
  if (!c.cam) return null
  const fov = p.fov ?? c.cam.fov
  const range = p.range ?? c.cam.range
  return { fov, range, ident: Math.min(range, c.cam.ident * (range / c.cam.range)) }
}

/** Floor area seen by each camera of the floor: rays every degree within
 * the view angle, stopped by walls, partitions, columns and tall furniture
 * (door openings are taken as open, glazing as seen through). */
export function cameraCoverage(items: PlacedItem[], idx: PlanIndex | null): Map<string, Coverage> {
  const out = new Map<string, Coverage>()
  const cams = items.filter((it) => catalogItem(it.item).cam)
  if (!cams.length) return out
  const occl: [XY, XY][] = []
  for (const it of items) {
    const c = catalogItem(it.item)
    const [w, d, h] = itemSize(it, c)
    if (c.cam || h + itemElev(it, c) < OCCLUDER_H || itemElev(it, c) > 0.5) continue
    const q = footprint(it.at, it.angle, w, d)
    for (let k = 0; k < 4; k++) occl.push([q[k], q[(k + 1) % 4]])
  }
  for (const cam of cams) {
    const c = catalogItem(cam.item)
    const prm = camParams(cam, c)!
    const { f } = axes(cam.angle)
    // the lens sits at the front of the body
    const [, d] = itemSize(cam, c)
    const apex: XY = c.kind === 'cam_bullet' ? [cam.at[0] + f[0] * d / 2, cam.at[1] + f[1] * d / 2] : cam.at
    const R = prm.range
    const near = (idx?.faces ?? []).filter(([a, b]) =>
      Math.min(a[0], b[0]) <= apex[0] + R && Math.max(a[0], b[0]) >= apex[0] - R &&
      Math.min(a[1], b[1]) <= apex[1] + R && Math.max(a[1], b[1]) >= apex[1] - R)
    const segs = [...near, ...occl]
    const full = prm.fov >= 360
    const n = Math.max(8, Math.ceil(prm.fov))
    const a0 = Math.atan2(f[1], f[0]) - (full ? Math.PI : (prm.fov * Math.PI) / 360)
    const span = full ? 2 * Math.PI : (prm.fov * Math.PI) / 180
    const far: XY[] = [], idp: XY[] = []
    for (let i = 0; i <= n; i++) {
      if (full && i === n) break
      const a = a0 + (span * i) / n
      const dir: XY = [Math.cos(a), Math.sin(a)]
      let t = R
      for (const [p, q] of segs) {
        const hit = rayHit(apex, dir, p, q)
        if (hit > 1e-3 && hit < t) t = hit
      }
      far.push([apex[0] + dir[0] * t, apex[1] + dir[1] * t])
      const ti = Math.min(t, prm.ident)
      idp.push([apex[0] + dir[0] * ti, apex[1] + dir[1] * ti])
    }
    out.set(cam.id, {
      apex, fov: prm.fov, range: R, arc: far, arcIdent: idp, closed: full,
      full: full ? far : [apex, ...far], ident: full ? idp : [apex, ...idp],
    })
  }
  return out
}

// Wi-Fi: a log-distance path loss model with a loss per wall face crossed
const RADIO_1M = 40            // dB of path loss at 1 m (2.4 GHz)
const RADIO_N = 2.2            // path loss exponent indoors
const FACE_DB = 3.5            // per face of a wall or partition (a wall ~ 7 dB)
export const RADIO_GOOD = -67, RADIO_USABLE = -75       // dBm

// Lighting: illuminance on the working plane from a single source
export const LUX_WORK = 300, LUX_LIT = 100       // lx: enough for work / lit
const WORK_PLANE = 0.8         // m above the floor
const LIGHT_MAX = 30           // m, the longest radius drawn

/** The lit area of a light source (params.light) by its flux, beam angle and
 * mounting height: the flux spreads evenly within the beam, so the illuminance
 * of the working plane at distance r from the point under the source is
 * I·H / (H² + r²)^1.5 (I — luminous intensity, H — height above the plane).
 * `under`: lx right under the source; `work` / `lit`: radii (m) where it is
 * at least LUX_WORK / LUX_LIT. */
export function lightZone(p: PlacedItem, c: CatalogItem = catalogItem(p.item)) {
  const l = c.params?.light
  if (!l) return null
  const elev = itemElev(p, c)
  // light leaves the bottom of a hung luminaire and the top of a standing one
  const src = elev >= 1 ? elev : elev + itemSize(p, c)[2]
  const H = Math.max(0.2, src - WORK_PLANE)
  const half = (Math.min(l.beam, 360) * Math.PI) / 360
  const I = l.flux / (2 * Math.PI * (1 - Math.cos(half)))
  const edge = l.beam < 170 ? H * Math.tan(half) : LIGHT_MAX
  const reach = (lux: number) => Math.min(edge, LIGHT_MAX, Math.sqrt(Math.max(0, ((I * H) / lux) ** (2 / 3) - H * H)))
  return { under: I / (H * H), work: reach(LUX_WORK), lit: reach(LUX_LIT) }
}

/** Radio coverage of Wi-Fi access points (params.radio), the floor protected
 * by fire detectors (params.detect) and the area lit by light sources
 * (params.light): rays in all directions; radio fades with distance and loses
 * FACE_DB at every wall face it crosses, a detector's area and light stop at
 * walls. `full` / `ident`: usable / good signal (detectors: both the area;
 * light: lit / lit enough for work). */
export function systemsCoverage(items: PlacedItem[], idx: PlanIndex | null): Map<string, Coverage> {
  const out = new Map<string, Coverage>()
  for (const it of items) {
    const c = catalogItem(it.item)
    const radio = c.params?.radio, detect = c.params?.detect
    const light = radio || detect ? null : lightZone(it, c)
    if (!radio && !detect && !(light && light.lit > 0.05)) continue
    const R = radio ? radio.range : detect ? detect.radius : light!.lit
    const apex = it.at
    const segs = (idx?.faces ?? []).filter(([a, b]) =>
      Math.min(a[0], b[0]) <= apex[0] + R && Math.max(a[0], b[0]) >= apex[0] - R &&
      Math.min(a[1], b[1]) <= apex[1] + R && Math.max(a[1], b[1]) >= apex[1] - R)
    const n = 180
    const good: XY[] = [], usable: XY[] = []
    for (let i = 0; i < n; i++) {
      const a = (2 * Math.PI * i) / n
      const dir: XY = [Math.cos(a), Math.sin(a)]
      const hits: number[] = []
      for (const [p, q] of segs) {
        const t = rayHit(apex, dir, p, q)
        if (t > 1e-3 && t < R) hits.push(t)
      }
      hits.sort((x, y) => x - y)
      let tg = R, tu = R
      if (detect) {
        tg = tu = hits.length ? hits[0] : R
      } else if (light) {
        tu = hits.length ? hits[0] : R
        tg = Math.min(tu, light.work)
      } else {
        const s1 = radio!.tx - RADIO_1M
        const reach = (loss: number, thr: number) => Math.max(1, 10 ** ((s1 - loss - thr) / (10 * RADIO_N)))
        let loss = 0, from = 0, gotG = false, gotU = false
        for (const end of [...hits, R]) {
          const dg = reach(loss, RADIO_GOOD), du = reach(loss, RADIO_USABLE)
          if (!gotG && dg <= end) { tg = Math.max(dg, from); gotG = true }
          if (!gotU && du <= end) { tu = Math.max(du, from); gotU = true }
          if (gotG && gotU) break
          loss += FACE_DB
          from = end
        }
      }
      good.push([apex[0] + dir[0] * tg, apex[1] + dir[1] * tg])
      usable.push([apex[0] + dir[0] * tu, apex[1] + dir[1] * tu])
    }
    out.set(it.id, { apex, fov: 360, range: R, arc: usable, arcIdent: good, closed: true, full: usable, ident: good,
      kind: radio ? 'radio' : detect ? 'detect' : 'light' })
  }
  return out
}

/** Distance along the ray (o, d) to segment pq, or Infinity. */
function rayHit(o: XY, d: XY, p: XY, q: XY): number {
  const e = sub(q, p)
  const den = cross(d, e)
  if (Math.abs(den) < 1e-12) return Infinity
  const w = sub(p, o)
  const t = cross(w, e) / den, u = cross(w, d) / den
  return u >= 0 && u <= 1 && t > 0 ? t : Infinity
}

export interface RoomCover { name: string; area: number; covered: number; ident: number }

/** Share of each room seen by the cameras (rooms that at least one camera
 * sees). Only the cameras' view areas are sampled, so a huge hall with one
 * camera costs no more than a small room. */
export function roomCoverage(idx: PlanIndex | null, cov: Map<string, Coverage>): RoomCover[] {
  if (!idx || !cov.size) return []
  const polys = [...cov.values()].map((c) => ({ full: c.full, ident: c.ident, box: bboxOf(c.full) }))
  const out: RoomCover[] = []
  for (const r of idx.rooms) {
    const hits = polys.filter((p) => boxesHit(p.box, r.box))
    if (!hits.length || r.area <= 0) continue
    // sample the union of the view boxes clipped to the room box
    const b: Box = [Infinity, Infinity, -Infinity, -Infinity]
    for (const h of hits) { b[0] = Math.min(b[0], h.box[0]); b[1] = Math.min(b[1], h.box[1]); b[2] = Math.max(b[2], h.box[2]); b[3] = Math.max(b[3], h.box[3]) }
    b[0] = Math.max(b[0], r.box[0]); b[1] = Math.max(b[1], r.box[1]); b[2] = Math.min(b[2], r.box[2]); b[3] = Math.min(b[3], r.box[3])
    const step = Math.max(0.2, Math.sqrt(((b[2] - b[0]) * (b[3] - b[1])) / 20000))
    // only room edges that can cross a rightward ray from a sample matter
    const edges: [XY, XY][] = []
    for (const ring of r.rings) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const p = ring[i] as XY, q = ring[j] as XY
        if (Math.max(p[1], q[1]) < b[1] || Math.min(p[1], q[1]) > b[3] || Math.max(p[0], q[0]) < b[0]) continue
        edges.push([p, q])
      }
    }
    const inRoom = (pt: XY) => {
      let c = false
      for (const [[xi, yi], [xj, yj]] of edges) {
        if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c
      }
      return c
    }
    let seen = 0, ident = 0
    for (let x = b[0] + step / 2; x < b[2]; x += step) {
      for (let y = b[1] + step / 2; y < b[3]; y += step) {
        const pt: XY = [x, y]
        const inView = hits.filter((h) => pt[0] >= h.box[0] && pt[0] <= h.box[2] && pt[1] >= h.box[1] && pt[1] <= h.box[3] && inRings(pt, [h.full]))
        if (!inView.length || !inRoom(pt)) continue
        seen++
        if (inView.some((h) => inRings(pt, [h.ident]))) ident++
      }
    }
    const a = step * step
    if (seen) out.push({ name: r.name || 'помещение', area: r.area, covered: Math.min(1, (seen * a) / r.area), ident: Math.min(1, (ident * a) / r.area) })
  }
  return out.sort((a, b) => a.covered - b.covered)
}
