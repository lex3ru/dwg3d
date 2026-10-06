// Requests to the gateway. The session is a cookie; a 401 means it is gone.

export type User = { sub: string; login: string; name: string; email: string | null; roles: string[]; is_admin: boolean }
export type Role = 'viewer' | 'responsible' | 'admin'
export type ScopeKind = 'building' | 'floor' | 'room' | 'asset'
export type Grant = {
  id: string; person_id: string; role: Role; scope: { kind: ScopeKind; id: string }; building_id: string; origin: string
}
export type Person = {
  id: string; full_name: string; position: string; department: string; email: string | null; phone: string | null
  linked: boolean; status: 'active' | 'left'; version: number
}
export type Me = {
  user: User
  /** the user's record in the directory of people; null — the account is not there */
  person: Person | null
  reason: 'unknown' | 'ambiguous' | 'left' | null
  scopes: { admin: boolean; grants: Grant[]; buildings: string[] } | null
  partial: string[]
}
/** Whether the user administers the building (or the whole system). */
export const manages = (me: Me, building: string) => me.user.is_admin ||
  !!me.scopes?.grants.some(g => g.role === 'admin' && g.scope.kind === 'building' && g.scope.id === building)
export type ServiceStatus = { name: string; ok: boolean; db: boolean | null; nats: boolean | null; ms: number | null }
export type SystemStatus = { services: ServiceStatus[]; viewers: number }
export type Note = { id: string; text: string; created_at: string; echoed_at: string | null; echoes: number }

/** A failure as services report it (application/problem+json). */
export class ApiError extends Error {
  status: number
  code: string
  /** rows at fault, when a file was refused */
  rows: string[] = []
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** Sign-in page of Keycloak, returning to where the user is now. */
export function signIn() {
  const here = location.pathname + location.search + location.hash
  location.assign(`/auth/login?next=${encodeURIComponent(here)}`)
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {}
  const response = await fetch(path, {
    ...rest,
    headers: { ...(json === undefined ? {} : { 'Content-Type': 'application/json' }), ...rest.headers },
    body: json === undefined ? rest.body : JSON.stringify(json),
  })
  if (response.ok) return (response.status === 204 ? undefined : await response.json()) as T
  let problem: { code?: string; detail?: string; title?: string } = {}
  try { problem = await response.json() } catch { /* not JSON: a proxy's own error page */ }
  throw new ApiError(response.status, problem.code ?? 'error', problem.detail ?? problem.title ?? `Ошибка ${response.status}`)
}

export const getMe = () => api<Me>('/api/me')
export const getStatus = () => api<SystemStatus>('/api/system/status')
export const createNote = (text: string) => api<Note>('/api/ping/v1/notes', { method: 'POST', json: { text } })

export async function signOut() {
  const { url } = await api<{ url: string }>('/auth/logout', { method: 'POST' })
  location.assign(url)
}

// ---- buildings and their drawings (stage 1: for the system administrator)

export type Building = {
  id: string; name: string; address: string; version: number
  floors?: number; rooms?: number; drawings?: number
}
export type Build = {
  id: string; n: number; status: 'queued' | 'running' | 'done' | 'error'; stage: string; progress: number
  message: string; error: string | null
}
export type Drawing = {
  id: string; building_id: string; name: string; filename: string | null; size: number | null; file_n: number | null
  build: Build | null; current_build_id: string | null; updated_at: string; unchanged?: boolean
}
/** A drawing as the building has taken it in: the build that is shown. */
export type Placement = { dx: number; dy: number; dz: number; rotation: number }
export type PlacedDrawing = { id: string; name: string; build_id: string | null; build_n: number; placement: Placement; version: number }
export type Room = {
  id: string; floor_id: string; name: string; number: string | null; type: string | null; area: number
  status: 'active' | 'retired'; version: number
}
export type TreeFloor = { id: string; drawing_id: string; name: string; level: number | null; rooms: Room[] }
type Ring = [number, number][]
/** The 2D plan of a floor: plan coordinates of its drawing, metres, Y up. */
export type FloorPlanData = {
  bounds: [number, number, number, number]
  walls: Ring[][]; partitions: Ring[][]; columns: Ring[][]; stairs: Ring[][]
  openings: { kind: string; poly: Ring[] }[]
  rooms: { id: string | null; name: string; area: number; poly: Ring[]; label: [number, number] }[]
}

const BUILDINGS = '/api/buildings/v1'
const IMPORT = '/api/import/v1'

export const listBuildings = () => api<{ items: Building[] }>(`${BUILDINGS}/buildings`).then(r => r.items)
export const getBuilding = (id: string) => api<Building>(`${BUILDINGS}/buildings/${id}`)
export const createBuilding = (name: string, address: string) =>
  api<Building>(`${BUILDINGS}/buildings`, { method: 'POST', json: { name, address } })
export const deleteBuilding = (id: string) => api<void>(`${BUILDINGS}/buildings/${id}`, { method: 'DELETE' })
export const getTree = (id: string) => api<{ floors: TreeFloor[] }>(`${BUILDINGS}/buildings/${id}/tree`).then(r => r.floors)
export const listPlaced = (id: string) =>
  api<{ items: PlacedDrawing[] }>(`${BUILDINGS}/buildings/${id}/drawings`).then(r => r.items)

export const listDrawings = (building: string) =>
  api<{ items: Drawing[] }>(`${IMPORT}/drawings?building_id=${building}`).then(r => r.items)
export const deleteDrawing = (id: string) => api<void>(`${IMPORT}/drawings/${id}`, { method: 'DELETE' })
export const rebuildDrawing = (id: string) => api<Drawing>(`${IMPORT}/drawings/${id}/builds`, { method: 'POST', json: {} })

function fileForm(file: File, fields: Record<string, string> = {}) {
  const form = new FormData()
  form.append('file', file)
  for (const [k, v] of Object.entries(fields)) form.append(k, v)
  return form
}
export const uploadDrawing = (building: string, file: File) =>
  api<Drawing>(`${IMPORT}/drawings`, { method: 'POST', body: fileForm(file, { building_id: building }) })
/** A new file of an existing drawing; the same file again changes nothing (`unchanged`). */
export const uploadDrawingFile = (drawing: string, file: File) =>
  api<Drawing>(`${IMPORT}/drawings/${drawing}/files`, { method: 'POST', body: fileForm(file) })
export const placeDrawing = (building: string, d: PlacedDrawing, placement: Placement) =>
  api<PlacedDrawing>(`${BUILDINGS}/buildings/${building}/drawings/${d.id}`, { method: 'PATCH', json: { placement, version: d.version } })
export const getFloorPlan = (floor: string) =>
  api<{ plan: FloorPlanData }>(`${BUILDINGS}/floors/${floor}/plan`).then(r => r.plan)
export const patchRoom = (room: Room, patch: { name?: string; type?: string | null }) =>
  api<Room>(`${BUILDINGS}/rooms/${room.id}`, { method: 'PATCH', json: { ...patch, version: room.version } })
export const getDrawing = (id: string) => api<Drawing>(`${IMPORT}/drawings/${id}`)

// ---- people and rights (the building's administrators)

const PEOPLE = '/api/people/v1'
const ACCESS = '/api/access/v1'
export type PersonIn = { full_name: string; position?: string; department?: string; email?: string | null; phone?: string | null }
export type ImportReport = { created: number; updated: number; unchanged: number; errors: { row: number; message: string }[] }

export const listPeople = (q = '') =>
  api<{ items: Person[] }>(`${PEOPLE}/people?q=${encodeURIComponent(q)}`).then(r => r.items)
export const createPerson = (p: PersonIn) => api<Person>(`${PEOPLE}/people`, { method: 'POST', json: p })
export const leavePerson = (id: string) => api<Person>(`${PEOPLE}/people/${id}/leave`, { method: 'POST' })
export const linkPerson = (id: string, user_sub: string) =>
  api<Person>(`${PEOPLE}/people/${id}/link`, { method: 'PUT', json: { user_sub } })
export const importPeople = (file: File) =>
  api<ImportReport>(`${PEOPLE}/people/import`, { method: 'POST', body: fileForm(file) })
export const peopleByIds = (ids: string[]) =>
  api<{ items: { id: string; full_name: string; position: string }[] }>(`${PEOPLE}/people/batch-get`, { method: 'POST', json: { ids } })
    .then(r => r.items)

export const listGrants = (building: string) =>
  api<{ items: Grant[] }>(`${ACCESS}/grants?building_id=${building}`).then(r => r.items)
export const createGrant = (g: { person_id: string; role: Role; scope: { kind: ScopeKind; id: string }; building_id: string }) =>
  api<Grant>(`${ACCESS}/grants`, { method: 'POST', json: g })
export const revokeGrant = (id: string) => api<void>(`${ACCESS}/grants/${id}`, { method: 'DELETE' })

// ---- the catalog: types of equipment and furniture (read by all, changed by the system administrator)

const CATALOG = '/api/catalog/v1'
export type PropKind = 'text' | 'number' | 'date' | 'bool' | 'choice' | 'person'
export type Prop = {
  key: string; title: string; kind: PropKind; unit: string | null; options: { value: string; title: string }[] | null
  required: boolean; stored: 'type' | 'asset'; editable_by: 'system' | 'admin' | 'responsible'
  /** in a resolved schema: the set the property comes from */
  set?: string | null
}
export type Category = { id: string; name: string; color: string; sort: number }
export type PropertySet = { id: string; name: string; description: string; properties: Prop[]; version: number; types?: number }
export type TypeModel = { name: string; size: number; rotation: number; bounds: number[] | null; warnings: string[] }
export type CatalogType = {
  id: string; category_id: string; name: string; size: [number, number, number]; container: boolean; portable: boolean
  sets: string[]; properties: Prop[]; values: Record<string, unknown>; model: TypeModel | null; active: boolean
  schema_version: number; version: number; schema?: Prop[]
}
export type TypeBody = {
  category_id: string; name: string; w: number; d: number; h: number; container: boolean; portable: boolean
  sets: string[]; properties: Prop[]; values: Record<string, unknown>
}

const items = <T,>(path: string) => api<{ items: T[] }>(`${CATALOG}/${path}`).then(r => r.items)
export const listCategories = () => items<Category>('categories')
export const listSets = () => items<PropertySet>('property-sets')
export const listTypes = (active: boolean) => items<CatalogType>(`types?active=${active}`)
export const getType = (id: string) => api<CatalogType>(`${CATALOG}/types/${id}`)
export const saveType = (body: TypeBody, existing?: CatalogType) => existing
  ? api<CatalogType>(`${CATALOG}/types/${existing.id}`, { method: 'PATCH', json: { ...body, version: existing.version } })
  : api<CatalogType>(`${CATALOG}/types`, { method: 'POST', json: body })
export const archiveType = (id: string, archive: boolean) =>
  api<CatalogType>(`${CATALOG}/types/${id}/${archive ? 'archive' : 'restore'}`, { method: 'POST' })
export const putTypeModel = (id: string, file: File) =>
  api<CatalogType>(`${CATALOG}/types/${id}/model`, { method: 'PUT', body: fileForm(file) })
export const deleteTypeModel = (id: string) => api<void>(`${CATALOG}/types/${id}/model`, { method: 'DELETE' })
export const typeModelUrl = (t: CatalogType) => `${CATALOG}/types/${t.id}/model.glb?v=${t.version}`
export const saveSet = (body: { name: string; description: string; properties: Prop[] }, existing?: PropertySet) => existing
  ? api<PropertySet>(`${CATALOG}/property-sets/${existing.id}`, { method: 'PATCH', json: { ...body, version: existing.version } })
  : api<PropertySet>(`${CATALOG}/property-sets`, { method: 'POST', json: body })

// ---- objects: furniture and equipment on the plan

const ASSETS = '/api/assets/v1'
export type AssetState = 'in_use' | 'faulty' | 'in_repair' | 'in_storage' | 'retired'
export const STATES: Record<AssetState, string> = {
  in_use: 'в работе', faulty: 'неисправен', in_repair: 'в ремонте', in_storage: 'на складе', retired: 'списан' }
export type Asset = {
  id: string; type_id: string; type_name: string; building_id: string; floor_id: string; room_id: string
  x: number | null; y: number | null; container_id: string | null; inventory_no: string; serial_no: string | null
  state: AssetState; responsible_id: string | null; props: Record<string, unknown>; note: string
  needs_placement: boolean; needs_fill: boolean; qr_code: string; version: number
}
/** How an object looks in a list and on the plan: fine, needs attention, out of order. */
export const assetTone = (a: Asset) => (a.state === 'faulty' ? 'bad' : a.state !== 'in_use' || a.needs_fill || a.needs_placement ? 'warn' : 'ok')
export type AssetCard = Asset & {
  schema: Prop[]; portable: boolean; container: boolean; children: Asset[]
  /** what the catalog says of the type as a whole: properties kept with the type, with their values */
  type_props: (Prop & { value: unknown })[]
  can: { edit: boolean; manage: boolean; move: boolean }
}
export type HistoryEntry = {
  id: string; at: string; action: string; changes: Record<string, [unknown, unknown]>
  actor: { kind: string; id: string; person_id: string | null }; reverts: string | null; reason: string | null
}
export type AssetFile = { id: string; kind: 'photo' | 'document'; name: string; size: number }

export const listAssets = (params: Record<string, string | undefined>) => {
  const q = new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => !!e[1]))
  return api<{ items: Asset[]; total: number; next: number | null }>(`${ASSETS}/assets?${q}`)
}
/** Everything that matches, page after page: a floor's plan shows all its objects. */
export async function listAllAssets(params: Record<string, string | undefined>): Promise<Asset[]> {
  const all: Asset[] = []
  for (let cursor: number | null = 0; cursor != null && all.length < 20000;) {
    const page: { items: Asset[]; next: number | null } = await listAssets({ ...params, limit: '500', cursor: String(cursor) })
    all.push(...page.items)
    cursor = page.next
  }
  return all
}
export const getAsset = (id: string) => api<AssetCard>(`${ASSETS}/assets/${id}`)
export const createAsset = (body: { type_id: string; floor_id: string; x: number; y: number; inventory_no: string }) =>
  api<Asset>(`${ASSETS}/assets`, { method: 'POST', json: body })
export const patchAsset = (a: Asset, patch: { props?: Record<string, unknown>; note?: string; serial_no?: string }) =>
  api<Asset>(`${ASSETS}/assets/${a.id}`, { method: 'PATCH', json: { ...patch, version: a.version } })
export const setAssetState = (a: Asset, state: AssetState) =>
  api<Asset>(`${ASSETS}/assets/${a.id}/state`, { method: 'POST', json: { state, version: a.version } })
export const setAssetResponsible = (a: Asset, person_id: string | null) =>
  api<Asset>(`${ASSETS}/assets/${a.id}/responsible`, { method: 'POST', json: { person_id, version: a.version } })
export const moveAsset = (a: Asset, floor_id: string, x: number, y: number) =>
  api<Asset>(`${ASSETS}/assets/${a.id}/move`, { method: 'POST', json: { floor_id, x, y, version: a.version } })
export const assetHistory = (id: string) => api<{ items: HistoryEntry[] }>(`${ASSETS}/assets/${id}/history`).then(r => r.items)
export const revertAsset = (id: string, entry: string) => api<Asset>(`${ASSETS}/assets/${id}/history/${entry}/revert`, { method: 'POST' })
export const assetFiles = (id: string) => api<{ items: AssetFile[] }>(`${ASSETS}/assets/${id}/files`).then(r => r.items)
export const addAssetFile = (id: string, file: File) => api<AssetFile>(`${ASSETS}/assets/${id}/files`, { method: 'POST', body: fileForm(file) })
export const deleteAssetFile = (id: string) => api<void>(`${ASSETS}/files/${id}`, { method: 'DELETE' })
export const assetFileUrl = (id: string) => `${ASSETS}/files/${id}`
export const moveAssetInto = (a: Asset, container_id: string) =>
  api<Asset>(`${ASSETS}/assets/${a.id}/move`, { method: 'POST', json: { container_id, version: a.version } })
export const createAssets = (body: { type_id: string; floor_id: string; points: [number, number][]; prefix: string; start: number; width: number }) =>
  api<{ items: Asset[] }>(`${ASSETS}/assets/batch`, { method: 'POST', json: body })
/** All rows or none; a refusal lists the rows at fault (ApiError.rows). */
export async function importAssets(building: string, file: File): Promise<{ created: number }> {
  const response = await fetch(`${ASSETS}/assets/import?building_id=${building}`, { method: 'POST', body: fileForm(file) })
  const body = await response.json()
  if (response.ok) return body
  const error = new ApiError(response.status, body.code ?? 'error', body.detail ?? `Ошибка ${response.status}`)
  error.rows = (body.errors ?? []).map((e: { field: string; message: string }) => `${e.field}: ${e.message}`)
  throw error
}

// ---- stage 5: the cabinet, QR, comments, reports

export type Cabinet = {
  person_id: string | null
  /** the whole building is visible: an administrator, or a right on the building */
  whole: boolean
  rooms: { id: string; name: string; number: string | null; floor_id: string; floor_name: string; level: number | null }[]
  attention: Asset[]; mine: Asset[]; partial: string[]
}
export const getCabinet = (building: string) => api<Cabinet>(`/api/views/cabinet?building_id=${building}`)
/** Whose label this is; 404 both when there is no such code and when the object is not ours to see. */
export const byQr = (code: string) => api<{ asset_id: string; building_id: string }>(`${ASSETS}/qr/${encodeURIComponent(code)}`)
export const assetLabelUrl = (id: string, size = 40) => `${ASSETS}/assets/${id}/label?size=${size}`
export const assetsReportUrl = (params: Record<string, string | undefined>) =>
  `/api/reports/assets.xlsx?${new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => !!e[1]))}`
export const roomSheetUrl = (room: string) => `/api/reports/rooms/${room}/sheet.pdf`

/** A file the services make on request (a sheet of labels, a drawing): fetched, then handed to the browser to save. */
async function download(path: string, init: RequestInit & { json?: unknown }, fallback: string): Promise<void> {
  const { json, ...rest } = init
  const response = await fetch(path, { ...rest, headers: { 'Content-Type': 'application/json', ...rest.headers }, body: JSON.stringify(json) })
  if (!response.ok) {
    let problem: { code?: string; detail?: string } = {}
    try { problem = await response.json() } catch { /* not JSON */ }
    throw new ApiError(response.status, problem.code ?? 'error', problem.detail ?? `Ошибка ${response.status}`)
  }
  const name = decodeURIComponent(/filename\*=UTF-8''([^;]+)/.exec(response.headers.get('content-disposition') ?? '')?.[1] ?? fallback)
  const url = URL.createObjectURL(await response.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
export const labelsSheet = (body: { asset_ids?: string[]; building_id?: string; floor_id?: string; room_id?: string; size?: number }) =>
  download(`${ASSETS}/labels`, { method: 'POST', json: body }, 'метки.pdf')
export const drawingWithObjects = (building: string, drawing_id: string, format: 'dxf' | 'dwg') =>
  download(`/api/reports/buildings/${building}/drawing`, { method: 'POST', json: { drawing_id, format } }, `drawing.${format}`)

export type CommentTarget = 'point' | 'room' | 'asset'
export type Comment = {
  id: string; building_id: string; floor_id: string | null; room_id: string | null
  target_kind: CommentTarget; target_id: string | null; x: number | null; y: number | null; body: string
  author: { sub: string; person_id: string | null; name: string }
  resolved_at: string | null; resolved_by: string | null; created_at: string; version: number
}
export const listComments = (params: { building_id: string; target_kind?: CommentTarget; target_id?: string; floor_id?: string; resolved?: 'true' }) =>
  api<{ items: Comment[] }>(`${BUILDINGS}/comments?${new URLSearchParams(params as Record<string, string>)}`).then(r => r.items)
export const addComment = (body: { building_id: string; target_kind: CommentTarget; target_id?: string; floor_id?: string; x?: number; y?: number; body: string }) =>
  api<Comment>(`${BUILDINGS}/comments`, { method: 'POST', json: body })
export const resolveComment = (id: string) => api<Comment>(`${BUILDINGS}/comments/${id}/resolve`, { method: 'POST' })
export const deleteComment = (id: string) => api<void>(`${BUILDINGS}/comments/${id}`, { method: 'DELETE' })
