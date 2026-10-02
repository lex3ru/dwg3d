/** The signed-in user (GET /api/auth/me), loaded before the app renders,
 * and the user's role in the project on screen. Sign-in itself happens in
 * Keycloak: the server sends the browser there and back. */

export type GlobalRole = 'user' | 'catalog_admin' | 'admin'
export type ProjectRole = 'viewer' | 'editor' | 'owner'

export interface Me {
  id: number | null
  login: string
  name: string
  role: GlobalRole
  role_name: string
  /** the application's roles in Keycloak (client roles): dwg3d.admin, dwg3d.user, dwg3d.<role>… */
  roles?: string[]
  email: string | null
  /** false: the server runs without sign-in (DWG3D_AUTH=off) */
  auth: boolean
  /** opened through a share link: read-only, one project */
  guest?: { project_id: string; drawings: string[] | null; layers: string[] | null; name: string }
}

const GLOBAL_RANK: Record<GlobalRole, number> = { user: 0, catalog_admin: 1, admin: 2 }
const PROJECT_RANK: Record<ProjectRole, number> = { viewer: 0, editor: 1, owner: 2 }
export const PROJECT_ROLE_NAMES: Record<ProjectRole, string> = { viewer: 'просмотр', editor: 'редактор', owner: 'владелец' }

export let me: Me | null = null
let projectRole: ProjectRole | null = null

/** The current user, or null when the server wants a sign-in. */
export async function loadMe(): Promise<Me | null> {
  const r = await fetch('/api/auth/me')
  if (r.status === 401) return (me = null)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (me = await r.json() as Me)
}

/** Whether the user has the Keycloak client role dwg3d.<role>. */
export const hasRole = (role: string) => !!me?.roles?.includes(`dwg3d.${role}`)

/** Global roles (from Keycloak): catalog editing, every project. */
export const can = (role: GlobalRole) => !!me && GLOBAL_RANK[me.role] >= GLOBAL_RANK[role]

/** The role in the project on screen (from the server's `my_role`). */
export function setProjectRole(role: ProjectRole | null | undefined) { projectRole = role ?? null }
export const hasProjectRole = (role: ProjectRole) => !!projectRole && PROJECT_RANK[projectRole] >= PROJECT_RANK[role]
/** Uploading, rebuilding, layers, objects, pins, settings */
export const canEdit = () => hasProjectRole('editor')
export const READ_ONLY = 'Только просмотр: изменения доступны участникам проекта с ролью «редактор».'

/** Off to the Keycloak sign-in page; back to where we are now. */
export function signIn() {
  location.href = `/api/auth/login?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`
}

export async function signOut() {
  let url: string | null = null
  try { url = (await (await fetch('/api/auth/logout', { method: 'POST' })).json()).logout_url } catch { /* signed out anyway */ }
  location.href = url ?? '/'
}

/** A share link (#/s/<token>): opens it on the server (a cookie) and returns its project id, null when invalid. */
export async function openShare(token: string): Promise<string | null> {
  const r = await fetch(`/api/share/${encodeURIComponent(token)}`, { method: 'POST' })
  if (!r.ok) return null
  me = await r.json() as Me
  return me.guest?.project_id ?? null
}
