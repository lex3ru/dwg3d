/**
 * What a placed object looks like on the plan from above: a symbol by the
 * shape its catalog type names (the viewer's procedural models), in metres of
 * the object's own frame — x along its width, y from its back (negative) to
 * its front (positive). Fill and stroke come from the group around it; lines
 * are drawn with `fill="none"`, solid parts (a backrest, a screen) opaque.
 */
import type { ReactNode } from 'react'
import type { Asset, CatalogType } from '../api'
import type { Item } from './FloorPlan'

/** half-width, half-depth, line width */
type Draw = (hw: number, hd: number, k: number) => ReactNode

const SOLID = { fillOpacity: 0.9, stroke: 'none' } as const
const NONE = { fill: 'none' } as const

const box: Draw = (hw, hd, k) => <rect x={-hw} y={-hd} width={2 * hw} height={2 * hd} rx={Math.min(k, hw / 4, hd / 4)} />
const round: Draw = (hw, hd) => <ellipse rx={hw} ry={hd} />
const inner = (hw: number, hd: number, inset: number) => (
  <rect x={-hw * (1 - inset)} y={-hd * (1 - inset)} width={2 * hw * (1 - inset)} height={2 * hd * (1 - inset)} {...NONE} />)
/** a strip along the back: a backrest, a headboard, a screen on a desk */
const back = (hw: number, hd: number, share = 0.3, max = 0.12) => (
  <rect x={-hw} y={-hd} width={2 * hw} height={Math.min(2 * hd * share, max)} {...SOLID} />)
/** a strip along the front: a screen facing the viewer */
const front = (hw: number, hd: number, share = 0.3, max = 0.08) => {
  const t = Math.min(2 * hd * share, max)
  return <rect x={-hw} y={hd - t} width={2 * hw} height={t} {...SOLID} />
}
/** armrests and a backrest drawn as one line: a sofa, an armchair */
const arms = (hw: number, hd: number) => {
  const a = Math.min(hw * 0.25, 0.18), b = Math.min(hd * 0.35, 0.2)
  return <path d={`M${-hw + a} ${hd}V${-hd + b}H${hw - a}V${hd}`} {...NONE} />
}
const pillow = (hw: number, hd: number) => {
  const w = Math.min(hw * 0.7, 0.3), t = Math.min(hd * 0.3, 0.2), y = -hd + Math.min(hd * 0.12, 0.06)
  return <rect x={-w} y={y} width={2 * w} height={t} rx={t / 3} {...NONE} />
}
const wheels = (hw: number, hd: number) => {
  const r = Math.min(0.05, hw * 0.15, hd * 0.15)
  return <>{[[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy], i) => <circle key={i} cx={sx * (hw - r)} cy={sy * (hd - r)} r={r} {...SOLID} />)}</>
}
const diagonal: Draw = (hw, hd) => <line x1={-hw} y1={-hd} x2={hw} y2={hd} {...NONE} />
const cross: Draw = (hw, hd) => <path d={`M${-hw} ${-hd}L${hw} ${hd}M${-hw} ${hd}L${hw} ${-hd}`} {...NONE} />
const plus: Draw = (hw, hd) => <path d={`M${-hw} 0H${hw}M0 ${-hd}V${hd}`} {...NONE} />
const dot = (hw: number, hd: number) => <ellipse rx={Math.max(hw * 0.25, 0.02)} ry={Math.max(hd * 0.25, 0.02)} {...SOLID} />
/** lines across the width every `step` metres: a radiator's sections, a row of lockers */
const hatch = (hw: number, hd: number, step: number, cap = 12) => {
  const n = Math.min(cap, Math.max(1, Math.round((2 * hw) / step)))
  return <path d={Array.from({ length: n - 1 }, (_, i) => `M${-hw + ((i + 1) * 2 * hw) / n} ${-hd}V${hd}`).join('')} {...NONE} />
}
/** the camera's view: a wedge out of the front */
const wedge = (hw: number, hd: number, half = 30) => {
  const r = Math.max(hw, hd) * 2.2, a = (half * Math.PI) / 180
  return <path d={`M0 0L${-r * Math.sin(a)} ${r * Math.cos(a)}A${r} ${r} 0 0 0 ${r * Math.sin(a)} ${r * Math.cos(a)}Z`} fillOpacity={0.12} />
}
/** rays around a lamp */
const rays = (hw: number, hd: number) => {
  const r = Math.max(hw, hd) * 1.5
  return <path d={`M${-r} 0H${r}M0 ${-r}V${r}`} {...NONE} />
}

const seat: Draw = (hw, hd, k) => <>{box(hw, hd, k)}{back(hw, hd)}</>
const sofa: Draw = (hw, hd, k) => <>{box(hw, hd, k)}{arms(hw, hd)}</>
const couch: Draw = (hw, hd, k) => <>{box(hw, hd, k)}{pillow(hw, hd)}</>
const device: Draw = (hw, hd, k) => <>{box(hw, hd, k)}{inner(hw, hd, 0.25)}</>
const ring: Draw = (hw, hd, k) => {
  const r = Math.min(hw, hd) * 0.85
  return <>{box(hw, hd, k)}<circle r={r} {...NONE} /><circle r={r * 0.45} {...NONE} /></>
}
const cam: Draw = (hw, hd) => <>{round(hw, hd, 0)}{dot(hw, hd)}</>

const DRAW: Record<string, Draw> = {
  box,
  table: (hw, hd, k) => (Math.abs(hw - hd) < Math.max(hw, hd) * 0.15 ? round(hw, hd, k) : box(hw, hd, k)),
  desk: box, counter: box, reception: box, nightstand: box, stadiometer: box,
  desk_pc: (hw, hd, k) => {
    const w = Math.min(hw * 0.45, 0.3), t = Math.min(hd * 0.15, 0.06)
    return <>{box(hw, hd, k)}<rect x={-w} y={-hd + Math.min(hd * 0.15, 0.06)} width={2 * w} height={t} {...SOLID} /></>
  },
  counter_sink: (hw, hd, k) => <>{box(hw, hd, k)}<ellipse cx={hw * 0.4} rx={Math.min(hw * 0.3, 0.22)} ry={Math.min(hd * 0.6, 0.18)} {...NONE} /></>,
  hood: (hw, hd, k) => <>{box(hw, hd, k)}{inner(hw, hd, 0.2)}</>,
  chair: seat, exam_chair: sofa, armchair_med: sofa, dental: sofa, sofa,
  chair_office: (hw, hd) => <>
    <ellipse rx={hw * 0.85} ry={hd * 0.85} />
    <path d={`M${-hw * 0.8} ${-hd * 0.2}A${hw} ${hd} 0 0 1 ${hw * 0.8} ${-hd * 0.2}`} {...NONE} strokeWidth={Math.min(hw, hd) * 0.3} />
  </>,
  stool: round,
  seats: (hw, hd, k) => {
    const n = Math.max(1, Math.round((2 * hw) / 0.55)), s = (2 * hw) / n
    return <>{box(hw, hd, k)}{hatch(hw, hd, s, n)}{back(hw, hd)}</>
  },
  couch, bed: couch,
  gurney: (hw, hd, k) => <>{couch(hw, hd, k)}{wheels(hw, hd)}</>,
  wheelchair: (hw, hd, k) => <>
    {box(hw * 0.75, hd * 0.6, k)}{back(hw * 0.75, hd * 0.6)}
    <path d={`M${-hw} ${-hd * 0.5}V${hd * 0.7}M${hw} ${-hd * 0.5}V${hd * 0.7}`} {...NONE} strokeWidth={k * 2.5} />
  </>,
  cabinet: (hw, hd, k) => <>{box(hw, hd, k)}{diagonal(hw, hd, k)}</>,
  cabinet_glass: (hw, hd, k) => <>{box(hw, hd, k)}{diagonal(hw, hd, k)}{inner(hw, hd, 0.15)}</>,
  fridge: (hw, hd, k) => <>{box(hw, hd, k)}{diagonal(hw, hd, k)}{dot(hw * 0.5, hd * 0.5)}</>,
  lockers: (hw, hd, k) => <>{box(hw, hd, k)}{hatch(hw, hd, 0.4)}</>,
  rack: (hw, hd, k) => <>{box(hw, hd, k)}{cross(hw, hd, k)}</>,
  server: (hw, hd, k) => <>{box(hw, hd, k)}{cross(hw, hd, k)}</>,
  kiosk: (hw, hd, k) => <>{box(hw, hd, k)}{front(hw, hd)}</>,
  cooler: (hw, hd, k) => <>{round(hw, hd, k)}{dot(hw, hd)}</>,
  plant: (hw, hd, k) => <>{round(hw, hd, k)}{plus(hw, hd, k)}{cross(hw * 0.7, hd * 0.7, k)}</>,
  bin: (hw, hd, k) => <>{round(hw, hd, k)}<ellipse rx={hw * 0.6} ry={hd * 0.6} {...NONE} /></>,
  extinguisher: (hw, hd, k) => <>{round(hw, hd, k)}{dot(hw * 1.6, hd * 1.6)}</>,
  device, ultrasound: (hw, hd, k) => <>{box(hw, hd, k)}{back(hw, hd, 0.25, 0.1)}{wheels(hw, hd)}</>,
  xray: (hw, hd, k) => <>{box(hw, hd, k)}<circle r={Math.min(hw, hd) * 0.6} {...NONE} /></>,
  ct: ring, mri: ring,
  screen_tv: (hw, hd, k) => <>{box(hw, hd, k)}{front(hw, hd, 0.4)}</>,
  iv: (hw, hd, k) => <>{round(hw, hd, k)}{plus(hw, hd, k)}</>,
  cart: (hw, hd, k) => <>{box(hw, hd, k)}{wheels(hw, hd)}</>,
  sink: (hw, hd, k) => <>{box(hw, hd, k)}<ellipse rx={hw * 0.6} ry={hd * 0.55} cy={hd * 0.1} {...NONE} />{dot(hw * 0.3, hd * 0.3)}</>,
  toilet: (hw, hd) => <>
    <rect x={-hw} y={-hd} width={2 * hw} height={hd * 0.6} />
    <ellipse cy={hd * 0.35} rx={hw * 0.8} ry={hd * 0.6} />
  </>,
  radiator: (hw, hd, k) => <>{box(hw, hd, k)}{hatch(hw, hd, 0.1)}</>,
  ac: (hw, hd, k) => <>{box(hw, hd, k)}<path d={`M${-hw * 0.8} ${-hd * 0.3}H${hw * 0.8}M${-hw * 0.8} ${hd * 0.3}H${hw * 0.8}`} {...NONE} /></>,
  panel: (hw, hd, k) => <>{box(hw, hd, k)}<path d={`M${-hw * 0.3} ${-hd * 0.7}L${hw * 0.15} ${-hd * 0.1}L${-hw * 0.15} ${hd * 0.1}L${hw * 0.3} ${hd * 0.7}`} {...NONE} /></>,
  device_wall: (hw, hd, k) => <>{box(hw, hd, k)}<line x1={0} y1={0} x2={0} y2={hd * 1.6} {...NONE} /></>,
  cam_dome: cam,
  cam_fisheye: (hw, hd) => <>{cam(hw, hd, 0)}<ellipse rx={hw * 0.6} ry={hd * 0.6} {...NONE} /></>,
  cam_bullet: (hw, hd) => <>{wedge(hw, hd)}{cam(hw, hd, 0)}</>,
  cam_ptz: (hw, hd, k) => <>{wedge(hw, hd, 50)}{round(hw, hd, k)}{plus(hw * 0.6, hd * 0.6, k)}</>,
  lamp_panel: (hw, hd, k) => <>{box(hw, hd, k)}{cross(hw, hd, k)}</>,
  lamp_round: (hw, hd, k) => <>{rays(hw, hd)}{round(hw, hd, k)}{dot(hw * 0.6, hd * 0.6)}</>,
  lamp_floor: (hw, hd, k) => <>{rays(hw, hd)}{round(hw, hd, k)}{dot(hw, hd)}</>,
  zone: (hw, hd, k) => <rect x={-hw} y={-hd} width={2 * hw} height={2 * hd} fillOpacity={0.08} strokeDasharray={`${k * 3} ${k * 2}`} />,
  folding: (hw, hd, k) => {
    const n = 3, s = (2 * hw) / n
    return <path d={`M${-hw} ${-hd}` + Array.from({ length: n }, (_, i) => `L${-hw + (i + 1) * s} ${i % 2 ? -hd : hd}`).join('')} {...NONE} strokeWidth={k * 2} />
  },
}

/** The symbol of a shape: a box for one the catalog does not know. */
export const glyph = (shape: string, hw: number, hd: number, k: number): ReactNode => (DRAW[shape] ?? box)(hw, hd, k)
export const SHAPES = Object.keys(DRAW)

/** An object as the plan draws it: to its type's size and shape; a half-metre box when the catalog does not know the type. */
export const itemOf = (a: Asset, types: Map<string, CatalogType>, rest: Pick<Item, 'tone' | 'chosen'>): Item => {
  const t = types.get(a.type_id)
  return { id: a.id, x: a.x!, y: a.y!, angle: a.angle ?? 0, w: t?.size[0] || 0.5, d: t?.size[1] || 0.5, shape: t?.shape ?? 'box',
    title: a.inventory_no ? `${a.type_name} · ${a.inventory_no}` : a.type_name, ...rest }
}
