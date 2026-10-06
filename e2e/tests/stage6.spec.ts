import { execSync } from 'node:child_process'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { signIn, users } from './helpers'

// Stage 6 (docs/ACCEPTANCE.md, section 8): people in rooms, automatic rights, the journal.

async function as(browser: Browser, who: keyof typeof users): Promise<Page> {
  const page = await (await browser.newContext({ locale: 'ru-RU', viewport: { width: 1360, height: 860 } })).newPage()
  await signIn(page, who)
  return page
}

const compose = (cmd: string) => execSync(`docker compose -f ../deploy/docker-compose.yml ${cmd}`, { stdio: 'ignore' })

test('a person assigned to a room sees it without any grant by hand; rights follow responsibility; the journal keeps everything', async ({ browser }) => {
  test.setTimeout(400_000)
  const stamp = Date.now().toString().slice(-7)
  const workerName = `Работник ${stamp}`, mateName = `Коллега ${stamp}`

  // ---- the administrator: a building, two objects in the office, two people of the directory
  const root = await as(browser, 'admin')
  await root.getByRole('button', { name: 'Создать здание' }).click()
  await root.getByLabel('Название').fill(`Люди ${stamp}`)
  await root.getByRole('button', { name: 'Создать', exact: true }).click()
  await root.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(root.url())![1]
  await root.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(root.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const floors = (await (await root.request.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors as
    { id: string; rooms: { id: string; name: string }[] }[]
  const floor = floors[0]
  const office = floor.rooms.find(r => r.name === 'Кабинет')!
  const other = floor.rooms.find(r => r.name !== 'Кабинет')!
  const plan = (await (await root.request.get(`/api/buildings/v1/floors/${floor.id}/plan`)).json()).plan as
    { rooms: { id: string | null; poly: [number, number][][] }[] }
  const inside = (room: { id: string }) => {
    const ring = plan.rooms.find(r => r.id === room.id)!.poly[0]
    return [ring.reduce((s, p) => s + p[0], 0) / ring.length, ring.reduce((s, p) => s + p[1], 0) / ring.length]
  }
  const types = (await (await root.request.get('/api/catalog/v1/types?active=true')).json()).items as { id: string; name: string }[]
  const put = async (name: string, number: string, room: { id: string }, shift = 0) => {
    const [x, y] = inside(room)
    const r = await root.request.post('/api/assets/v1/assets', { data: { type_id: types.find(t => t.name === name)!.id, floor_id: floor.id, x: x + shift, y, inventory_no: number } })
    expect(r.status(), await r.text()).toBe(201)
    return await r.json() as { id: string; version: number }
  }
  const desk = await put('Рабочий стол', `СТ-${stamp}`, office)
  const scope = await put('Гастроскоп', `ГС-${stamp}`, office, 0.4)
  const foreign = await put('Кушетка', `ЧЖ-${stamp}`, other)
  const addPerson = async (name: string, email: string, phone?: string) => {
    const r = await root.request.post('/api/people/v1/people', { data: { full_name: name, position: 'врач', email, phone } })
    expect(r.status(), await r.text()).toBe(201)
    return (await r.json()).id as string
  }
  const worker = await addPerson(workerName, `${users.worker.login}@example.test`)
  const mate = await addPerson(mateName, `mate-${stamp}@example.test`, '100-200')

  // ---- assigned to the office with the desk as the workplace — from the people page; the colleague by request
  await root.goto(`/#/b/${building}/people`)
  const row = root.locator(`[data-person="${workerName}"]`)
  await row.getByRole('button', { name: 'привязать к помещению' }).click()
  const form = row.getByTestId('assign-form')
  const option = form.getByLabel('Помещение').locator('option').filter({ hasText: /Кабинет/ }).first()
  await form.getByLabel('Помещение').selectOption(await option.getAttribute('value') as string)
  await form.getByLabel('Рабочее место').selectOption({ label: `Рабочий стол · СТ-${stamp}` })
  await form.getByRole('button', { name: 'Привязать' }).click()
  await expect(row.locator(`[data-assignment="${office.id}"]`)).toContainText('Кабинет')
  expect((await root.request.put(`/api/people/v1/people/${mate}/assignments/${office.id}`, { data: {} })).status()).toBe(200)

  // ---- the worker signs in: the office is theirs, with its objects and its people — nobody gave a grant by hand
  const me = await as(browser, 'worker')
  await expect(me).toHaveURL(new RegExp(`#/b/${building}`), { timeout: 30_000 })
  await expect(me.getByTestId('my-rooms')).toContainText('Кабинет', { timeout: 30_000 })
  await me.getByRole('complementary', { name: 'Меню' }).getByRole('link', { name: 'Объекты', exact: true }).click()
  await expect(me.getByTestId('assets').locator(`[data-asset="СТ-${stamp}"]`)).toBeVisible()
  await expect(me.getByTestId('assets-total')).toHaveText('2')
  await me.goto(`/#/b/${building}/rooms/${office.id}`)
  const roomCard = me.getByTestId('panel').getByTestId('room-card')
  await expect(roomCard.getByTestId('room-people')).toContainText(mateName)
  await expect(roomCard.getByTestId('room-people')).toContainText('100-200')          // contacts, by the right on the room
  await expect(roomCard.getByTestId('room-people').locator(`[data-person="${workerName}"]`).getByRole('link', { name: 'рабочее место' })).toBeVisible()
  // and not the people of a room they have no right to
  expect((await me.request.get(`/api/people/v1/rooms/${other.id}/people`)).status()).toBe(404)
  expect((await me.request.get(`/api/assets/v1/assets/${foreign.id}`)).status()).toBe(404)
  const grants = async () => (await (await root.request.get(`/api/access/v1/grants?building_id=${building}&person_id=${worker}`)).json()).items as { origin: string; role: string }[]
  expect((await grants()).map(g => g.origin)).toEqual(['assignment'])

  // ---- responsibility gives the right to edit; passing it on takes the right away
  const current = async () => await (await root.request.get(`/api/assets/v1/assets/${scope.id}`)).json() as { version: number }
  const name = async (person: string | null) => {
    const r = await root.request.post(`/api/assets/v1/assets/${scope.id}/responsible`, { data: { person_id: person, version: (await current()).version } })
    expect(r.status(), await r.text()).toBe(200)
  }
  const canEdit = async () => (await me.request.post(`/api/assets/v1/assets/${scope.id}/state`, { data: { state: 'in_repair', version: (await current()).version } })).status() === 200
  await name(worker)
  await expect.poll(canEdit, { timeout: 40_000, intervals: [2000] }).toBe(true)
  await name(mate)
  await expect.poll(canEdit, { timeout: 40_000, intervals: [2000] }).toBe(false)
  expect((await grants()).map(g => g.origin)).toEqual(['assignment'])
  // a right given by hand stays when the assignment goes; the room is theirs until that one goes too
  const manual = await root.request.post('/api/access/v1/grants', { data: { person_id: worker, role: 'viewer', scope: { kind: 'room', id: office.id }, building_id: building } })
  expect(manual.status()).toBe(201)
  await root.goto(`/#/b/${building}/people`)
  await row.locator(`[data-assignment="${office.id}"]`).getByRole('button', { name: 'отвязать' }).click()
  await expect(row.locator(`[data-assignment="${office.id}"]`)).toHaveCount(0)
  await expect.poll(async () => (await grants()).map(g => g.origin), { timeout: 20_000, intervals: [1000] }).toEqual(['manual'])
  await me.goto(`/#/b/${building}`)
  await expect(me.getByTestId('my-rooms')).toContainText('Кабинет')
  expect((await root.request.delete(`/api/access/v1/grants/${(await manual.json()).id}`)).status()).toBe(204)
  const myRooms = async () => ((await (await me.request.get(`/api/views/cabinet?building_id=${building}`)).json()).rooms as unknown[]).length
  await expect.poll(myRooms, { timeout: 40_000, intervals: [2000] }).toBe(0)

  // ---- the journal: who did what, where; filtered by kind; a worker sees only their areas
  await root.goto(`/#/b/${building}/journal`)
  const journal = root.getByTestId('journal')
  await expect(journal.locator('[data-event="people.person.assigned"]').first()).toContainText('привязан к помещению')
  await expect(journal.locator('[data-event="assets.asset.responsible_changed"]').first()).toContainText('назначен ответственный')
  await expect(journal.locator('[data-event="access.grant.created"]').first()).toBeVisible()
  await root.getByLabel('Вид события').selectOption('people.')
  await expect(journal.locator('[data-event^="people."]').first()).toBeVisible()
  await expect(journal.locator('[data-event^="assets."]')).toHaveCount(0)
  await root.getByLabel('Вид события').selectOption('')
  await root.getByLabel('Помещение').selectOption(office.id)
  await expect(journal.locator('[data-event="assets.asset.created"]')).toHaveCount(2)       // not the couch of the other room
  await root.goto(`/#/b/${building}/assets/${scope.id}`)
  await root.getByTestId('panel').getByTestId('asset-card').getByRole('link', { name: 'События объекта в журнале' }).click()
  await expect(journal.locator('li').first()).toBeVisible()
  await expect(journal.locator('[data-event="assets.asset.created"]')).toHaveCount(1)
  // the worker: their own events and the office's while they were there, nothing of the other room or the building
  await name(worker)
  await expect.poll(canEdit, { timeout: 40_000, intervals: [2000] }).toBe(true)
  const mine = (await (await me.request.get(`/api/journal/v1/events?building_id=${building}`)).json()).items as { type: string; asset_id?: string; room_id?: string }[]
  expect(mine.length).toBeGreaterThan(0)
  expect(mine.every(e => e.asset_id === scope.id || (e.room_id === office.id && !e.asset_id) || e.type.startsWith('people.') || e.type.startsWith('access.'))).toBe(true)
  expect(mine.some(e => e.asset_id === foreign.id)).toBe(false)
  expect((await me.request.get('/api/journal/v1/events')).status()).toBe(403)

  // ---- the journal stopped: what happens meanwhile is in the feed after it starts, once
  const feed = async () => {
    const r = await root.request.get(`/api/journal/v1/events?asset_id=${scope.id}&type=assets.asset.state_changed`)
    return r.ok() ? (await r.json()).items as { id: string }[] : []                   // 503 while the journal starts
  }
  const before = (await feed()).length
  compose('stop journal')
  try {
    for (const state of ['in_storage', 'in_use']) {
      const r = await root.request.post(`/api/assets/v1/assets/${scope.id}/state`, { data: { state, version: (await current()).version } })
      expect(r.status()).toBe(200)
    }
  } finally {
    compose('start journal')
  }
  await expect.poll(async () => (await feed()).length, { timeout: 60_000, intervals: [2000] }).toBe(before + 2)
  await new Promise(r => setTimeout(r, 3000))
  const after = await feed()
  expect(after.length).toBe(before + 2)
  expect(new Set(after.map(e => e.id)).size).toBe(after.length)

  // ---- the reconciliation: an automatic grant deleted behind the service's back comes back
  const auto = async () => (await grants()).filter(g => g.origin === 'responsible').length
  expect(await auto()).toBe(1)
  execSync(`docker compose -f ../deploy/docker-compose.yml exec -T db psql -U twin -d access -c "delete from grants where origin = 'responsible' and person_id = '${worker}'"`, { stdio: 'ignore' })
  expect(await auto()).toBe(0)
  const fixed = await root.request.post('/api/access/v1/reconcile')
  expect(fixed.status()).toBe(200)
  expect((await fixed.json()).added).toBeGreaterThanOrEqual(1)
  expect(await auto()).toBe(1)
})
