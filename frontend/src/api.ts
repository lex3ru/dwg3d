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
  kind?: 'user'
  user: User
  /** the user's record in the directory of people; null — the account is not there */
  person: Person | null
  reason: 'unknown' | 'ambiguous' | 'left' | null
  scopes: { admin: boolean; grants: Grant[]; buildings: string[] } | null
  partial: string[]
}
/** Someone who opened a link for viewing (no account): one building, or a floor or a room of it, until a time. */
export type GuestMe = {
  kind: 'guest'; name: string
  guest: {
    building_id: string; building_name: string | null; scope: { kind: 'building' | 'floor' | 'room'; id: string }
    /** the floor of a floor or room link; null — the whole building */
    floor_id: string | null; expires_at: string
  }
}
export const isGuest = (me: Me | GuestMe): me is GuestMe => me.kind === 'guest'
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

// a guest's viewing has ended (the link revoked or expired): whatever was asked, the screen says so
let guestEnded: (() => void) | null = null
export const onGuestEnded = (f: (() => void) | null) => { guestEnded = f }

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
  if (response.status === 401 && problem.code === 'guest_ended') guestEnded?.()
  throw new ApiError(response.status, problem.code ?? 'error', problem.detail ?? problem.title ?? `Ошибка ${response.status}`)
}

export const getMe = () => api<Me | GuestMe>('/api/me')
export const getStatus = () => api<SystemStatus>('/api/system/status')
export const createNote = (text: string) => api<Note>('/api/ping/v1/notes', { method: 'POST', json: { text } })

export async function signOut() {
  const { url } = await api<{ url: string }>('/auth/logout', { method: 'POST' })
  location.assign(url)
}
/** A guest leaves: the session made by the link is dropped, there is nowhere to go after. */
export const endGuest = () => api<unknown>('/auth/logout', { method: 'POST' })

// ---- buildings and their drawings (stage 1: for the system administrator)

export type Building = {
  id: string; name: string; address: string; version: number
  floors?: number; rooms?: number; drawings?: number
}
export type Build = {
  id: string; n: number; status: 'queued' | 'running' | 'done' | 'error'; stage: string; progress: number
  message: string; error: string | null
  /** what was built: an uploaded file, or a drawn plan (a drawing turned into a plan keeps its file builds) */
  of?: 'file' | 'sketch'
}
export type Drawing = {
  id: string; building_id: string; name: string
  /** file: an uploaded DWG/DXF; sketch: a plan drawn in the 2D editor */
  kind: 'file' | 'sketch'
  /** the number of the sketch's last save */
  sketch_version: number | null
  filename: string | null; size: number | null; file_n: number | null
  build: Build | null; current_build_id: string | null; updated_at: string; unchanged?: boolean
}
/** A drawing as the building has taken it in: the build that is shown. */
export type Placement = { dx: number; dy: number; dz: number; rotation: number }
export type PlacedDrawing = {
  id: string; name: string; build_id: string | null; build_n: number; placement: Placement; version: number
  /** the newest revision of the drawing: a draft waits for the administrator */
  revision: { id: string; n: number; status: 'draft' | 'published' | 'discarded'; summary: Record<string, number> } | null
}
export type Room = {
  id: string; floor_id: string; name: string; number: string | null; type: string | null; area: number
  status: 'active' | 'retired'; version: number
}
export type TreeFloor = { id: string; drawing_id: string; name: string; level: number | null; version: number; rooms: Room[] }
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
/** The tree with the building itself: a guest may not ask for the building alone. */
export const getTreeWithBuilding = (id: string) => api<{ building: Building; floors: TreeFloor[] }>(`${BUILDINGS}/buildings/${id}/tree`)
/** The 3D model of the building, by drawing; for a guest of a floor `model_url` is already cut to it. */
export type DrawingModel = { id: string; name: string; build_id: string | null; model_url: string }
export const getModel = (id: string) => api<{ drawings: DrawingModel[] }>(`${BUILDINGS}/buildings/${id}/model`).then(r => r.drawings)
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
/** The name and number of a floor, kept by new builds of its drawing (for plans without titles written on them). */
export const patchFloor = (floor: TreeFloor, patch: { name?: string; level?: number }) =>
  api<TreeFloor>(`${BUILDINGS}/floors/${floor.id}`, { method: 'PATCH', json: { ...patch, version: floor.version } })
export const patchRoom = (room: Room, patch: { name?: string; type?: string | null }) =>
  api<Room>(`${BUILDINGS}/rooms/${room.id}`, { method: 'PATCH', json: { ...patch, version: room.version } })
export const getDrawing = (id: string) => api<Drawing>(`${IMPORT}/drawings/${id}`)
/** The kinds of rooms a build tells apart (its default settings): type → its name and colour. */
export const getRoomTypes = () =>
  api<{ room_types: Record<string, { label: string; color: string }> }>(`${IMPORT}/config/default`).then(c => c.room_types)
/** A new plan drawn from scratch in the building: an empty sheet of the 2D editor. */
export const createSketch = (building: string, name?: string) =>
  api<Drawing>(`${IMPORT}/sketches`, { method: 'POST', json: { building_id: building, name: name ?? '' } })
/**
 * The uploaded drawing turned into a drawn plan from its last build: the same drawing, edited in the 2D editor from
 * now on; its floors and rooms go on. `notes` — what did not come over (an opening that found no wall).
 */
export const drawingToSketch = (drawing: string) =>
  api<Drawing & { notes: string[] }>(`${IMPORT}/drawings/${drawing}/to-sketch`, { method: 'POST' })
export const getSketch = (drawing: string) => api<{ sketch: unknown; version: number }>(`${IMPORT}/drawings/${drawing}/sketch`)
/** A picture to draw the plan over: stored with the drawn plan, its name goes into the floor's underlay. */
export const uploadUnderlay = (drawing: string, file: File) =>
  api<{ id: string; size: number }>(`${IMPORT}/drawings/${drawing}/underlays`, { method: 'POST', body: fileForm(file) })
export const underlayUrl = (drawing: string, image: string) => `${IMPORT}/drawings/${drawing}/underlays/${image}`
/** Saves over the save `version` the edits started from; another save made meanwhile — ApiError 409 «conflict». */
export const saveSketch = (drawing: string, sketch: unknown, version: number) =>
  api<{ version: number }>(`${IMPORT}/drawings/${drawing}/sketch`, { method: 'PUT', json: { sketch, version } })

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

/** A link for viewing without an account: to the building, a floor or a room, until a time. */
export type Share = {
  id: string; building_id: string; scope: { kind: 'building' | 'floor' | 'room'; id: string }
  /** the floor of a floor or room link */
  floor_id: string | null
  note: string; expires_at: string; revoked_at: string | null; state: 'active' | 'revoked' | 'expired'
  opened: number; last_opened_at: string | null; created_by: string; created_at: string
}
export const listShares = (building: string) =>
  api<{ items: Share[] }>(`${ACCESS}/shares?building_id=${building}`).then(r => r.items)
/** The answer holds the link once: it is kept nowhere and cannot be shown again. */
export const createShare = (s: { building_id: string; scope: Share['scope']; floor_id: string | null; expires_at: string; note: string }) =>
  api<Share & { token: string; url: string }>(`${ACCESS}/shares`, { method: 'POST', json: s })
export const revokeShare = (id: string) => api<void>(`${ACCESS}/shares/${id}`, { method: 'DELETE' })

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
/** How objects of a type are mounted and what else the type carries besides its schema. A change of a type
 * replaces it whole, so the editor keeps all of these — the ones it shows and the ones it does not. */
export type TypeRest = {
  elevation: number | null; wall_mounted: boolean; ceiling_mounted: boolean; shape: string; color: string | null
  article: string | null; supplier: string | null; price: number | null; currency: string; sort: number
}
export type CatalogType = TypeRest & {
  id: string; category_id: string; name: string; size: [number, number, number]; container: boolean; portable: boolean
  sets: string[]; properties: Prop[]; values: Record<string, unknown>; model: TypeModel | null; active: boolean
  schema_version: number; version: number; schema?: Prop[]
  /** makes and models offered (active ones) */
  products?: number
}
export type TypeBody = TypeRest & {
  category_id: string; name: string; w: number; d: number; h: number; container: boolean; portable: boolean
  sets: string[]; properties: Prop[]; values: Record<string, unknown>
}

const items = <T,>(path: string) => api<{ items: T[] }>(`${CATALOG}/${path}`).then(r => r.items)
export const listCategories = () => items<Category>('categories')
export const listSets = () => items<PropertySet>('property-sets')
/** A make and model of a type — «Монитор 27″» → Dell P2723DE — with the article, the supplier and the list price;
 * an object may name its product; a variant is priced by the product when named, else by the type's estimate. */
export type Product = {
  id: string; type_id: string; vendor: string; name: string; article: string | null; supplier: string | null
  price: number | null; currency: string; note: string; active: boolean; version: number; sort: number
}
export type ProductBody = Omit<Product, 'id' | 'type_id' | 'active' | 'version'>
export const productLabel = (p: { vendor: string; name: string }) => `${p.vendor} ${p.name}`.trim()
export const listProducts = (typeId: string, active = true) => items<Product>(`types/${typeId}/products?active=${active}`)
export const saveProduct = (typeId: string, body: ProductBody, existing?: Product) => existing
  ? api<Product>(`${CATALOG}/products/${existing.id}`, { method: 'PATCH', json: { ...body, version: existing.version } })
  : api<Product>(`${CATALOG}/types/${typeId}/products`, { method: 'POST', json: body })
export const archiveProduct = (id: string, archive: boolean) =>
  api<Product>(`${CATALOG}/products/${id}/${archive ? 'archive' : 'restore'}`, { method: 'POST' })
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
  /** the make and model named (catalog's product) and a copy of its name */
  product_id: string | null; product_name: string
  state: AssetState; responsible_id: string | null; props: Record<string, unknown>; note: string
  needs_placement: boolean; needs_fill: boolean; qr_code: string; version: number
}
/** How an object looks in a list and on the plan: fine, needs attention, out of order. */
export const assetTone = (a: Asset) => (a.state === 'faulty' ? 'bad' : a.state !== 'in_use' || a.needs_fill || a.needs_placement ? 'warn' : 'ok')
export type AssetCard = Asset & {
  schema: Prop[]; portable: boolean; container: boolean; children: Asset[]
  /** what the catalog says of the type as a whole: properties kept with the type, with their values */
  type_props: (Prop & { value: unknown })[]
  /** the make and model as the catalog describes it; null — none named, or the catalog is down */
  product: Product | null
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
export const createAsset = (body: { type_id: string; product_id?: string | null; floor_id: string; x: number; y: number; inventory_no: string }) =>
  api<Asset>(`${ASSETS}/assets`, { method: 'POST', json: body })
export const patchAsset = (a: Asset, patch: { props?: Record<string, unknown>; note?: string; serial_no?: string; inventory_no?: string; product_id?: string | null }) =>
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
/** A drawn plan as a DXF (or DWG) drawing, as it is saved now. */
export const downloadSketch = (drawing: string, format: 'dxf' | 'dwg' = 'dxf') =>
  download(`${IMPORT}/drawings/${drawing}/export?format=${format}`, { method: 'GET' }, `plan.${format}`)
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

// ---- stage 6: people in rooms, the journal

export type Assignment = { person_id: string; room_id: string; building_id: string; floor_id: string; workplace_asset_id: string | null; created_at: string }
export type RoomPerson = Person & { workplace_asset_id: string | null }
export const listAssignments = (person: string) =>
  api<{ items: Assignment[] }>(`${PEOPLE}/people/${person}/assignments`).then(r => r.items)
export const assignPerson = (person: string, room: string, workplace_asset_id: string | null) =>
  api<Assignment>(`${PEOPLE}/people/${person}/assignments/${room}`, { method: 'PUT', json: { workplace_asset_id } })
export const unassignPerson = (person: string, room: string) =>
  api<void>(`${PEOPLE}/people/${person}/assignments/${room}`, { method: 'DELETE' })
export const roomPeople = (room: string) => api<{ items: RoomPerson[] }>(`${PEOPLE}/rooms/${room}/people`).then(r => r.items)

const JOURNAL = '/api/journal/v1'
export type JournalEvent = {
  id: string; type: string; time: string
  actor: { kind: string; id: string; person_id?: string }
  subject: { kind: string; id: string }
  data: Record<string, unknown>
  building_id?: string; floor_id?: string; room_id?: string; asset_id?: string; person_id?: string
}
export const listEvents = (params: Record<string, string | undefined>) => {
  const q = new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => !!e[1]))
  return api<{ items: JournalEvent[]; next: string | null }>(`${JOURNAL}/events?${q}`)
}

// ---- stage 7: revisions of drawings, rooms merged and split

export type RevisionRoom = {
  candidate: string; idx: number; name: string; area: number; room_id: string | null; auto: boolean
  floor_id: string | null; old_name: string | null
  /** new | name | outline | returned; empty — the same room */
  changes: string[]
}
export type Differences = {
  floors: { candidate: string; floor_id: string | null; name: string; level: number | null }[]
  rooms: RevisionRoom[]
  retired: { id: string; name: string; floor_id: string; area: number }[]
  /** rooms lying whole inside a room of the build (a partition erased): merged into it, what was in them goes there */
  merged?: { id: string; name: string; floor_id: string; area: number; into: string; into_name: string }[]
  floors_retired: string[]
  choices: Record<string, { id: string; name: string; area: number }[]>
  count: { new: number; same: number; changed: number; retired: number; merged?: number; floors_new: number; floors_retired: number }
}
export type Revision = {
  id: string; drawing_id: string; n: number; status: 'draft' | 'published' | 'discarded'; summary: Record<string, unknown>
  differences?: Differences; warnings?: string[]
}
export const getRevision = (id: string) => api<Revision>(`${BUILDINGS}/revisions/${id}`)
export const matchRoom = (id: string, candidate: string, idx: number, room_id: string | null) =>
  api<Revision>(`${BUILDINGS}/revisions/${id}/matches`, { method: 'PATCH', json: { matches: [{ candidate, idx, room_id }] } })
export const publishRevision = (id: string) => api<Revision>(`${BUILDINGS}/revisions/${id}/publish`, { method: 'POST' })
export const discardRevision = (id: string) => api<Revision>(`${BUILDINGS}/revisions/${id}/discard`, { method: 'POST' })

// ---- stage 8: variants of placing objects (the planning service)

const PLANNING = '/api/planning/v1'
export type VariantOp = { id: string; op: 'add' | 'move' | 'change' | 'remove'; asset_id: string | null; base_version: number | null
  data: Record<string, unknown>; conflict?: string | null }
export type Variant = {
  id: string; building_id: string; name: string; based_on: string | null; status: 'draft' | 'applied'; stale: boolean
  stale_reasons: { asset_id?: string; what: string; at: string }[]
  last_result: { applied: { op_id: string; op: string }[]; refused: { op_id: string; op: string; reason: string; asset_id?: string | null }[]; at: string } | null
  counts: { add: number; move: number; change: number; remove: number }; ops?: VariantOp[]
  created_at: string; updated_at: string; applied_at: string | null; version: number
}
export type Comparison = {
  counts: { added: number; removed: number; moved: number; changed: number; same: number }
  objects: { key: string; change: 'added' | 'removed' | 'moved' | 'changed'; what: string[]; asset_id: string | null; op_id: string | null
    type_id: string; name: string; inventory_no: string | null; floor_id: string }[]
  /** a line per type and make and model; `product` — its name, '' for objects of no named model */
  items: { type_id: string; product_id: string | null; name: string; product: string; price: number | null; currency: string
    qty_a: number; qty_b: number; delta: number; sum_a?: number; sum_b?: number }[]
  totals: Record<string, { a: number; b: number; delta: number }>
}
export const listVariants = (building: string) => api<{ items: Variant[] }>(`${PLANNING}/variants?building_id=${building}`).then(r => r.items)
export const getVariant = (id: string) => api<Variant>(`${PLANNING}/variants/${id}`)
export const createVariant = (building_id: string, name: string, based_on: string | null) =>
  api<Variant>(`${PLANNING}/variants`, { method: 'POST', json: { building_id, name, based_on } })
export const deleteVariant = (id: string) => api<void>(`${PLANNING}/variants/${id}`, { method: 'DELETE' })
export const compareWithFact = (building: string, id: string) =>
  api<Comparison>(`${PLANNING}/compare?building_id=${building}&a=fact&b=${id}`)
export const numberAdded = (id: string, op_id: string, inventory_no: string) =>
  api<unknown>(`${PLANNING}/variants/${id}/edits`, { method: 'POST', json: { edits: [{ kind: 'move', op_id, inventory_no }] } })
export const applyVariant = (id: string) => api<Variant & { result: NonNullable<Variant['last_result']> }>(`${PLANNING}/variants/${id}/apply`, { method: 'POST' })
