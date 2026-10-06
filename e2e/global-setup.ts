import { randomBytes } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Two test users in the realm, made through Keycloak's admin API with the
// bootstrap admin of deploy/.env: a system administrator and an ordinary
// user. Their passwords are new on every run and live only in this process.

const base = process.env.TWIN_URL ?? 'http://localhost:8090'

function deployEnv(): Record<string, string> {
  const path = fileURLToPath(new URL('../deploy/.env', import.meta.url))
  if (!existsSync(path)) return {}
  return Object.fromEntries(readFileSync(path, 'utf8').split('\n')
    .filter(line => /^[A-Z_]+=/.test(line)).map(line => line.split(/=(.*)/s).slice(0, 2) as [string, string]))
}

async function call(token: string, method: string, path: string, body?: unknown): Promise<Response> {
  const response = await fetch(`${base}/kc/admin/realms/twin${path}`, {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok && response.status !== 409) throw new Error(`Keycloak ${method} ${path}: ${response.status} ${await response.text()}`)
  return response
}

async function ensureUser(token: string, username: string, firstName: string, lastName: string, admin: boolean): Promise<string> {
  const password = randomBytes(12).toString('base64url')
  await call(token, 'POST', '/users', { username, firstName, lastName, email: `${username}@example.test`, emailVerified: true, enabled: true })
  const [user] = await (await call(token, 'GET', `/users?username=${username}&exact=true`)).json() as { id: string }[]
  await call(token, 'PUT', `/users/${user.id}/reset-password`, { type: 'password', value: password, temporary: false })
  if (admin) {
    const [client] = await (await call(token, 'GET', '/clients?clientId=twin')).json() as { id: string }[]
    const role = await (await call(token, 'GET', `/clients/${client.id}/roles/twin.admin`)).json()
    await call(token, 'POST', `/users/${user.id}/role-mappings/clients/${client.id}`, [role])
  }
  return password
}

export default async function globalSetup() {
  const env = deployEnv()
  const response = await fetch(`${base}/kc/realms/master/protocol/openid-connect/token`, {
    method: 'POST',
    body: new URLSearchParams({
      grant_type: 'password', client_id: 'admin-cli',
      username: env.KEYCLOAK_ADMIN ?? 'kcadmin', password: env.KEYCLOAK_ADMIN_PASSWORD ?? 'kcadmin',
    }),
  })
  if (!response.ok) throw new Error(`Не удалось войти в Keycloak администратором (${response.status}); стек запущен?`)
  const { access_token: token } = await response.json() as { access_token: string }
  process.env.E2E_ADMIN_PASSWORD = await ensureUser(token, 'e2e-admin', 'Проверка', 'Администратор', true)
  process.env.E2E_USER_PASSWORD = await ensureUser(token, 'e2e-user', 'Проверка', 'Пользователь', false)
  // people of the directory in the scenarios of rights: new accounts on every run, since what
  // a run does to a person (rights, «выбыл») stays in the directory
  const run = Date.now().toString(36)
  process.env.E2E_RUN = run
  process.env.E2E_BOSS_PASSWORD = await ensureUser(token, `e2e-boss-${run}`, 'Проверка', 'Начальник', false)
  process.env.E2E_CLERK_PASSWORD = await ensureUser(token, `e2e-clerk-${run}`, 'Проверка', 'Сотрудник', false)
  process.env.E2E_KEEPER_PASSWORD = await ensureUser(token, `e2e-keeper-${run}`, 'Проверка', 'Хранитель', false)
  process.env.E2E_TENANT_PASSWORD = await ensureUser(token, `e2e-tenant-${run}`, 'Проверка', 'Жилец', false)
}
