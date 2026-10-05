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
