// Requests to the gateway. The session is a cookie; a 401 means it is gone.

export type User = { sub: string; login: string; name: string; email: string | null; roles: string[]; is_admin: boolean }
export type Me = { user: User; person: unknown; scopes: unknown }
export type ServiceStatus = { name: string; ok: boolean; db: boolean | null; nats: boolean | null; ms: number | null }
export type SystemStatus = { services: ServiceStatus[]; viewers: number }
export type Note = { id: string; text: string; created_at: string; echoed_at: string | null; echoes: number }

/** A failure as services report it (application/problem+json). */
export class ApiError extends Error {
  status: number
  code: string
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
export type PlacedDrawing = { id: string; name: string; build_id: string | null; build_n: number }
export type TreeFloor = { id: string; name: string; level: number | null; rooms: { id: string; name: string; area: number }[] }

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
