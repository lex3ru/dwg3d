import { expect, test, type Browser, type Page } from '@playwright/test'
import { signIn, users } from './helpers'
import { unzipEntry } from './xlsx'

// Scenarios of work with the system by role (docs/SCENARIOS.md): what a person of each role does
// in a working day, end to end, including what the stage scenarios leave out — the limits of
// the keeper of a room, writing off and taking back, two people on one card, search and export,
// input that is not plain text, a shared link.

const PHONE = { width: 360, height: 740 }
const DESK = { width: 1360, height: 860 }

async function as(browser: Browser, who: keyof typeof users, viewport = DESK, path = '/'): Promise<Page> {
  const page = await (await browser.newContext({ locale: 'ru-RU', viewport })).newPage()
  await signIn(page, who, path)
  return page
}

type Room = { id: string; name: string }
type Floor = { id: string; name: string; rooms: Room[] }
type Asset = { id: string; version: number; qr_code: string; room_id: string; state: string; responsible_id: string | null }

const centroid = (ring: [number, number][]) =>
  [ring.reduce((s, p) => s + p[0], 0) / ring.length, ring.reduce((s, p) => s + p[1], 0) / ring.length] as const

/** A building from the sample drawing, made the way an administrator makes one; what the scenarios need of it. */
async function building(root: Page, name: string) {
  await root.goto('/#/buildings')
  await root.getByRole('button', { name: 'Создать здание' }).click()
  await root.getByLabel('Название').fill(name)
  await root.getByRole('button', { name: 'Создать', exact: true }).click()
  await root.waitForURL(/#\/p\//)
  const id = /#\/p\/([\w-]+)/.exec(root.url())![1]
  await root.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(root.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  // the build is done when import says so; the rooms reach the building a moment later, by an event
  let floors: Floor[] = []
  await expect.poll(async () => {
    floors = (await (await root.request.get(`/api/buildings/v1/buildings/${id}/tree`)).json()).floors
    return floors[0]?.rooms.some(r => r.name === 'Кабинет') ?? false
  }, { timeout: 20_000 }).toBe(true)
  const floor = floors[0]
  const office = floor.rooms.find(r => r.name === 'Кабинет')!
  const other = floor.rooms.find(r => r.id !== office.id)!                 // the sample's other room has no name
  const plan = (await (await root.request.get(`/api/buildings/v1/floors/${floor.id}/plan`)).json()).plan as { rooms: { id: string | null; poly: [number, number][][] }[] }
  const inside = (room: Room) => centroid(plan.rooms.find(r => r.id === room.id)!.poly[0])
  const types: { id: string; name: string }[] = (await (await root.request.get('/api/catalog/v1/types?active=true')).json()).items
  /** An object put on the plan through the API, as the plan page does it. */
  const put = async (type: string, number: string, room: Room, shift = 0): Promise<Asset> => {
    const [x, y] = inside(room)
    const r = await root.request.post('/api/assets/v1/assets', {
      data: { type_id: types.find(t => t.name === type)!.id, floor_id: floor.id, x: x + shift, y, inventory_no: number } })
    expect(r.status(), await r.text()).toBe(201)
    return await r.json()
  }
  return { id, floor, office, other, inside, put, types }
}

async function addPerson(page: Page, building: string, name: string, email: string) {
  await page.goto(`/#/b/${building}/people`)
  await page.getByRole('button', { name: 'Добавить' }).click()
  await page.getByLabel('ФИО').fill(name)
  await page.getByLabel(/Почта/).fill(email)
  await page.getByRole('button', { name: 'Добавить', exact: true }).last().click()
  await expect(page.locator(`[data-person="${name}"]`)).toBeVisible()
}

async function give(page: Page, building: string, name: string, role: string, where: string) {
  await page.goto(`/#/b/${building}/access`)
  const form = page.getByTestId('grant-form')
  await form.getByLabel('Кому').selectOption({ label: name })
  await form.getByLabel('Что может').selectOption({ label: role })
  await form.getByLabel('Где').selectOption(where)
  await form.getByRole('button', { name: 'Выдать' }).click()
  await expect(page.locator(`[data-grant="${name}"]`)).toBeVisible()
}

const fresh = async (page: Page, id: string): Promise<Asset> => (await page.request.get(`/api/assets/v1/assets/${id}`)).json()

// ---- С1. The keeper of a room, on a phone: keeps what is in it, and no more
test('С1 the keeper of a room, on a phone, edits what is theirs and cannot place, write off or move what is fixed', async ({ browser }) => {
  test.setTimeout(240_000)
  const stamp = Date.now().toString().slice(-7)
  const steward = `Завхоз ${stamp}`
  const root = await as(browser, 'admin')
  const b = await building(root, `С1 Поликлиника ${stamp}`)
  const scope = await b.put('Гастроскоп', `С1-ГС-${stamp}`, b.office)          // portable
  const couch = await b.put('Кушетка', `С1-КШ-${stamp}`, b.office, 0.4)         // fixed
  const away = await b.put('Кушетка', `С1-ЧЖ-${stamp}`, b.other)
  await addPerson(root, b.id, steward, `${users.steward.login}@example.test`)
  await give(root, b.id, steward, 'ответственный', b.office.id)

  const phone = await as(browser, 'steward', PHONE)
  await expect(phone).toHaveURL(new RegExp(`#/b/${b.id}`), { timeout: 20_000 })
  await expect(phone.getByTestId('my-rooms')).toContainText('Кабинет')
  expect(await phone.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(PHONE.width)
  await phone.screenshot({ path: 'screenshots/scenario-c1-cabinet.png', fullPage: true })

  // a portable object: its own measurements are theirs to keep, the administrator's are text, «списан» is not offered
  await phone.goto(`/#/b/${b.id}/assets/${scope.id}`)
  const card = phone.getByTestId('panel').getByTestId('asset-card')
  await expect(card).toContainText(`С1-ГС-${stamp}`)
  await card.getByLabel('Число проведённых исследований').fill('12')
  await card.getByLabel('Число проведённых исследований').blur()
  await expect(card.getByTestId('asset-history')).toContainText('Число проведённых исследований: — → 12')
  await expect(card.getByLabel('Год выпуска')).toHaveCount(0)
  await expect(card.getByLabel('Состояние объекта').locator('option')).not.toContainText(['списан'])
  await expect(card.getByLabel('Ответственный')).toHaveCount(0)
  await expect(card.getByRole('link', { name: 'Переместить' })).toBeVisible()     // portable: the keeper moves it too
  expect(await phone.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(PHONE.width)
  await phone.screenshot({ path: 'screenshots/scenario-c1-card.png', fullPage: true })

  // a fixed object: the wear is theirs; it is not theirs to move
  await phone.goto(`/#/b/${b.id}/assets/${couch.id}`)
  await expect(card).toContainText(`С1-КШ-${stamp}`)
  await card.getByLabel('Износ').selectOption({ label: 'изношен' })
  await expect(card.getByTestId('asset-history')).toContainText('Износ')
  // the history speaks the words of the choice, as the field does
  await expect(card.getByTestId('asset-history')).toContainText('Износ: — → изношен')
  await expect(card.getByRole('link', { name: 'Переместить' })).toHaveCount(0)

  // the plan: no placing for them, the objects of other rooms are not there
  await phone.goto(`/#/b/${b.id}/plan/${b.floor.id}`)
  await expect(phone.getByTestId('plan')).toBeVisible()
  await expect(phone.getByRole('button', { name: 'Поставить объект' })).toHaveCount(0)
  await expect(phone.getByTestId('plan').locator(`[data-asset="${away.id}"]`)).toHaveCount(0)
  await expect(phone.getByTestId('plan').locator(`[data-asset="${scope.id}"]`)).toHaveCount(1)

  // and by the API, past the screen: no new objects, no writing off, no moving the fixed, nothing of the other room
  const [x, y] = b.inside(b.office)
  expect((await phone.request.post('/api/assets/v1/assets', { data: { type_id: b.types[0].id, floor_id: b.floor.id, x, y, inventory_no: `С1-Х-${stamp}` } })).status()).toBe(403)
  const c = await fresh(phone, couch.id)
  expect((await phone.request.post(`/api/assets/v1/assets/${couch.id}/state`, { data: { state: 'retired', version: c.version } })).status()).toBe(403)
  expect((await phone.request.post(`/api/assets/v1/assets/${couch.id}/move`, { data: { floor_id: b.floor.id, x: x + 0.2, y, version: c.version } })).status()).toBe(403)
  expect((await phone.request.get(`/api/assets/v1/assets/${away.id}`)).status()).toBe(404)
  // the portable one moves within the room
  const s = await fresh(phone, scope.id)
  const moved = await phone.request.post(`/api/assets/v1/assets/${scope.id}/move`, { data: { floor_id: b.floor.id, x: x - 0.3, y, version: s.version } })
  expect(moved.status(), await moved.text()).toBe(200)
})

// ---- С2. Writing off: off the books and out of the lists — and back by the administrator
test('С2 an object written off leaves the lists, keeps its number taken, and is taken back by the administrator', async ({ browser }) => {
  test.setTimeout(240_000)
  const stamp = Date.now().toString().slice(-7)
  const root = await as(browser, 'admin')
  const b = await building(root, `С2 Склад ${stamp}`)
  const number = `С2-КШ-${stamp}`
  const couch = await b.put('Кушетка', number, b.office)
  await b.put('Кушетка', `С2-ДР-${stamp}`, b.office, 0.4)

  await root.goto(`/#/b/${b.id}/assets/${couch.id}`)
  const card = root.getByTestId('panel').getByTestId('asset-card')
  await card.getByLabel('Состояние объекта').selectOption({ label: 'списан' })
  await expect(card.getByTestId('asset-history')).toContainText('списан')
  // read-only now: no fields, no moving
  await expect(card.getByLabel('Материал, цвет')).toHaveCount(0)
  await expect(card.getByRole('link', { name: 'Переместить' })).toHaveCount(0)
  await root.screenshot({ path: 'screenshots/scenario-c2-retired.png' })

  // out of the list and the count, back with the filter «списан»
  await root.goto(`/#/b/${b.id}/assets`)
  await expect(root.getByTestId('assets-total')).toHaveText('1')
  await expect(root.getByTestId('assets').locator(`[data-asset="${number}"]`)).toHaveCount(0)
  await root.getByLabel('Состояние').selectOption({ label: 'списан' })
  await expect(root.getByTestId('assets').locator(`[data-asset="${number}"]`)).toBeVisible()
  // and off the plan
  await root.goto(`/#/b/${b.id}/plan/${b.floor.id}`)
  await expect(root.getByTestId('plan').locator(`[data-asset="${couch.id}"]`)).toHaveCount(0)

  // its number stays taken, with words a person understands
  const [x, y] = b.inside(b.office)
  const again = await root.request.post('/api/assets/v1/assets', { data: { type_id: b.types.find(t => t.name === 'Кушетка')!.id, floor_id: b.floor.id, x, y, inventory_no: number } })
  expect(again.status()).toBe(409)
  expect((await again.json()).detail).toMatch(/[А-Яа-я]/)

  // the journal has it
  await root.goto(`/#/b/${b.id}/journal`)
  await expect(root.getByTestId('journal')).toContainText('объект списан')

  // taken back by the administrator, from the card: on the books, in the list and on the plan again
  await root.goto(`/#/b/${b.id}/assets/${couch.id}`)
  await expect(card).toContainText(number)
  await card.getByLabel('Состояние объекта').selectOption({ label: 'в работе' })
  await expect(card.getByTestId('asset-history').locator('li').first()).toContainText('Состояние: списан → в работе')
  await expect(card.getByLabel('Материал, цвет')).toBeVisible()
  expect((await fresh(root, couch.id)).state).toBe('in_use')
  await root.goto(`/#/b/${b.id}/assets`)
  await expect(root.getByTestId('assets-total')).toHaveText('2')
  await root.goto(`/#/b/${b.id}/plan/${b.floor.id}`)
  await expect(root.getByTestId('plan').locator(`[data-asset="${couch.id}"]`)).toBeVisible()
})

// ---- С3. Two people on one card
test('С3 two administrators on one card: another\'s change neither loses what is being typed nor is overwritten', async ({ browser }) => {
  test.setTimeout(180_000)
  const stamp = Date.now().toString().slice(-7)
  const a = await as(browser, 'admin')
  const b = await building(a, `С3 Корпус ${stamp}`)
  const scope = await b.put('Гастроскоп', `С3-ГС-${stamp}`, b.office)
  const other = await as(browser, 'admin')
  await a.goto(`/#/b/${b.id}/assets/${scope.id}`)
  await other.goto(`/#/b/${b.id}/assets/${scope.id}`)
  const mine = a.getByTestId('panel').getByTestId('asset-card')
  const theirs = other.getByTestId('panel').getByTestId('asset-card')
  await expect(mine).toContainText(`С3-ГС-${stamp}`)
  await expect(theirs).toContainText(`С3-ГС-${stamp}`)

  // the first starts typing the year; meanwhile the second saves a note
  await mine.getByLabel('Год выпуска').fill('2019')
  await theirs.getByLabel('Примечание').fill('после ремонта')
  await theirs.getByLabel('Примечание').blur()
  await expect(theirs.getByTestId('asset-history')).toContainText('Примечание: — → после ремонта')
  // the first one's card catches the change live
  await expect(mine.getByTestId('asset-history')).toContainText('после ремонта', { timeout: 5000 })
  await expect(mine.getByLabel('Год выпуска')).toHaveValue('2019')
  await mine.getByLabel('Год выпуска').blur()
  await expect(mine.getByTestId('asset-history')).toContainText('Год выпуска: — → 2019')
  // neither overwrote the other
  const now = await fresh(a, scope.id) as Asset & { note: string; props: Record<string, unknown> }
  expect(now.note).toBe('после ремонта')
  expect(now.props.made).toBe(2019)

  // a change made on a version already gone is refused, not applied over the newer one
  const stale = await a.request.patch(`/api/assets/v1/assets/${scope.id}`, { data: { note: 'старое', version: now.version - 1 } })
  expect(stale.status()).toBe(409)
  expect((await stale.json()).detail).toMatch(/[А-Яа-я]/)
  expect((await fresh(a, scope.id) as Asset & { note: string }).note).toBe('после ремонта')
})

// ---- С4. Finding: search, filters and export agree
test('С4 search by number and by type, the filters of state and attention, and the Excel of the same choice', async ({ browser }) => {
  test.setTimeout(180_000)
  const stamp = Date.now().toString().slice(-7)
  const root = await as(browser, 'admin')
  const b = await building(root, `С4 Поиск ${stamp}`)
  const c1 = await b.put('Кушетка', `С4-КШ-${stamp}-1`, b.office)
  await b.put('Кушетка', `С4-КШ-${stamp}-2`, b.office, 0.4)
  await b.put('Гастроскоп', `С4-ГС-${stamp}`, b.other)
  const broken = await b.put('Рабочий стол', `С4-СТ-${stamp}`, b.other, 0.4)
  await root.request.post(`/api/assets/v1/assets/${broken.id}/state`, { data: { state: 'faulty', version: broken.version } })

  await root.goto(`/#/b/${b.id}/assets`)
  const total = root.getByTestId('assets-total')
  await expect(total).toHaveText('4')
  const search = root.getByLabel('Поиск объекта')
  await search.fill('кушет')                                                  // part of the type, any case
  await expect(total).toHaveText('2')
  await search.fill(`С4-ГС-${stamp}`)
  await expect(total).toHaveText('1')
  await search.fill(`${stamp}-1`)                                             // part of the number
  await expect(total).toHaveText('1')
  await expect(root.getByTestId('assets').locator(`[data-asset="С4-КШ-${stamp}-1"]`)).toBeVisible()
  await search.fill('нет такого объекта')
  await expect(root.getByText('Ничего не найдено.')).toBeVisible()
  await search.fill('')
  await root.getByLabel('Состояние').selectOption({ label: 'неисправен' })
  await expect(total).toHaveText('1')
  await expect(root.getByTestId('assets').locator(`[data-asset="С4-СТ-${stamp}"]`)).toContainText('неисправен')

  // the Excel of the same choice has the same rows
  const href = await root.getByRole('link', { name: 'В Excel' }).getAttribute('href')
  const xlsx = await root.request.get(href!)
  expect(xlsx.status()).toBe(200)
  const rows = unzipEntry(await xlsx.body(), 'xl/worksheets/sheet1.xml')!
  expect(rows.split('<row ').length - 1).toBe(2)                              // the header and the faulty one
  expect(rows).toContain(`С4-СТ-${stamp}`)

  // the cabinet shows the faulty one among what needs attention; its link opens the same choice
  await root.goto(`/#/b/${b.id}`)
  await expect(root.getByTestId('tasks')).toContainText(/неисправ/i)
  // a room's card lists its objects
  await root.goto(`/#/b/${b.id}/rooms/${b.office.id}`)
  await expect(root.getByTestId('room-assets')).toContainText(`С4-КШ-${stamp}-1`)
  await expect(root.getByTestId('room-assets')).not.toContainText(`С4-ГС-${stamp}`)
  expect(c1.room_id).toBe(b.office.id)
})

// ---- С5. Input that is not plain text
test('С5 markup, quotes, emoji and long names are kept as text everywhere, and reports are still made of them', async ({ browser }) => {
  test.setTimeout(180_000)
  const stamp = Date.now().toString().slice(-7)
  const evil = `<img src=x onerror="window.__pwned=1">"Ёлка" & 🏥 ${stamp}`
  const root = await as(browser, 'admin')
  const b = await building(root, evil)
  await expect(root.getByRole('heading', { name: evil })).toBeVisible()

  // a room named with markup and at the limit of its length
  const long = `${'<b>Кабинет</b> «№1» '.repeat(10)}`.slice(0, 200)
  await root.goto(`/#/b/${b.id}/rooms/${b.office.id}`)
  const room = root.getByTestId('panel').getByTestId('room-card')
  await room.getByRole('button', { name: 'Переименовать' }).click()
  await room.getByLabel('Название помещения').fill(long)
  await room.getByRole('button', { name: 'Сохранить' }).click()
  await expect(room.getByRole('heading', { level: 2 })).toHaveText(long)
  await room.getByLabel('Новый комментарий').fill(`<script>window.__pwned=2</script> ${evil}`)
  await room.getByRole('button', { name: 'Оставить' }).click()
  await expect(room.getByTestId('comments')).toContainText('<script>window.__pwned=2</script>')
  const obj = await b.put('Кушетка', `С5 <i>№</i> "1" ${stamp}`, b.office)
  await root.goto(`/#/b/${b.id}/assets/${obj.id}`)
  const card = root.getByTestId('panel').getByTestId('asset-card')
  await expect(card).toContainText(`С5 <i>№</i> "1" ${stamp}`)
  await card.getByLabel('Примечание').fill(evil)
  await card.getByLabel('Примечание').blur()
  await expect(card.getByTestId('asset-history')).toContainText('onerror')
  await root.goto(`/#/b/${b.id}/journal`)
  await expect(root.getByTestId('journal')).toBeVisible()
  await root.goto(`/#/b/${b.id}`)
  await root.screenshot({ path: 'screenshots/scenario-c5-markup.png' })
  expect(await root.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined()

  // reports of such names: the Excel, the room sheet, a label
  expect((await root.request.get(`/api/reports/assets.xlsx?building_id=${b.id}`)).status()).toBe(200)
  const sheet = await root.request.get(`/api/reports/rooms/${b.office.id}/sheet.pdf`)
  expect(sheet.status(), await sheet.text().catch(() => '')).toBe(200)
  const label = await root.request.get(`/api/assets/v1/assets/${obj.id}/label?size=40`)
  expect(label.status()).toBe(200)

  // an empty name, a name too long — refused with words, nothing made
  for (const name of ['   ', 'х'.repeat(5000)]) {
    const r = await root.request.post('/api/buildings/v1/buildings', { data: { name } })
    expect(r.status(), `здание с именем длиной ${name.length}`).toBe(422)
  }
})

// ---- С6. A link sent to a colleague opens the same place — for whoever may see it
test('С6 a link to an object card opens it after signing in; for someone of another building it is «not found»', async ({ browser }) => {
  test.setTimeout(180_000)
  const stamp = Date.now().toString().slice(-7)
  const root = await as(browser, 'admin')
  const b = await building(root, `С6 Ссылки ${stamp}`)
  const elsewhere = await building(root, `С6 Другое ${stamp}`)
  const scope = await b.put('Гастроскоп', `С6-ГС-${stamp}`, b.office)
  const outsider = `Посторонний ${stamp}`
  await addPerson(root, elsewhere.id, outsider, `${users.outsider.login}@example.test`)
  await give(root, elsewhere.id, outsider, 'просмотр', 'building')

  // the administrator, signed out, follows the link: sign-in, then the card itself
  const link = `/#/b/${b.id}/assets/${scope.id}`
  const fresh = await (await browser.newContext({ locale: 'ru-RU', viewport: DESK })).newPage()
  await fresh.goto(link)
  await expect(fresh).toHaveURL(/\/kc\/realms\/twin\//)
  await fresh.locator('#username').fill(users.admin.login)
  await fresh.locator('#password').fill(users.admin.password())
  await fresh.locator('#kc-login').click()
  await expect(fresh).toHaveURL(new RegExp(`assets/${scope.id}`), { timeout: 20_000 })
  await expect(fresh.getByTestId('panel').getByTestId('asset-card')).toContainText(`С6-ГС-${stamp}`)

  // someone of another building: the same link shows nothing of it
  const other = await as(browser, 'outsider')
  await other.goto(link)
  await expect(other.getByText('Здание не найдено')).toBeVisible()
  await expect(other.getByText(`С6-ГС-${stamp}`)).toHaveCount(0)
  await other.screenshot({ path: 'screenshots/scenario-c6-foreign-link.png' })
  // and after signing out, the back button shows no data
  await other.goto(`/#/b/${elsewhere.id}`)
  await other.getByRole('button', { name: 'Выйти' }).click()
  await expect(other).toHaveURL(/\/kc\/realms\/twin\/|#\/?$/, { timeout: 15_000 })
  expect((await other.request.get('/api/buildings/v1/buildings')).status()).toBe(401)
})

// ---- С7. A person leaves: the objects they answered for are left without, and say so
test('С7 a person who leaves stops answering for objects; the objects show it in the card and the list', async ({ browser }) => {
  test.setTimeout(180_000)
  const stamp = Date.now().toString().slice(-7)
  const root = await as(browser, 'admin')
  const b = await building(root, `С7 Уход ${stamp}`)
  const scope = await b.put('Гастроскоп', `С7-ГС-${stamp}`, b.office)
  const name = `Уходящий ${stamp}`
  await addPerson(root, b.id, name, `leaver-${stamp}@example.test`)
  await root.goto(`/#/b/${b.id}/assets/${scope.id}`)
  const card = root.getByTestId('panel').getByTestId('asset-card')
  await card.getByLabel('Ответственный').selectOption({ label: name })
  await expect(card.getByLabel('Ответственный')).toHaveValue(/.+/)

  await root.goto(`/#/b/${b.id}/people`)
  root.once('dialog', d => d.accept())
  await root.locator(`[data-person="${name}"]`).getByRole('button', { name: 'Выбыл' }).click()
  await expect(root.locator(`[data-person="${name}"]`)).toHaveCount(0)
  await expect.poll(async () => (await fresh(root, scope.id)).responsible_id, { timeout: 20_000 }).toBeNull()
  await root.goto(`/#/b/${b.id}/assets/${scope.id}`)
  await expect(card.getByLabel('Ответственный')).toHaveValue('')
  await expect(card.getByTestId('asset-history')).toContainText('ответственный')
})
