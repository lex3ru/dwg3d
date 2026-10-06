import { expect, test, type Browser, type Page } from '@playwright/test'
import { signIn, users } from './helpers'

// Stage 7 (docs/ACCEPTANCE.md, section 9): a new revision of a drawing, rooms merged and split.
// Guest links of the stage are postponed.

async function as(browser: Browser, who: keyof typeof users): Promise<Page> {
  const page = await (await browser.newContext({ locale: 'ru-RU', viewport: { width: 1360, height: 900 } })).newPage()
  await signIn(page, who)
  return page
}

type Room = { id: string; name: string; area: number }
type Floor = { id: string; level: number; rooms: Room[] }

/** Click a point of the floor plan given in plan coordinates (metres). */
async function clickAt(page: Page, x: number, y: number) {
  const svg = page.getByTestId('plan')
  const [vx, vy, vw, vh] = (await svg.getAttribute('viewBox'))!.split(' ').map(Number)
  const box = (await svg.boundingBox())!
  const scale = Math.min(box.width / vw, box.height / vh)
  const left = box.x + (box.width - vw * scale) / 2, top = box.y + (box.height - vh * scale) / 2
  await page.mouse.click(left + (x - vx) * scale, top + (-y - vy) * scale)
}

test('a changed drawing waits as a draft, is corrected and published; objects without a place are found and placed', async ({ browser }) => {
  test.setTimeout(300_000)
  const stamp = Date.now().toString().slice(-7)
  const root = await as(browser, 'admin')
  await root.getByRole('button', { name: 'Создать здание' }).click()
  await root.getByLabel('Название').fill(`Ревизии ${stamp}`)
  await root.getByRole('button', { name: 'Создать', exact: true }).click()
  await root.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(root.url())![1]
  await root.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(root.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const row = root.getByTestId('drawings').locator('li').first()         // its name follows the file: one drawing here

  const tree = async () => (await (await root.request.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors as Floor[]
  const [first, second] = (await tree()).sort((a, b) => a.level - b.level)
  const before = { office1: first.rooms.find(r => r.name === 'Кабинет')!, left1: first.rooms.find(r => r.name === '')!,
                   office2: second.rooms.find(r => r.name === 'Кабинет')!, left2: second.rooms.find(r => r.name === '')! }
  const types = (await (await root.request.get('/api/catalog/v1/types?active=true')).json()).items as { id: string; name: string }[]
  const put = async (floor: string, number: string, x: number, y: number) => {
    const r = await root.request.post('/api/assets/v1/assets', { data: { type_id: types.find(t => t.name === 'Кушетка')!.id, floor_id: floor, x, y, inventory_no: number } })
    expect(r.status(), await r.text()).toBe(201)
    return (await r.json()).id as string
  }
  const lost = await put(second.id, `ПР-${stamp}`, 2.5, 4)         // in the room of floor 2 that will be gone
  const kept = await put(second.id, `ОР-${stamp}`, 8, 4)           // in the office of floor 2, to be renamed
  const right = await put(first.id, `ПЧ-${stamp}`, 10, 4)          // in the part of the office of floor 1 beyond the new wall
  // a person in the unchanged room, and a right on the office of floor 2
  const person = await (await root.request.post('/api/people/v1/people', { data: { full_name: `Ревизор ${stamp}` } })).json()
  expect((await root.request.put(`/api/people/v1/people/${person.id}/assignments/${before.left1.id}`, { data: {} })).status()).toBe(200)
  expect((await root.request.post('/api/access/v1/grants', { data: { person_id: person.id, role: 'viewer', building_id: building,
    scope: { kind: 'room', id: before.office2.id } } })).status()).toBe(201)
  const rights = async () => ((await (await root.request.get(`/api/access/v1/grants?building_id=${building}&person_id=${person.id}`)).json()).items as
    { scope: { id: string }; origin: string }[]).map(g => `${g.origin}:${g.scope.id}`).sort()
  await expect.poll(rights, { timeout: 20_000 }).toEqual([`assignment:${before.left1.id}`, `manual:${before.office2.id}`].sort())

  // ---- the new version of the drawing: on floor 1 the office divided, on floor 2 a room gone and the office renamed
  await root.goto(`/#/b/${building}/drawings`)
  const chooser = root.waitForEvent('filechooser')
  await row.getByRole('button', { name: 'Новый файл' }).click()
  await (await chooser).setFiles('fixtures/sample-changed.dxf')
  const draft = row.getByTestId('draft')
  await expect(draft).toContainText('ждёт проверки', { timeout: 60_000 })
  await expect(draft).toContainText('снимет помещений: 1')
  // nothing has changed yet
  expect((await tree()).map(f => f.rooms.length).sort()).toEqual([2, 2])
  expect((await (await root.request.get(`/api/assets/v1/assets/${lost}`)).json()).needs_placement).toBe(false)
  // the 3D view shows the published build meanwhile, it does not wait for the draft
  await row.getByRole('link', { name: 'Открыть' }).click()
  await expect(root.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await expect(root.getByText('Публикация')).toHaveCount(0)
  const notice = root.getByTestId('draft-notice')
  await expect(notice).toContainText('Сборка 2 ждёт проверки')
  await expect(notice).toContainText('снимет помещений: 1')
  // «Проверить» leads to the drawings with the review open
  await notice.getByRole('link', { name: 'Проверить' }).click()
  const review = row.getByTestId('revision')
  await expect(review).toBeVisible()
  await expect(review.getByTestId('retired')).toContainText('34.78 м²')
  await expect(review).toContainText('переименовано')
  await expect(review).toContainText('Ординаторская')
  // the office continues in the part beyond the new wall (22.69 m²), not in the one with its name written
  const part = review.locator('[data-match]').filter({ hasText: '22.69 м²' })
  await expect(part).toContainText('новое')
  await part.getByLabel('Продолжает помещение').selectOption(before.office1.id)
  await expect(part.getByLabel('Продолжает помещение')).toHaveValue(before.office1.id)
  await expect(review.locator('[data-match]').filter({ hasText: '24.07 м²' }).getByLabel('Продолжает помещение')).toHaveValue('')
  await root.screenshot({ path: 'screenshots/revision.png', fullPage: true })
  await review.getByRole('button', { name: 'Опубликовать' }).click()
  await expect(row.getByTestId('draft')).toHaveCount(0)

  // ---- published: ids kept where the rooms continue; the gone room's object waits to be placed
  const after = (await tree()).sort((a, b) => a.level - b.level)
  expect(after[0].rooms.find(r => r.area === 22.69)!.id).toBe(before.office1.id)
  expect(after[0].rooms.find(r => r.area === 34.78)!.id).toBe(before.left1.id)
  expect(after[1].rooms.map(r => [r.id, r.name])).toEqual([[before.office2.id, 'Ординаторская']])
  const asset = async (id: string) => (await (await root.request.get(`/api/assets/v1/assets/${id}`)).json()) as { room_id: string; needs_placement: boolean; x: number }
  await expect.poll(async () => (await asset(lost)).needs_placement, { timeout: 20_000 }).toBe(true)
  expect((await asset(kept)).room_id).toBe(before.office2.id)
  expect((await asset(kept)).x).toBe(5.5)                                   // floor 2 is aligned 2.5 m otherwise now
  expect((await asset(right)).room_id).toBe(before.office1.id)
  expect(await rights()).toEqual([`assignment:${before.left1.id}`, `manual:${before.office2.id}`].sort())

  await root.goto(`/#/b/${building}/assets`)
  await root.getByLabel('Требует внимания').selectOption('needs_placement')
  await expect(root.getByTestId('assets').locator('[data-asset]')).toHaveCount(1)
  await root.getByTestId('assets').locator(`[data-asset="ПР-${stamp}"]`).click()
  await root.getByTestId('panel').getByTestId('asset-card').getByRole('link', { name: 'Переместить' }).click()
  await expect(root.getByTestId('moving')).toBeVisible()
  await clickAt(root, 4, 4)
  await expect.poll(async () => (await asset(lost)).needs_placement, { timeout: 10_000 }).toBe(false)
  expect((await asset(lost)).room_id).toBe(before.office2.id)

  // ---- rooms by hand: the two parts of the office of floor 1 merged back (the interface merges them when a
  // partition is erased in the editor; here — by the request), then divided by a line on the plan
  const named = after[0].rooms.find(r => r.area === 24.07)!
  const inNamed = await put(after[0].id, `ИМ-${stamp}`, 6.5, 2)
  const merged = await root.request.post(`/api/buildings/v1/rooms/${before.office1.id}/merge`, { data: { with: [named.id] } })
  expect(merged.status(), await merged.text()).toBe(200)
  await expect.poll(async () => (await asset(inNamed)).room_id, { timeout: 10_000 }).toBe(before.office1.id)
  await root.goto(`/#/b/${building}/plan/${after[0].id}/${before.office1.id}`)
  await root.getByRole('button', { name: 'Разделить помещение линией' }).click()
  await clickAt(root, 7.0, 0.1)                                    // in the outer wall, beyond the room
  await clickAt(root, 7.0, 7.9)
  await expect(root.getByTestId('cutting')).toHaveCount(0)
  // the object west of the line is in the new part, the one east of it stays in the office
  await expect.poll(async () => (await asset(inNamed)).room_id, { timeout: 10_000 }).not.toBe(before.office1.id)
  expect((await asset(right)).room_id).toBe(before.office1.id)
})
