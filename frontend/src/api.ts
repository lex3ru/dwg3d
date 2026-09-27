export type Role = 'walls' | 'columns' | 'windows' | 'doors' | 'rooms' | 'grid' | 'ignore' | 'insulation' | 'stairs'

export interface RoomMeta {
  node: string
  name: string
  area: number
  label_pos: [number, number, number]
}

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
}

async function check<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const j = await r.json()
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* not json */ }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
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
