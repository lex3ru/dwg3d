export type Role = 'walls' | 'columns' | 'windows' | 'doors' | 'rooms' | 'grid' | 'ignore' | 'insulation' | 'stairs'

export type V3 = [number, number, number]

export interface RoomMeta {
  node: string
  name: string
  area: number
  type?: string
  label_pos: V3
  /** text on the floor: rotation about Y (rad), wrap width and room depth, m */
  label_angle?: number
  label_w?: number
  label_d?: number
}

export interface RoomType { type: string; label: string; color: string }

export interface Entrance {
  id: string
  label: string
  name: string
  main: boolean
  floor: string
  width: number
  pos: V3
  /** outward direction, glTF X / Z */
  dir: [number, number]
}

export interface Poi { kind: 'stair' | 'lift'; floor: string; pos: V3 }

export interface Candidate {
  id: string
  source: string
  name: string
  level: number | null
  kind: string
  include: boolean
  mark: number | null
  elevation: number | null
  height: number | null
  elevation_source: string
  height_source: string
  alignment: string
  n_shapes: number
  preview?: { w: number; h: number; d: string }
}

export interface FloorMeta extends Candidate {
  node: string
  plan: string
  rooms: RoomMeta[]
  stats: {
    openings: Record<string, number>
    rooms: number
    stairs: number
    wall_area_m2: number
    footprint_m2: number
    [k: string]: unknown
  }
}

export type OpeningKind = 'door' | 'window' | 'vitrage' | 'passage'
type Ring = [number, number][]

/** 2D plan of one floor (plan coordinates, meters, Y up). */
export interface PlanData {
  bounds: [number, number, number, number]
  walls: Ring[][]
  partitions: Ring[][]
  columns: Ring[][]
  footprint: Ring[][]
  openings: {
    id: string
    kind: OpeningKind
    source: string
    width: number
    center: [number, number]
    poly: Ring[]
    leaves: [[number, number], [number, number]][]
  }[]
  rooms: { name: string; area: number; poly: Ring[]; label: [number, number] }[]
  stairs: Ring[][]
  lines: Ring[]
}

export type XY = [number, number]
export interface FloorEdits {
  add_walls: { a: XY; b: XY; thickness: number }[]
  erase_walls: { a: XY; b: XY; width: number }[]
  add_openings: { a: XY; b: XY; kind: OpeningKind }[]
  openings: { at: XY; kind: OpeningKind | 'wall' | 'none' }[]
  rooms: { at: XY; name: string }[]
}

export interface LayerInfo {
  role: Role | null
  count: number
  types: Record<string, number>
}

export interface Result {
  source: string
  units: string
  units_source: string
  converter: string
  floors: FloorMeta[]
  roof_node: string | null
  height_range: [number, number]
  candidates: Candidate[]
  layers: Record<string, LayerInfo>
  triangles: number
  warnings: string[]
  /** plausibility check: "suspect" = built, but most likely recognised wrongly */
  quality?: { status: 'ok' | 'suspect'; issues: string[] }
  /** editor corrections whose floor sheet was not found in this build (kept, not applied) */
  edits_unmatched?: number
  entrances?: Entrance[]
  pois?: Poi[]
  room_types?: RoomType[]
  /** plan coordinates of the glTF origin */
  center?: [number, number]
  elapsed_s: number
  exports?: Record<string, string>
  extent?: { x: [number, number]; z: [number, number] }
}

export interface Job {
  id: string
  filename: string
  status: 'queued' | 'running' | 'done' | 'error'
  stage: string
  progress: number
  message: string
  error?: string
  result?: Result
  model_url?: string
  build: number
  config?: Record<string, unknown>
  view?: ViewSettings
}

export interface Pin {
  id: string
  /** row version on the server (sent back with changes) */
  version?: number
  floor: string
  pos: V3
  text: string
  label?: string
  created?: number
}

/** Furniture / equipment placed on a floor (plan coordinates, meters). */
export interface PlacedItem {
  id: string
  /** row version on the server (sent back with changes) */
  version?: number
  floor: string
  /** catalog item id */
  item: string
  at: XY
  /** degrees, counter-clockwise; 0 = back towards +Y (plan up) */
  angle: number
  /** [w, d, h] override of the catalog size */
  size?: [number, number, number]
  note?: string
  /** mounting height override, m */
  elev?: number
  /** CCTV camera: horizontal view angle (deg) and range (m) overrides */
  fov?: number
  range?: number
}

/** Per-job viewer settings stored on the server (no rebuild needed). */
export interface ViewSettings {
  name?: string
  site?: { lat: number; lon: number; azimuth: number; scale: number; tiles?: string; attribution?: string }
  detail?: { file?: string; version?: number; size?: number; offset: V3; rotation: number; scale: number }
  comments?: Pin[]
  markers?: Pin[]
  furniture?: PlacedItem[]
  /** furniture whose floor was not found after a rebuild (kept by the server) */
  furniture_unplaced?: (PlacedItem & { _anchor?: { name?: string } | null })[]
}

export interface JobSummary { id: string; filename: string; name: string; status: Job['status']; floors: number; updated: number }

/** A failed request: `status` and the parsed JSON body (e.g. 409 conflicts). */
export class ApiError extends Error {
  status: number
  body: Record<string, unknown> | null
  constructor(msg: string, status: number, body: Record<string, unknown> | null) {
    super(msg)
    this.status = status
    this.body = body
  }
}

async function check<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    let body: Record<string, unknown> | null = null
    try {
      body = await r.json()
      const d = body?.detail
      if (d) msg = typeof d === 'string' ? d : JSON.stringify(d)
    } catch { /* not json */ }
    throw new ApiError(msg, r.status, body)
  }
  return (r.status === 204 ? null : r.json()) as Promise<T>
}

export async function uploadFile(file: File): Promise<Job> {
  const fd = new FormData()
  fd.append('file', file)
  return check(await fetch('/api/jobs', { method: 'POST', body: fd }))
}

export async function getJob(id: string): Promise<Job> {
  return check(await fetch(`/api/jobs/${id}`))
}

export async function rebuildJob(id: string, override: Record<string, unknown>): Promise<Job> {
  return check(await fetch(`/api/jobs/${id}/rebuild`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(override),
  }))
}

export async function getPlan(id: string, path: string, v: number): Promise<PlanData> {
  return check(await fetch(fileUrl(id, path, v)))
}

export const fileUrl = (id: string, path: string, v = 0) => `/api/jobs/${id}/files/${path}?v=${v}`

/** Source drawing with the editor corrections applied, downloaded as a file. */
export async function downloadDrawing(id: string, fmt: 'dxf' | 'dwg'): Promise<void> {
  const r = await fetch(`/api/jobs/${id}/drawing.${fmt}`)
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try { msg = (await r.json()).detail ?? msg } catch { /* not json */ }
    throw new Error(msg)
  }
  const cd = r.headers.get('content-disposition') ?? ''
  const m = /filename\*=utf-8''([^;]+)/i.exec(cd) ?? /filename="?([^";]+)"?/i.exec(cd)
  const name = m ? decodeURIComponent(m[1]) : `drawing.${fmt}`
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}

export async function listJobs(): Promise<JobSummary[]> {
  return check(await fetch('/api/jobs'))
}

export async function putView(id: string, v: Partial<ViewSettings> | Record<string, unknown>): Promise<ViewSettings> {
  return check(await fetch(`/api/jobs/${id}/view`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(v),
  }))
}

export async function uploadDetail(id: string, file: File): Promise<ViewSettings> {
  const fd = new FormData()
  fd.append('file', file)
  return check(await fetch(`/api/jobs/${id}/detail`, { method: 'POST', body: fd }))
}

export async function deleteDetail(id: string): Promise<ViewSettings> {
  return check(await fetch(`/api/jobs/${id}/detail`, { method: 'DELETE' }))
}

/** One change of a placed item or pin; updates and deletes carry the row version they were made against. */
export type RowOp = { op: 'create' | 'update' | 'delete'; id: string; version?: number } & Record<string, unknown>
export interface RowConflict { id: string; current: (PlacedItem & Pin) | null }
export interface BatchResult<T> { items: T[]; deleted: string[] }

/** Apply changes to furniture ('placements') or pins as one transaction: all or none.
 * Throws ApiError 409 with body.conflicts when rows were changed by someone else,
 * or when the model was rebuilt since `build`. */
export async function batchRows<T = PlacedItem>(id: string, kind: 'placements' | 'pins', build: number, ops: RowOp[]): Promise<BatchResult<T>> {
  return check(await fetch(`/api/projects/${id}/${kind}:batch`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ build, ops }),
  }))
}
