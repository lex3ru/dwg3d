import { execSync } from 'node:child_process'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { signIn, users } from './helpers'
import { unzipEntry } from './xlsx'

// Stage 5 (docs/ACCEPTANCE.md, section 7): the cabinet, QR labels, reports, comments.

async function as(browser: Browser, who: keyof typeof users, viewport = { width: 1360, height: 860 }, path = '/'): Promise<Page> {
  const page = await (await browser.newContext({ locale: 'ru-RU', viewport })).newPage()
  await signIn(page, who, path)
  return page
}

type Room = { id: string; name: string }
type Floor = { id: string; name: string; rooms: Room[] }
type Plan = { rooms: { id: string | null; poly: [number, number][][] }[] }

const centroid = (ring: [number, number][]) =>
  [ring.reduce((s, p) => s + p[0], 0) / ring.length, ring.reduce((s, p) => s + p[1], 0) / ring.length] as const

test('the cabinet: my rooms and objects, search, the card by a QR label; labels, reports and comments', async ({ browser }) => {
  test.setTimeout(300_000)
  const stamp = Date.now().toString().slice(-7)
  const tenantName = `Жилец ${stamp}`

  // ---- the administrator: a building from a drawing, three objects in two rooms, a person who keeps one room
  const root = await as(browser, 'admin')
  await root.getByRole('button', { name: 'Создать здание' }).click()
  await root.getByLabel('Название').fill(`Кабинет ${stamp}`)
  await root.getByRole('button', { name: 'Создать', exact: true }).click()
  await root.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(root.url())![1]
  await root.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(root.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const floors: Floor[] = (await (await root.request.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors
  const floor = floors[0]
  const office = floor.rooms.find(r => r.name === 'Кабинет')!
  const other = floor.rooms.find(r => r.name !== 'Кабинет')!
  const plan: Plan = (await (await root.request.get(`/api/buildings/v1/floors/${floor.id}/plan`)).json()).plan
  const inside = (room: Room) => centroid(plan.rooms.find(r => r.id === room.id)!.poly[0])
  const types: { id: string; name: string }[] = (await (await root.request.get('/api/catalog/v1/types?active=true')).json()).items
  const type = (name: string) => types.find(t => t.name === name)!.id
  const put = async (name: string, number: string, room: Room, shift = 0) => {
    const [x, y] = inside(room)
    const r = await root.request.post('/api/assets/v1/assets', { data: { type_id: type(name), floor_id: floor.id, x: x + shift, y, inventory_no: number } })
    expect(r.status(), await r.text()).toBe(201)
    return await r.json() as { id: string; qr_code: string; room_id: string }
  }
  const scope = await put('Гастроскоп', `ГС-${stamp}`, office)
  const couch = await put('Кушетка', `КШ-${stamp}`, office, 0.3)
  const foreign = await put('Кушетка', `ЧЖ-${stamp}`, other)
  expect([scope.room_id, couch.room_id, foreign.room_id]).toEqual([office.id, office.id, other.id])
  await root.goto(`/#/b/${building}/people`)
  await root.getByRole('button', { name: 'Добавить' }).click()
  await root.getByLabel('ФИО').fill(tenantName)
  await root.getByLabel(/Почта/).fill(`${users.tenant.login}@example.test`)
  await root.getByRole('button', { name: 'Добавить', exact: true }).last().click()
  await expect(root.locator(`[data-person="${tenantName}"]`)).toBeVisible()
  await root.goto(`/#/b/${building}/access`)
  const form = root.getByTestId('grant-form')
  await form.getByLabel('Кому').selectOption({ label: tenantName })
  await form.getByLabel('Что может').selectOption({ label: 'ответственный' })
  const option = form.getByLabel('Где').locator('option').filter({ hasText: /Кабинет/ }).first()
  await form.getByLabel('Где').selectOption(await option.getAttribute('value') as string)
  await form.getByRole('button', { name: 'Выдать' }).click()
  await expect(root.locator(`[data-grant="${tenantName}"]`)).toBeVisible()
  await root.goto(`/#/b/${building}/assets/${scope.id}`)
  const card = root.getByTestId('panel').getByTestId('asset-card')
  await card.getByLabel('Ответственный').selectOption({ label: tenantName })
  await expect(card.getByTestId('asset-history')).toContainText('ответственный')

  // ---- the tenant signs in: the cabinet has their room, the object they answer for; the search finds by number
  const tenant = await as(browser, 'tenant')
  await expect(tenant).toHaveURL(new RegExp(`#/b/${building}`), { timeout: 20_000 })
  await expect(tenant.getByTestId('my-rooms')).toContainText('Кабинет')
  await expect(tenant.getByTestId('mine').locator(`[data-asset="ГС-${stamp}"]`)).toBeVisible()
  await tenant.getByLabel('Найти объект').fill(`КШ-${stamp}`)
  await tenant.getByRole('button', { name: 'Найти' }).click()
  await expect(tenant.getByTestId('assets').locator(`[data-asset="КШ-${stamp}"]`)).toBeVisible()
  await expect(tenant.getByTestId('assets-total')).toHaveText('1')
  await tenant.getByTestId('assets').locator(`[data-asset="КШ-${stamp}"]`).click()
  const mine = tenant.getByTestId('panel').getByTestId('asset-card')
  await expect(mine).toContainText(`КШ-${stamp}`)
  await mine.getByRole('link', { name: 'На плане' }).click()
  await expect(tenant.getByTestId('plan').locator(`[data-asset="${couch.id}"]`)).toBeVisible()
  // the whole building's plan with room names, the objects only of their room — by the answers, not the screen
  const seen = (await (await tenant.request.get(`/api/assets/v1/assets?building_id=${building}`)).json()).items as { id: string }[]
  expect(seen.map(a => a.id).sort()).toEqual([scope.id, couch.id].sort())
  expect((await tenant.request.get(`/api/assets/v1/assets/${foreign.id}`)).status()).toBe(404)
  expect((await tenant.request.get(`/api/buildings/v1/floors/${floor.id}/plan`)).status()).toBe(200)
  await expect(tenant.getByTestId('plan').locator('text', { hasText: 'Кабинет' })).toBeVisible()

  // ---- a QR label: theirs opens the card; someone else's — «нет доступа», with no sign the object exists
  await tenant.goto(`/q/${couch.qr_code}`)
  await expect(tenant).toHaveURL(new RegExp(`#/b/${building}/assets/${couch.id}`))
  await expect(tenant.getByTestId('panel').getByTestId('asset-card')).toContainText(`КШ-${stamp}`)
  await tenant.goto(`/q/${foreign.qr_code}`)
  await expect(tenant.getByTestId('qr-denied')).toBeVisible()
  await tenant.goto('/q/NOSUCHCODE')
  await expect(tenant.getByTestId('qr-denied')).toBeVisible()
  expect((await tenant.request.get(`/api/assets/v1/qr/${foreign.qr_code}`)).status()).toBe(404)
  expect((await tenant.request.get('/api/assets/v1/qr/NOSUCHCODE')).status()).toBe(404)
  // without a session the label leads to the sign-in, and after it — to the card
  const phone = await (await browser.newContext({ locale: 'ru-RU', viewport: { width: 360, height: 740 } })).newPage()
  await phone.goto(`/q/${scope.qr_code}`)
  await expect(phone).toHaveURL(/\/kc\/realms\/twin\//)
  await phone.locator('#username').fill(users.tenant.login)
  await phone.locator('#password').fill(users.tenant.password())
  await phone.locator('#kc-login').click()
  await expect(phone).toHaveURL(new RegExp(`#/b/${building}/assets/${scope.id}`), { timeout: 20_000 })
  const phoneCard = phone.getByTestId('panel').getByTestId('asset-card')
  await expect(phoneCard).toContainText(`ГС-${stamp}`)
  // on a phone: nothing wider than the screen, a photo is taken by the camera
  expect(await phone.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360)
  await expect(phoneCard.getByRole('button', { name: 'Снять' })).toBeVisible()
  await expect(phone.getByTestId('asset-camera')).toHaveAttribute('capture', 'environment')
  await phone.goto(`/#/b/${building}`)
  await expect(phone.getByTestId('mine')).toBeVisible()
  expect(await phone.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360)
  await phone.screenshot({ path: 'screenshots/cabinet-phone.png' })

  // ---- labels in PDF: one, and a sheet of the room
  const label = await tenant.request.get(`/api/assets/v1/assets/${couch.id}/label?size=40`)
  expect(label.status()).toBe(200)
  expect(label.headers()['content-type']).toBe('application/pdf')
  expect((await label.body()).subarray(0, 4).toString()).toBe('%PDF')
  const sheet = await root.request.post('/api/assets/v1/labels', { data: { room_id: office.id, size: 30 } })
  expect(sheet.status()).toBe(200)
  expect((await tenant.request.post('/api/assets/v1/labels', { data: { room_id: office.id } })).status()).toBe(403)

  // ---- reports: Excel by the filter with nothing the tenant may not see; the room sheet; the drawing with objects
  const xlsx = await tenant.request.get(`/api/reports/assets.xlsx?building_id=${building}`)
  expect(xlsx.status()).toBe(200)
  const rows = unzipEntry(await xlsx.body(), 'xl/worksheets/sheet1.xml')!
  expect(rows.split('<row ').length - 1).toBe(3)                      // the header and the two objects of the room
  expect(rows).toContain(`КШ-${stamp}`)
  expect(rows).not.toContain(`ЧЖ-${stamp}`)
  expect(rows).toContain('Вид')                                       // a property of the type, as a column
  const pdf = await tenant.request.get(`/api/reports/rooms/${office.id}/sheet.pdf`)
  expect(pdf.status()).toBe(200)
  expect((await pdf.body()).subarray(0, 4).toString()).toBe('%PDF')
  const drawings = (await (await root.request.get(`/api/import/v1/drawings?building_id=${building}`)).json()).items as { id: string }[]
  const dxf = await root.request.post(`/api/reports/buildings/${building}/drawing`, { data: { drawing_id: drawings[0].id, format: 'dxf' } })
  expect(dxf.status(), await dxf.text()).toBe(200)
  expect(dxf.headers()['x-objects-drawn']).toBe('3')
  const text = (await dxf.body()).toString('utf8')
  expect(text).toContain('INVENTORY_NO')
  expect(text).toContain(`ГС-${stamp}`)
  await root.goto(`/#/b/${building}/drawings`)
  const saved = root.waitForEvent('download')
  await root.locator('[data-drawing="sample.dxf"]').getByRole('button', { name: 'С объектами' }).click()
  expect((await saved).suggestedFilename()).toMatch(/объекты\.dxf$/)

  // ---- comments: the tenant on their room and object; the administrator sees and closes; a point on the plan
  await tenant.goto(`/#/b/${building}/rooms/${office.id}`)
  const roomCard = tenant.getByTestId('panel').getByTestId('room-card')
  await roomCard.getByLabel('Новый комментарий').fill('Течёт кран')
  await roomCard.getByRole('button', { name: 'Оставить' }).click()
  await expect(roomCard.getByTestId('comments')).toContainText('Течёт кран')
  await expect(roomCard.getByTestId('comments')).toContainText(users.tenant.name)
  await root.goto(`/#/b/${building}/rooms/${office.id}`)
  const rootRoom = root.getByTestId('panel').getByTestId('room-card')
  await expect(rootRoom.getByTestId('comments')).toContainText('Течёт кран')
  await rootRoom.getByTestId('comments').getByRole('button', { name: 'Закрыть' }).click()
  await expect(rootRoom.getByTestId('comments')).not.toContainText('Течёт кран')
  await expect(roomCard.getByTestId('comments')).not.toContainText('Течёт кран', { timeout: 5000 })   // live, no reload
  await tenant.goto(`/#/b/${building}/assets/${scope.id}`)
  await mine.getByLabel('Новый комментарий').fill('Шумит при включении')
  await mine.getByRole('button', { name: 'Оставить' }).click()
  await expect(mine.getByTestId('comments')).toContainText('Шумит при включении')
  await root.goto(`/#/b/${building}/plan/${floor.id}`)
  await root.getByRole('button', { name: 'Комментарий к точке' }).click()
  const box = (await root.getByTestId('plan').boundingBox())!
  await root.mouse.click(box.x + box.width * 0.7, box.y + box.height * 0.5)
  await root.getByLabel('Текст комментария').fill('Здесь нужна розетка')
  await root.getByTestId('noting').getByRole('button', { name: 'Оставить' }).click()
  await expect(root.getByTestId('plan-notes')).toContainText('Здесь нужна розетка')
  await tenant.goto(`/#/b/${building}/plan/${floor.id}`)
  await expect(tenant.getByTestId('plan-notes')).toContainText('Здесь нужна розетка')  // whoever sees the plan sees the point
  // a comment on an object one cannot see is not even there
  expect((await tenant.request.post('/api/buildings/v1/comments', { data: { building_id: building, target_kind: 'asset', target_id: foreign.id, body: 'x' } })).status()).toBe(404)

  // ---- without the people service the card still opens, without names and with a note
  execSync('docker compose -f ../deploy/docker-compose.yml stop people', { stdio: 'ignore' })
  try {
    await root.goto(`/#/b/${building}/assets/${scope.id}`)
    await expect(card).toContainText(`ГС-${stamp}`)
    await expect(card.getByTestId('partial')).toBeVisible()
  } finally {
    execSync('docker compose -f ../deploy/docker-compose.yml up -d --wait people', { stdio: 'ignore' })    // ready, not just started
  }
})
