import type { CatalogItem, Category } from './furniture/catalog'

export type Role = 'walls' | 'columns' | 'windows' | 'doors' | 'rooms' | 'grid' | 'ignore' | 'insulation' | 'stairs'

export type V3 = [number, number, number]

export interface RoomMeta {
  /** room id kept across builds (see GET /api/drawings/{id}/rooms) */
  id?: number
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

export type LayerKind = 'furniture' | 'cctv' | string

/** A layer of a project (its objects may stand on any of the project's drawings). */
export interface Layer {
  id: string
  kind: LayerKind
  name: string
  visible: boolean
  locked: boolean
  sort: number
  props: Record<string, unknown>
  version: number
  /** objects in the layer (all drawings) */
  count?: number
}

export interface LayerKindInfo { kind: LayerKind; name: string; geoms: string[]; categories: string[] | null }

/** A drawing (one uploaded DWG/DXF) with the state of its latest build. */
export interface Job {
  id: string
  project_id: string
  name: string
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
  /** layers of the drawing's project */
  layers?: Layer[]
  /** the current user's role in the project */
  my_role?: 'viewer' | 'editor' | 'owner' | null
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

/** Furniture / equipment placed on a floor (plan coordinates, meters): a point object of a layer. */
export interface PlacedItem {
  id: string
  /** row version on the server (sent back with changes) */
  version?: number
  /** layer id (the server picks a default layer for new items when absent) */
  layer?: string
  /** id of the room it stands in (kept across builds), null outside rooms */
  room?: number | null
  geom?: 'point'
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

export interface JobSummary {
  id: string
  project_id: string
  filename: string
  name: string
  status: Job['status']
  progress: number
  floors: number
  build: number
  size: number
  updated: number
}

export interface Project {
  id: string
  name: string
  description: string
  /** the current user's role in the project */
  my_role: 'viewer' | 'editor' | 'owner' | null
  created: number
  updated: number
  drawings: JobSummary[]
}

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
    // the session expired or was ended elsewhere: back to the sign-in screen
    if (r.status === 401 && body?.login) location.reload()
    throw new ApiError(msg, r.status, body)
  }
  return (r.status === 204 ? null : r.json()) as Promise<T>
}

const jsonBody = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export async function listProjects(): Promise<Project[]> {
  return check(await fetch('/api/projects'))
}

export async function getProject(id: string): Promise<Project> {
  return check(await fetch(`/api/projects/${id}`))
}

export async function createProject(name: string, description = ''): Promise<Project> {
  return check(await fetch('/api/projects', jsonBody('POST', { name, description })))
}

export async function updateProject(id: string, patch: { name?: string; description?: string }): Promise<Project> {
  return check(await fetch(`/api/projects/${id}`, jsonBody('PATCH', patch)))
}

export async function deleteProject(id: string): Promise<void> {
  return check(await fetch(`/api/projects/${id}`, { method: 'DELETE' }))
}

/** Upload a DWG/DXF into a project (a new project named after the file when none is given). */
export async function uploadFile(file: File, projectId?: string, name?: string): Promise<Job> {
  const pid = projectId ?? (await createProject(file.name.replace(/\.[^.]+$/, ''))).id
  const fd = new FormData()
  fd.append('file', file)
  if (name) fd.append('name', name)
  return check(await fetch(`/api/projects/${pid}/drawings`, { method: 'POST', body: fd }))
}

/** A new revision of a drawing's DWG: floors, corrections and furniture follow it. */
export async function uploadRevision(id: string, file: File): Promise<Job> {
  const fd = new FormData()
  fd.append('file', file)
  return check(await fetch(`/api/drawings/${id}/revision`, { method: 'POST', body: fd }))
}

export async function deleteDrawing(id: string): Promise<void> {
  return check(await fetch(`/api/drawings/${id}`, { method: 'DELETE' }))
}

export async function getJob(id: string): Promise<Job> {
  return check(await fetch(`/api/drawings/${id}`))
}

export async function rebuildJob(id: string, override: Record<string, unknown>): Promise<Job> {
  return check(await fetch(`/api/drawings/${id}/rebuild`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(override),
  }))
}

export async function getPlan(id: string, path: string, v: number): Promise<PlanData> {
  return check(await fetch(fileUrl(id, path, v)))
}

export const fileUrl = (id: string, path: string, v = 0) => `/api/drawings/${id}/files/${path}?v=${v}`

/** Source drawing with the editor corrections applied, downloaded as a file. */
export async function downloadDrawing(id: string, fmt: 'dxf' | 'dwg'): Promise<void> {
  const r = await fetch(`/api/drawings/${id}/drawing.${fmt}`)
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

/** Drawings of one project (or all), newest first. */
export async function listLayers(projectId: string): Promise<Layer[]> {
  return check(await fetch(`/api/projects/${projectId}/layers`))
}

export async function layerKinds(): Promise<LayerKindInfo[]> {
  return check(await fetch('/api/layer-kinds'))
}

export async function createLayer(projectId: string, kind: LayerKind, name?: string): Promise<Layer> {
  return check(await fetch(`/api/projects/${projectId}/layers`, jsonBody('POST', { kind, name })))
}

/** name / visible / locked / sort; `version` makes it fail (409) when someone changed the layer meanwhile. */
export async function updateLayer(projectId: string, id: string, patch: Partial<Pick<Layer, 'name' | 'visible' | 'locked' | 'sort' | 'props' | 'version'>>): Promise<Layer> {
  return check(await fetch(`/api/projects/${projectId}/layers/${id}`, jsonBody('PATCH', patch)))
}

export async function deleteLayer(projectId: string, id: string): Promise<void> {
  return check(await fetch(`/api/projects/${projectId}/layers/${id}`, { method: 'DELETE' }))
}

export async function listJobs(projectId?: string): Promise<JobSummary[]> {
  return check(await fetch(projectId ? `/api/drawings?project=${projectId}` : '/api/drawings'))
}

export async function putView(id: string, v: Partial<ViewSettings> | Record<string, unknown>): Promise<ViewSettings> {
  return check(await fetch(`/api/drawings/${id}/view`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(v),
  }))
}

export async function uploadDetail(id: string, file: File): Promise<ViewSettings> {
  const fd = new FormData()
  fd.append('file', file)
  return check(await fetch(`/api/drawings/${id}/detail`, { method: 'POST', body: fd }))
}

export async function deleteDetail(id: string): Promise<ViewSettings> {
  return check(await fetch(`/api/drawings/${id}/detail`, { method: 'DELETE' }))
}

/** One change of a placed item or pin; updates and deletes carry the row version they were made against. */
export type RowOp = { op: 'create' | 'update' | 'delete'; id: string; version?: number } & Record<string, unknown>
export interface RowConflict { id: string; current: (PlacedItem & Pin) | null }
export interface BatchResult<T> { items: T[]; deleted: string[] }

/** Apply changes to layer objects (furniture, cameras, lines...) or pins as one transaction: all or none.
 * Throws ApiError 409 with body.conflicts when rows were changed by someone else,
 * or when the model was rebuilt since `build`. */
export async function batchRows<T = PlacedItem>(id: string, kind: 'objects' | 'pins', build: number, ops: RowOp[]): Promise<BatchResult<T>> {
  return check(await fetch(`/api/drawings/${id}/${kind}:batch`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ build, ops }),
  }))
}

// ---- catalog editing (catalog_admin) and reports

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export async function createCatalogItem(item: Partial<CatalogItem>): Promise<CatalogItem> {
  return check(await fetch('/api/catalog/items', json('POST', item)))
}

/** Fields given replace the stored ones; null clears an optional field. */
export async function updateCatalogItem(id: string, patch: Record<string, unknown>): Promise<CatalogItem> {
  return check(await fetch(`/api/catalog/items/${encodeURIComponent(id)}`, json('PATCH', patch)))
}

export async function uploadCatalogModel(id: string, file: File): Promise<CatalogItem> {
  const fd = new FormData()
  fd.append('file', file)
  return check(await fetch(`/api/catalog/items/${encodeURIComponent(id)}/model`, { method: 'POST', body: fd }))
}

export async function saveCategory(c: Category, create: boolean): Promise<Category> {
  return check(await fetch(create ? '/api/catalog/categories' : `/api/catalog/categories/${encodeURIComponent(c.id)}`,
    json(create ? 'POST' : 'PATCH', c)))
}

export interface ReportRow {
  item: string
  name: string
  category: string
  article: string
  supplier: string
  price: number | null
  currency: string | null
  qty: number
  sum: number | null
  /** count per floor name (one project) or per project id (all projects) */
  by: Record<string, number>
}

export interface EquipmentReport {
  project?: { id: string; name: string }
  projects?: { id: string; name: string }[]
  columns: string[]
  rows: ReportRow[]
  totals: Record<string, number>
  qty: number
  unpriced: number
  generated: string
}

export async function equipmentReport(project: string | null, layer?: string | null): Promise<EquipmentReport> {
  const q = new URLSearchParams()
  if (project) q.set('project', project)
  if (layer) q.set('layer', layer)
  return check(await fetch(`/api/reports/equipment?${q}`))
}

export interface RoomReport {
  project: { id: string; name: string }
  layer?: { id: string; name: string }
  many_drawings: boolean
  rooms: { drawing: string; floor: string; room: string; room_id: number | null; area: number | null; qty: number;
    totals: Record<string, number>; items: Omit<ReportRow, 'by'>[] }[]
  qty: number
  totals: Record<string, number>
  generated: string
}

export async function roomReport(project: string, layer?: string | null): Promise<RoomReport> {
  const q = new URLSearchParams({ project, by: 'room' })
  if (layer) q.set('layer', layer)
  return check(await fetch(`/api/reports/equipment?${q}`))
}

export const equipmentReportXlsx = (project: string | null, by: 'floor' | 'room' = 'floor', layer?: string | null) => {
  const q = new URLSearchParams({ format: 'xlsx' })
  if (project) q.set('project', project)
  if (by === 'room') q.set('by', 'room')
  if (layer) q.set('layer', layer)
  return `/api/reports/equipment?${q}`
}
