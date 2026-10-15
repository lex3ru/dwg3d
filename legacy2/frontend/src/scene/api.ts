import type { CatalogItem, Category } from './furniture/catalog'
import { buildFileUrl, fetch } from './compat'

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
  /** a newer build waits for the administrator's review: the model shown is the published one */
  draft?: { revision: string; n: number; retired: number; merged: number }
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
  /** the make and model named: «Dell P2723DE» (an object of the records) */
  product?: string
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
    throw new ApiError(msg, r.status, body)
  }
  return (r.status === 204 ? null : r.json()) as Promise<T>
}

const jsonBody = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

const get = async <T>(url: string): Promise<T> => check(await fetch(url))

/** A request without a body (DELETE, POST of an action), or with a JSON one. */
const send = async <T>(method: string, url: string, body?: unknown): Promise<T> =>
  check(await fetch(url, body === undefined ? { method } : jsonBody(method, body)))

/** POST a file (multipart `file`, plus string fields). */
const upload = async <T>(url: string, file: File, fields: Record<string, string | undefined> = {}): Promise<T> => {
  const fd = new FormData()
  fd.append('file', file)
  for (const [k, v] of Object.entries(fields)) if (v) fd.append(k, v)
  return check(await fetch(url, { method: 'POST', body: fd }))
}

export async function listProjects(): Promise<Project[]> {
  return get('/api/projects')
}

export async function getProject(id: string): Promise<Project> {
  return get(`/api/projects/${id}`)
}

export async function createProject(name: string, description = ''): Promise<Project> {
  return send('POST', '/api/projects', { name, description })
}

export async function updateProject(id: string, patch: { name?: string; description?: string }): Promise<Project> {
  return send('PATCH', `/api/projects/${id}`, patch)
}

export async function deleteProject(id: string): Promise<void> {
  return send('DELETE', `/api/projects/${id}`)
}

/** Upload a DWG/DXF into a project (a new project named after the file when none is given). */
export async function uploadFile(file: File, projectId?: string, name?: string): Promise<Job> {
  const pid = projectId ?? (await createProject(file.name.replace(/\.[^.]+$/, ''))).id
  return upload(`/api/projects/${pid}/drawings`, file, { name })
}

/** A new revision of a drawing's DWG: floors, corrections and furniture follow it. */
export async function uploadRevision(id: string, file: File): Promise<Job> {
  return upload(`/api/drawings/${id}/revision`, file)
}

export async function deleteDrawing(id: string): Promise<void> {
  return send('DELETE', `/api/drawings/${id}`)
}

export async function getJob(id: string): Promise<Job> {
  return get(`/api/drawings/${id}`)
}

export async function rebuildJob(id: string, override: Record<string, unknown>): Promise<Job> {
  return send('POST', `/api/drawings/${id}/rebuild`, override)
}

export async function getPlan(id: string, path: string, v: number): Promise<PlanData> {
  return get(`/api/drawings/${id}/files/${path}?v=${v}`)
}

// the loaders of the viewer fetch files by address: the real one, in the import service
export const fileUrl = (id: string, path: string, _v = 0) => buildFileUrl(id, path)

/** Source drawing with the editor corrections applied and, with `objects`, the objects of accounting
 * on its floors drawn in as blocks with attributes, downloaded as a file. */
export async function downloadDrawing(id: string, fmt: 'dxf' | 'dwg', objects = false): Promise<void> {
  const r = await fetch(`/api/drawings/${id}/drawing.${fmt}${objects ? '?objects=1' : ''}`)
  if (!r.ok) await check(r)
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

export async function listLayers(projectId: string): Promise<Layer[]> {
  return get(`/api/projects/${projectId}/layers`)
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
  return get('/api/layer-kinds')
}

export async function createLayer(projectId: string, kind: LayerKind, name?: string): Promise<Layer> {
  return send('POST', `/api/projects/${projectId}/layers`, { kind, name })
}

/** name / visible / locked / sort; `version` makes it fail (409) when someone changed the layer meanwhile. */
export async function updateLayer(projectId: string, id: string, patch: Partial<Pick<Layer, 'name' | 'visible' | 'locked' | 'sort' | 'props' | 'version'>>): Promise<Layer> {
  return send('PATCH', `/api/projects/${projectId}/layers/${id}`, patch)
}

/** A copy of a layer with its objects: a variant (props.variant_group ties the variants of a layer). */
export async function copyLayer(projectId: string, id: string, name?: string): Promise<Layer> {
  return send('POST', `/api/projects/${projectId}/layers/${id}/copy`, { name })
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
  return get(`/api/projects/${projectId}/layers/compare?a=${a}&b=${b}`)
}

export interface ProjectChecks {
  /** rooms short of fire detectors */
  fire: { drawing_id: string; drawing: string; floor: string; room_id: number; room: string; area: number; has: number; need: number }[]
}

export async function projectChecks(projectId: string): Promise<ProjectChecks> {
  return get(`/api/projects/${projectId}/checks`)
}

export async function deleteLayer(projectId: string, id: string): Promise<void> {
  return send('DELETE', `/api/projects/${projectId}/layers/${id}`)
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
  return get(`/api/projects/${projectId}/members`)
}

/** `who`: a login or an e-mail (an e-mail of someone who has not signed in yet is an invitation). */
export async function addMember(projectId: string, who: string, role: ProjectRole): Promise<Member> {
  return send('POST', `/api/projects/${projectId}/members`, { who, role })
}

export async function setMemberRole(projectId: string, id: number, role: ProjectRole): Promise<Member> {
  return send('PATCH', `/api/projects/${projectId}/members/${id}`, { role })
}

export async function removeMember(projectId: string, id: number): Promise<void> {
  return send('DELETE', `/api/projects/${projectId}/members/${id}`)
}

export async function searchUsers(q: string): Promise<UserInfo[]> {
  return get(`/api/users?q=${encodeURIComponent(q)}`)
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
  return get(`/api/projects/${projectId}/shares`)
}

export async function createShare(projectId: string, v: { name?: string; days?: number | null; drawings?: string[] | null; layers?: string[] | null }): Promise<ShareLink> {
  return send('POST', `/api/projects/${projectId}/shares`, v)
}

export async function revokeShare(projectId: string, id: string): Promise<ShareLink> {
  return send('DELETE', `/api/projects/${projectId}/shares/${id}`)
}

export async function renameDrawing(id: string, name: string): Promise<ViewSettings> {
  return putView(id, { name })
}

/** Drawings of one project (or all), newest first. */
export async function listJobs(projectId?: string): Promise<JobSummary[]> {
  return get(projectId ? `/api/drawings?project=${projectId}` : '/api/drawings')
}

export async function putView(id: string, v: Partial<ViewSettings> | Record<string, unknown>): Promise<ViewSettings> {
  return send('PUT', `/api/drawings/${id}/view`, v)
}

export async function uploadDetail(id: string, file: File): Promise<ViewSettings> {
  return upload(`/api/drawings/${id}/detail`, file)
}

export async function deleteDetail(id: string): Promise<ViewSettings> {
  return send('DELETE', `/api/drawings/${id}/detail`)
}

/** One change of a placed item or pin; updates and deletes carry the row version they were made against. */
export type RowOp = { op: 'create' | 'update' | 'delete'; id: string; version?: number } & Record<string, unknown>
export interface RowConflict { id: string; current: (PlacedItem & Pin) | null }
export interface BatchResult<T> { items: T[]; deleted: string[] }

/** The layer objects of a drawing as the server has them now: placed items and shapes. */
export async function listObjects(id: string): Promise<{ build: number; items: (PlacedItem | ShapeObject)[] }> {
  return get(`/api/drawings/${id}/objects`)
}

export async function listPins(id: string): Promise<{ build: number; markers: Pin[]; comments: Pin[] }> {
  return get(`/api/drawings/${id}/pins`)
}

/** Changes of layer objects proposed by the copilot, waiting for a person (or decided). */
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
  /** who proposed: «Копилот» */
  agent: string
  user: { id: number; login: string; name: string } | null
  counts: ProposalCounts
  created: number | null
  decided: number | null
  decided_by: { id: number; login: string; name: string } | null
}

/** Objects created / updated / deleted, and operations on layers. */
export interface ProposalCounts { create: number; update: number; delete: number; layers?: number }

/** What an operation on layers of a proposal does (a new layer, a variant, renaming or showing, deleting). */
export interface ProposalLayerOp {
  op: 'create_layer' | 'copy_layer' | 'update_layer' | 'delete_layer'
  id: string
  name: string
  kind?: string
  /** copy_layer: the layer copied */
  of?: string
  /** copy_layer / delete_layer: its objects */
  objects?: number
  changes?: { name?: string; visible?: boolean }
}

/** A proposal with what it would do now (rows as the server would have them). */
export interface ProposalFull extends Proposal {
  preview: {
    layers?: ProposalLayerOp[]
    created: (PlacedItem | ShapeObject)[]
    updated: { before: PlacedItem | ShapeObject | null; after: PlacedItem | ShapeObject }[]
    deleted: (PlacedItem | ShapeObject)[]
  }
}

export async function listProposals(projectId: string, q: { status?: string; drawing?: string } = {}): Promise<Proposal[]> {
  const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][])
  return get(`/api/projects/${projectId}/proposals?${qs}`)
}

export async function getProposal(id: string): Promise<ProposalFull> {
  return get(`/api/proposals/${id}`)
}

export async function applyProposal(id: string): Promise<{ proposal: Proposal }> {
  return send('POST', `/api/proposals/${id}/apply`)
}

export async function rejectProposal(id: string, reason: string): Promise<Proposal> {
  return send('POST', `/api/proposals/${id}/reject`, { reason })
}

/** One change of a committed transaction (GET /api/projects/{id}/events). */
export interface ProjectChange { drawing: string | null; entity: string; id: string; action: string }

/** Changes in a project made by someone (a person in another window, or the copilot);
 * `entity: 'resync'` — changes were lost: read everything again. */
export interface ProjectEvent {
  project?: string
  user_id?: number | null
  actor?: string | null
  /** «Копилот» when the copilot made the change */
  agent?: string | null
  changes?: ProjectChange[]
  /** changes left out of a big transaction */
  more?: number
  /** 'view': the copilot's command to this user's windows (`command`) */
  entity?: 'resync' | 'view'
  command?: ViewCommand
}

/** What the copilot asks the user's windows to show (show_in_viewer); changes no data. */
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

// ---- the built-in copilot (an external OpenAI-compatible model, set up by an admin)
export interface CopilotSettings {
  enabled: boolean
  /** OpenAI-compatible endpoint, up to /chat/completions (e.g. http://localhost:11434/v1) */
  base_url: string
  model: string
  daily_limit: number
  max_steps: number
  temperature: number | null
  api_key_set: boolean
  /** the key's last characters */
  api_key_hint: string
}

export async function getCopilotSettings(): Promise<CopilotSettings> {
  return get('/api/copilot/settings')
}

/** api_key: a new key; '' removes it; left out — kept. */
export async function saveCopilotSettings(v: Partial<Omit<CopilotSettings, 'api_key_set' | 'api_key_hint'>> & { api_key?: string }): Promise<CopilotSettings> {
  return send('PUT', '/api/copilot/settings', v)
}

export async function checkCopilot(v: { base_url?: string; api_key?: string; model?: string }):
  Promise<{ ok: boolean; error?: string; models?: string[]; answer?: string; prompt_tokens?: number }> {
  return send('POST', '/api/copilot/settings/check', v)
}

export interface CopilotStatus { enabled: boolean; model: string | null; daily_limit: number; used_today: number }

export async function copilotStatus(): Promise<CopilotStatus> {
  return get('/api/copilot/status')
}

export interface CopilotProposal { id: string; summary: string; status: string; counts?: ProposalCounts; drawing_id?: string }

/** One line of a copilot answer as it comes, or of a kept conversation. */
export type CopilotEvent =
  | { type: 'chat'; id: string }
  | { type: 'text'; text: string }
  /** a reasoning model at work: characters of reasoning so far (not shown) */
  | { type: 'thinking'; chars: number }
  | { type: 'tool'; name: string; error?: string }
  | { type: 'proposal'; proposal: CopilotProposal }
  | { type: 'error'; message: string }
  | { type: 'done' }

export type CopilotItem =
  | { type: 'user'; text: string }
  | { type: 'assistant'; text: string }
  | { type: 'tool'; name: string; error?: string }
  | { type: 'proposal'; proposal: CopilotProposal }
  | { type: 'error'; message: string }

/** Ask the copilot; `on` gets the answer's events as they come (NDJSON). */
export async function askCopilot(projectId: string, body: { message: string; chat?: string | null; ui?: Omit<UIContext, 'client'> & { client?: string } },
  on: (ev: CopilotEvent) => void, signal?: AbortSignal): Promise<void> {
  const r = await fetch(`/api/projects/${projectId}/copilot`, { ...jsonBody('POST', body), signal })
  if (!r.ok || !r.body) { await check(r); return }
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (value) buf += dec.decode(value, { stream: !done })
    let nl
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (line) on(JSON.parse(line))
    }
    if (done) break
  }
}

export async function listCopilotChats(projectId: string): Promise<{ id: string; title: string; updated: number }[]> {
  return get(`/api/projects/${projectId}/copilot/chats`)
}

export async function getCopilotChat(projectId: string, id: string): Promise<{ id: string; title: string; items: CopilotItem[] }> {
  return get(`/api/projects/${projectId}/copilot/chats/${id}`)
}

export async function deleteCopilotChat(projectId: string, id: string): Promise<void> {
  return send('DELETE', `/api/projects/${projectId}/copilot/chats/${id}`)
}

/** What this window shows, for the user's copilot (or `closed`). */
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
  return send('POST', `/api/drawings/${id}/${kind}:batch`, { build, ops })
}

// ---- catalog editing (catalog_admin) and reports

export async function createCatalogItem(item: Partial<CatalogItem>): Promise<CatalogItem> {
  return send('POST', '/api/catalog/items', item)
}

/** Fields given replace the stored ones; null clears an optional field. */
export async function updateCatalogItem(id: string, patch: Record<string, unknown>): Promise<CatalogItem> {
  return send('PATCH', `/api/catalog/items/${encodeURIComponent(id)}`, patch)
}

export async function uploadCatalogModel(id: string, file: File): Promise<CatalogItem> {
  return upload(`/api/catalog/items/${encodeURIComponent(id)}/model`, file)
}

export async function saveCategory(c: Category, create: boolean): Promise<Category> {
  return create ? send('POST', '/api/catalog/categories', c)
    : send('PATCH', `/api/catalog/categories/${encodeURIComponent(c.id)}`, c)
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
  return get(`/api/reports/equipment?${q}`)
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
  return get(`/api/reports/equipment?${q}`)
}

export const equipmentReportXlsx = (project: string | null, by: 'floor' | 'room' = 'floor', layer?: string | null) => {
  const q = new URLSearchParams({ format: 'xlsx' })
  if (project) q.set('project', project)
  if (by === 'room') q.set('by', 'room')
  if (layer) q.set('layer', layer)
  return `/api/reports/equipment?${q}`
}
