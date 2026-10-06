import { expect, test, type Browser, type Page } from '@playwright/test'
import { signIn, users } from './helpers'

// Stage 7, guest links (docs/ACCEPTANCE.md, section 9, criteria 7–8): a link to a floor shows its plan, 3D and
// objects to someone without an account, and nothing else; a revoked or expired link opens nothing; openings are
// in the journal.

async function as(browser: Browser, who: keyof typeof users): Promise<Page> {
  const page = await (await browser.newContext({ locale: 'ru-RU', viewport: { width: 1360, height: 900 } })).newPage()
  await signIn(page, who)
  return page
}

async function stranger(browser: Browser): Promise<Page> {
  return (await browser.newContext({ locale: 'ru-RU', viewport: { width: 1360, height: 900 } })).newPage()
}

type Floor = { id: string; level: number; rooms: { id: string; name: string }[] }

test('a link to a floor shows its plan, 3D and objects to a guest — and nothing else; revoked and expired links do not open', async ({ browser }) => {
  test.setTimeout(300_000)
  const stamp = Date.now().toString().slice(-7)

  // ---- the administrator: a building of two floors, objects on both, one of them with a responsible, a comment
  const root = await as(browser, 'admin')
  await root.getByRole('button', { name: 'Создать здание' }).click()
  await root.getByLabel('Название').fill(`Гости ${stamp}`)
  await root.getByRole('button', { name: 'Создать', exact: true }).click()
  await root.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(root.url())![1]
  await root.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(root.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const api = root.request
  const [first, second] = ((await (await api.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors as Floor[])
    .sort((a, b) => a.level - b.level)
  const types = (await (await api.get('/api/catalog/v1/types?active=true')).json()).items as { id: string; name: string }[]
  const put = async (floor: string, number: string, x: number, y: number) => {
    const r = await api.post('/api/assets/v1/assets', { data: { type_id: types.find(t => t.name === 'Кушетка')!.id, floor_id: floor, x, y, inventory_no: number } })
    expect(r.status(), await r.text()).toBe(201)
    return (await r.json()) as { id: string; version: number }
  }
  const seen1 = await put(first.id, `Г1-${stamp}`, 8, 4)
  await put(first.id, `Г2-${stamp}`, 2.5, 4)
  const hidden = await put(second.id, `Г3-${stamp}`, 8, 4)
  const person = await (await api.post('/api/people/v1/people', { data: { full_name: `Ответственный ${stamp}` } })).json()
  expect((await api.post(`/api/assets/v1/assets/${seen1.id}/responsible`, { data: { person_id: person.id, version: seen1.version } })).status()).toBe(200)
  expect((await api.post('/api/buildings/v1/comments', { data: { building_id: building, target_kind: 'point', floor_id: first.id, x: 3, y: 3, body: 'для своих' } })).status()).toBe(201)

  // ---- a link to floor 1 for a contractor, given in «Доступ»; shown once
  await root.goto(`/#/b/${building}/access`)
  const form = root.getByTestId('share-form')
  await form.getByLabel('Что показать').selectOption('floor')
  await form.getByLabel('Этаж').selectOption(first.id)
  await form.getByLabel('Для кого').fill(`подрядчик ${stamp}`)
  await form.getByRole('button', { name: 'Выдать ссылку' }).click()
  const link = (await root.getByTestId('share-link').inputValue()).trim()
  expect(link).toMatch(/\/s\/[\w-]{20,}$/)
  await expect(root.getByTestId('shares')).toContainText(`подрядчик ${stamp}`)
  await expect(root.getByTestId('shares')).toContainText('действует')

  // ---- a guest without an account opens it: the plan, 3D and objects of floor 1
  const guest = await stranger(browser)
  await guest.goto(link)
  await expect(guest).toHaveURL(/#\/g/)
  const view = guest.getByTestId('guest-view')
  await expect(view).toContainText(`Гости ${stamp}`)
  await expect(view).toContainText('Просмотр по ссылке до')
  await expect(guest.getByTestId('guest-objects')).toContainText(`Г1-${stamp}`)
  await expect(guest.getByTestId('guest-objects')).toContainText(`Г2-${stamp}`)
  await expect(guest.getByTestId('guest-objects')).not.toContainText(`Г3-${stamp}`)
  await expect(guest.getByTestId('guest-plan')).toBeVisible()
  await guest.getByRole('button', { name: '3D' }).click()
  await expect(guest.getByTestId('guest-3d').locator('canvas')).toBeVisible({ timeout: 30_000 })

  // ---- and by the answers of the requests: nothing but that floor, no people, responsibles, history, files, comments
  const g = guest.request
  const me = await (await g.get('/api/me')).json()
  expect(me.kind).toBe('guest')
  expect(me.guest.scope).toEqual({ kind: 'floor', id: first.id })
  const tree = (await (await g.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors as Floor[]
  expect(tree.map(f => f.id)).toEqual([first.id])
  expect((await g.get(`/api/buildings/v1/floors/${first.id}/plan`)).status()).toBe(200)
  expect((await g.get(`/api/buildings/v1/floors/${second.id}/plan`)).status()).toBe(404)
  const objects = (await (await g.get('/api/assets/v1/assets', { params: { building_id: building } })).json()).items as Record<string, unknown>[]
  expect(objects.map(a => a.inventory_no).sort()).toEqual([`Г1-${stamp}`, `Г2-${stamp}`])
  for (const a of objects) expect(a.responsible_id ?? null).toBeNull()
  expect((await g.get(`/api/assets/v1/assets/${hidden.id}`)).status()).toBe(404)
  expect((await g.get(`/api/assets/v1/assets/${seen1.id}/history`)).status()).toBe(403)
  expect((await g.get(`/api/assets/v1/assets/${seen1.id}/files`)).status()).toBe(403)
  expect((await g.get('/api/people/v1/people', { params: { building_id: building } })).status()).toBe(403)
  expect((await g.get(`/api/people/v1/rooms/${first.rooms[0].id}/people`)).status()).toBe(403)
  expect((await (await g.get('/api/buildings/v1/comments', { params: { building_id: building } })).json()).items).toEqual([])
  expect((await g.get('/api/journal/v1/events', { params: { building_id: building } })).status()).toBe(403)
  expect((await g.get('/api/views/cabinet', { params: { building_id: building } })).status()).toBe(403)
  const model = (await (await g.get(`/api/buildings/v1/buildings/${building}/model`)).json()).drawings[0]
  expect(model.result.floors.map((f: { floor_id: string }) => f.floor_id)).toEqual([first.id])
  expect((await g.get(model.model_url)).status()).toBe(200)
  expect((await g.get(model.model_url.replace(first.id, second.id))).status()).toBe(404)
  // changes are refused
  expect((await g.patch(`/api/assets/v1/assets/${seen1.id}`, { data: { note: 'гость', version: 99 }, headers: { Origin: new URL(link).origin } })).status()).toBeGreaterThanOrEqual(403)

  // ---- the opening is in the journal and in the list
  await root.goto(`/#/b/${building}/journal`)
  await expect(root.getByText(/открыта ссылка для просмотра/i).first()).toBeVisible({ timeout: 20_000 })
  await root.goto(`/#/b/${building}/access`)
  await expect(root.getByTestId('shares')).toContainText('открыта 1 раз')

  // ---- revoked: the link opens nothing any more
  await root.getByTestId('shares').getByRole('button', { name: 'Отозвать' }).first().click()
  await root.getByRole('button', { name: 'Отозвать', exact: true }).last().click()
  await expect(root.getByTestId('shares')).toContainText('отозвана')
  const late = await stranger(browser)
  await late.goto(link)
  await expect(late.getByTestId('guest-invalid')).toContainText('Ссылка недействительна')

  // ---- expired: a link given until a moment that has passed opens nothing either
  const soon = await api.post('/api/access/v1/shares', { data: { building_id: building, scope: { kind: 'floor', id: first.id },
    expires_at: new Date(Date.now() + 3000).toISOString(), note: 'на минуту' } })
  expect(soon.status()).toBe(201)
  await new Promise(r => setTimeout(r, 3500))
  const expired = await stranger(browser)
  await expired.goto((await soon.json()).url)
  await expect(expired.getByTestId('guest-invalid')).toContainText('Ссылка недействительна')
})

