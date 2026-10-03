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
  /** lines, zones, routes of functional layers */
  shapes?: ShapeObject[]
}

/** An object of a functional layer: a route (stops and the computed way in props) or a polygon (a zone). */
export interface ShapeObject {
  id: string
  version?: number
  layer?: string
  geom: 'route' | 'polygon' | 'polyline'
  floor: string
  room?: number | null
  at: XY
  angle?: number
  points?: XY[]
  props?: Record<string, unknown>
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

/** Source drawing with the editor corrections applied and the objects of the
 * shown project layers drawn in (or none), downloaded as a file. */
export async function downloadDrawing(id: string, fmt: 'dxf' | 'dwg', layers: string[] | 'none' = 'none'): Promise<void> {
  const q = layers === 'none' ? 'none' : layers.join(',') || 'none'
  const r = await fetch(`/api/drawings/${id}/drawing.${fmt}?layers=${encodeURIComponent(q)}`)
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

export interface LayerKinds {
  kinds: LayerKindInfo[]
  /** functional layers: flows of routes, which must not meet, zone kinds and flows forbidden in them */
  flows: Record<string, { name: string; color: string }>
  flow_conflicts: [string, string][]
  zone_kinds: Record<string, { name: string; color: string }>
  zone_forbidden: Record<string, string[]>
  cables: Record<string, { name: string; color: string }>
}

export async function layerKinds(): Promise<LayerKinds> {
  return check(await fetch('/api/layer-kinds'))
}

export async function createLayer(projectId: string, kind: LayerKind, name?: string): Promise<Layer> {
  return check(await fetch(`/api/projects/${projectId}/layers`, jsonBody('POST', { kind, name })))
}

/** name / visible / locked / sort; `version` makes it fail (409) when someone changed the layer meanwhile. */
export async function updateLayer(projectId: string, id: string, patch: Partial<Pick<Layer, 'name' | 'visible' | 'locked' | 'sort' | 'props' | 'version'>>): Promise<Layer> {
  return check(await fetch(`/api/projects/${projectId}/layers/${id}`, jsonBody('PATCH', patch)))
}

/** A copy of a layer with its objects: a variant (props.variant_group ties the variants of a layer). */
export async function copyLayer(projectId: string, id: string, name?: string): Promise<Layer> {
  return check(await fetch(`/api/projects/${projectId}/layers/${id}/copy`, jsonBody('POST', { name })))
}

export interface CompareObject {
  key: string
  change: 'added' | 'removed' | 'moved' | 'changed'
  what: string[]
  id_a: string | null
  id_b: string | null
  item: string | null
  name: string
  geom: string
  drawing_id: string
  drawing: string
  floor: string
  floor_name: string
  room: string
  at: XY
  from?: { drawing_id: string; floor: string; floor_name: string; room: string; at: XY }
}

export interface LayerComparison {
  a: Layer
  b: Layer
  counts: { added: number; removed: number; moved: number; changed: number; same: number }
  objects: CompareObject[]
  items: { item: string; name: string; category: string; price: number | null; currency: string | null;
    qty_a: number; qty_b: number; delta: number; sum_a?: number; sum_b?: number }[]
  totals: Record<string, { a: number; b: number; delta: number }>
}

export async function compareLayers(projectId: string, a: string, b: string): Promise<LayerComparison> {
  return check(await fetch(`/api/projects/${projectId}/layers/compare?a=${a}&b=${b}`))
}

export interface ProjectChecks {
  /** rooms short of fire detectors */
  fire: { drawing_id: string; drawing: string; floor: string; room_id: number; room: string; area: number; has: number; need: number }[]
}

export async function projectChecks(projectId: string): Promise<ProjectChecks> {
  return check(await fetch(`/api/projects/${projectId}/checks`))
}

export async function deleteLayer(projectId: string, id: string): Promise<void> {
  return check(await fetch(`/api/projects/${projectId}/layers/${id}`, { method: 'DELETE' }))
}

export type ProjectRole = 'viewer' | 'editor' | 'owner'

export interface Member {
  id: number
  role: ProjectRole
  role_name: string
  /** an invitation by e-mail waiting for the first sign-in */
  pending: boolean
  email: string | null
  user: { id: number; login: string; name: string } | null
}

export interface UserInfo { id: number; login: string; name: string; email: string | null; role: string }

export async function listMembers(projectId: string): Promise<Member[]> {
  return check(await fetch(`/api/projects/${projectId}/members`))
}

/** `who`: a login or an e-mail (an e-mail of someone who has not signed in yet is an invitation). */
export async function addMember(projectId: string, who: string, role: ProjectRole): Promise<Member> {
  return check(await fetch(`/api/projects/${projectId}/members`, jsonBody('POST', { who, role })))
}

export async function setMemberRole(projectId: string, id: number, role: ProjectRole): Promise<Member> {
  return check(await fetch(`/api/projects/${projectId}/members/${id}`, jsonBody('PATCH', { role })))
}

export async function removeMember(projectId: string, id: number): Promise<void> {
  return check(await fetch(`/api/projects/${projectId}/members/${id}`, { method: 'DELETE' }))
}

export async function searchUsers(q: string): Promise<UserInfo[]> {
  return check(await fetch(`/api/users?q=${encodeURIComponent(q)}`))
}

export interface ShareLink {
  id: string
  name: string
  /** drawing / layer ids the link opens (null: all) */
  drawings: string[] | null
  layers: string[] | null
  expires: number | null
  revoked: boolean
  active: boolean
  created: number | null
  last_used: number | null
  /** only in the answer to its creation */
  token?: string
  url?: string
}

export async function listShares(projectId: string): Promise<ShareLink[]> {
  return check(await fetch(`/api/projects/${projectId}/shares`))
}

export async function createShare(projectId: string, v: { name?: string; days?: number | null; drawings?: string[] | null; layers?: string[] | null }): Promise<ShareLink> {
  return check(await fetch(`/api/projects/${projectId}/shares`, jsonBody('POST', v)))
}

export async function revokeShare(projectId: string, id: string): Promise<ShareLink> {
  return check(await fetch(`/api/projects/${projectId}/shares/${id}`, { method: 'DELETE' }))
}

export type AgentMode = 'read' | 'propose' | 'write'

export interface AgentToken {
  id: string
  name: string
  mode: AgentMode
  mode_name: string
  /** the user the agent acts for */
  user: { id: number; login: string; name: string } | null
  mine: boolean
  expires: number
  revoked: boolean
  active: boolean
  created: number | null
  last_used: number | null
  /** only in the answer to its creation */
  token?: string
}

export async function listAgentTokens(projectId: string): Promise<AgentToken[]> {
  return check(await fetch(`/api/projects/${projectId}/agent-tokens`))
}

export async function createAgentToken(projectId: string, v: { name?: string; mode: AgentMode; days: number }): Promise<AgentToken> {
  return check(await fetch(`/api/projects/${projectId}/agent-tokens`, jsonBody('POST', v)))
}

export async function revokeAgentToken(projectId: string, id: string): Promise<AgentToken> {
  return check(await fetch(`/api/projects/${projectId}/agent-tokens/${id}`, { method: 'DELETE' }))
}

export async function renameDrawing(id: string, name: string): Promise<ViewSettings> {
  return putView(id, { name })
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

/** The layer objects of a drawing as the server has them now: placed items and shapes (`items`), and
 * catalog items whose floor is gone (`unplaced`). */
export async function listObjects(id: string): Promise<{ build: number; items: (PlacedItem | ShapeObject)[]; unplaced: PlacedItem[] }> {
  return check(await fetch(`/api/drawings/${id}/objects`))
}

export async function listPins(id: string): Promise<{ build: number; markers: Pin[]; comments: Pin[] }> {
  return check(await fetch(`/api/drawings/${id}/pins`))
}

/** Changes of layer objects proposed by an AI agent, waiting for a person (or decided). */
export interface Proposal {
  id: string
  project_id: string
  drawing_id: string
  drawing?: string
  summary: string
  status: 'open' | 'applied' | 'rejected' | 'stale'
  status_name: string
  /** why it was rejected, or why it no longer applies */
  reason: string | null
  /** the name of the agent's token */
  agent: string
  user: { id: number; login: string; name: string } | null
  counts: { create: number; update: number; delete: number }
  created: number | null
  decided: number | null
  decided_by: { id: number; login: string; name: string } | null
}

/** A proposal with what it would do now (rows as the server would have them). */
export interface ProposalFull extends Proposal {
  preview: {
    created: (PlacedItem | ShapeObject)[]
    updated: { before: PlacedItem | ShapeObject | null; after: PlacedItem | ShapeObject }[]
    deleted: (PlacedItem | ShapeObject)[]
  }
}

export async function listProposals(projectId: string, q: { status?: string; drawing?: string } = {}): Promise<Proposal[]> {
  const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][])
  return check(await fetch(`/api/projects/${projectId}/proposals?${qs}`))
}

export async function getProposal(id: string): Promise<ProposalFull> {
  return check(await fetch(`/api/proposals/${id}`))
}

export async function applyProposal(id: string): Promise<{ proposal: Proposal }> {
  return check(await fetch(`/api/proposals/${id}/apply`, { method: 'POST' }))
}

export async function rejectProposal(id: string, reason: string): Promise<Proposal> {
  return check(await fetch(`/api/proposals/${id}/reject`, jsonBody('POST', { reason })))
}

/** One change of a committed transaction (GET /api/projects/{id}/events). */
export interface ProjectChange { drawing: string | null; entity: string; id: string; action: string }

/** Changes in a project made by someone (a person in another window, or an agent with a token);
 * `entity: 'resync'` — changes were lost: read everything again. */
export interface ProjectEvent {
  project?: string
  user_id?: number | null
  actor?: string | null
  /** the name of the agent's token, when an agent made the change */
  agent?: string | null
  changes?: ProjectChange[]
  /** changes left out of a big transaction */
  more?: number
  /** 'view': an agent's command to this user's windows (`command`) */
  entity?: 'resync' | 'view'
  command?: ViewCommand
}

/** What an agent asks the user's windows to show (MCP show_in_viewer); changes no data. */
export interface ViewCommand {
  drawing?: string
  floor?: string | null
  /** plan point to fly to */
  at?: XY
  room?: number
  /** objects to outline */
  highlight?: string[]
  view?: '2d' | '3d'
  label?: string
}

/** What this window shows, for the user's agents (or `closed`). */
export interface UIContext {
  client: string
  drawing?: string | null
  floor?: string | null
  view?: '2d' | '3d'
  selected?: string[]
  room?: number | null
  proposal?: string | null
  tool?: string
  closed?: boolean
}

export async function reportUIContext(projectId: string, ctx: UIContext): Promise<void> {
  await fetch(`/api/projects/${projectId}/ui-context`, jsonBody('POST', ctx))
}

/** The window is going away: tell it even while the page unloads. */
export function closeUIContext(projectId: string, client: string) {
  navigator.sendBeacon?.(`/api/projects/${projectId}/ui-context`,
    new Blob([JSON.stringify({ client, closed: true })], { type: 'application/json' }))
}

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
