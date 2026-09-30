/** The signed-in user (GET /api/auth/me), loaded before the app renders. */

export interface Me {
  id: number | null
  login: string
  name: string
  role: 'viewer' | 'editor' | 'catalog_admin'
  role_name: string
  /** false: the server runs without sign-in (DWG3D_AUTH=off) */
  auth: boolean
}

const RANK = { viewer: 0, editor: 1, catalog_admin: 2 }

export let me: Me | null = null

/** The current user, or null when the server wants a sign-in. */
export async function loadMe(): Promise<Me | null> {
  const r = await fetch('/api/auth/me')
  if (r.status === 401) return (me = null)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (me = await r.json() as Me)
}

export const can = (role: Me['role']) => !!me && RANK[me.role] >= RANK[role]
/** Uploading, rebuilding, furniture, pins, settings */
export const canEdit = () => can('editor')
export const READ_ONLY = 'Только просмотр: изменения доступны роли «редактор».'

export async function signIn(login: string, password: string): Promise<Me> {
  const r = await fetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ login, password }),
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`)
  return (me = body as Me)
}

export async function signOut() {
  await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {})
  location.reload()
}
