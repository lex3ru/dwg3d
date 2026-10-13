import { execSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { answerNumber, signIn } from './helpers'

// Stage 8 (docs/ACCEPTANCE.md, section 10): variants of placing objects. Routes, zones and calculations
// of the stage are not part of this.

const PRICES: Record<string, number> = { 'Кресло посетителя': 3500, 'Кушетка': 15000, 'Рабочий стол': 12000 }

async function editVariantLayer(page: Page, name: string) {
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.locator('button').first().click()
  await page.getByText('План 1-го этажа').first().click()
  // a variant is a variant of each layer of objects; this one is of «Мебель и оборудование»
  const layer = page.locator('li', { hasText: name }).filter({ hasText: 'Мебель и оборудование' })
  await expect(layer).toBeVisible()
  await layer.locator('button:has(svg.lucide-pencil)').click()
  await expect(page.getByText('Кресло посетителя').first()).toBeVisible()
  await page.getByRole('button', { name: '2D', exact: true }).click()
  await page.waitForTimeout(2000)
}

test('a variant is made, edited in the editor, compared and priced, goes stale and is applied in part', async ({ page }) => {
  test.setTimeout(300_000)
  const stamp = Date.now().toString().slice(-7)
  const alerts: string[] = []
  page.on('dialog', d => {
    if (d.type() === 'alert') alerts.push(d.message())
    void d.accept()
  })
  await page.setViewportSize({ width: 1400, height: 850 })
  await signIn(page, 'admin')
  // prices of the types in the catalog
  const types = (await (await page.request.get('/api/catalog/v1/types?active=true')).json()).items as Record<string, any>[]  // eslint-disable-line @typescript-eslint/no-explicit-any
  for (const t of types.filter(t => t.name in PRICES)) {
    const { id, size, model: _m, active: _a, schema_version: _s, version, ...rest } = t
    const r = await page.request.patch(`/api/catalog/v1/types/${id}`, { data: { ...rest, w: size[0], d: size[1], h: size[2],
      price: PRICES[t.name], version } })
    expect(r.status(), await r.text()).toBe(200)
  }
  const typeId = (n: string) => types.find(t => t.name === n)!.id as string

  await page.getByRole('button', { name: 'Создать здание' }).click()
  await page.getByLabel('Название').fill(`Варианты ${stamp}`)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await page.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(page.url())![1]
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(page.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const floors = (await (await page.request.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors as { id: string; level: number }[]
  const f1 = floors.find(f => f.level === 1)!.id
  const put = async (name: string, number: string, x: number, y: number) => {
    const r = await page.request.post('/api/assets/v1/assets', { data: { type_id: typeId(name), floor_id: f1, x, y, inventory_no: number } })
    expect(r.status(), await r.text()).toBe(201)
    return await r.json() as { id: string; version: number }
  }
  const desk = await put('Рабочий стол', `СТ-${stamp}`, 9, 6.5)
  await put('Кресло посетителя', `КР-${stamp}-1`, 10.5, 2)
  const couch = await put('Кушетка', `КШ-${stamp}`, 2.5, 2)
  const asset = async (id: string) => (await (await page.request.get(`/api/assets/v1/assets/${id}`)).json()) as { state: string; angle: number; x: number; version: number }

  // ---- the variant is made in its section
  await page.goto(`/#/b/${building}/variants`)
  await page.getByLabel('Название варианта').fill('Перестановка')
  await page.getByRole('button', { name: 'Создать вариант' }).click()
  const card = page.getByTestId('variant-card')
  await expect(card.getByRole('heading', { name: 'Перестановка' })).toBeVisible()

  // ---- edited in the editor: a chair added (its number later), the couch taken out, the desk turned
  await card.getByRole('button', { name: 'Открыть в редакторе' }).click()
  await editVariantLayer(page, 'Перестановка')
  const item = (await page.getByText('Кресло посетителя').first().boundingBox())!
  const canvas = (await page.locator('canvas').first().boundingBox())!
  await page.mouse.move(item.x + 20, item.y + 8)
  await page.mouse.down()
  await page.mouse.move(canvas.x + canvas.width / 2 + 60, canvas.y + canvas.height / 2, { steps: 6 })
  await page.mouse.move(canvas.x + canvas.width / 2 + 80, canvas.y + canvas.height / 2, { steps: 4 })
  await page.mouse.up()
  await answerNumber(page, '')                                         // the number is left for later
  await page.waitForTimeout(1500)
  const panel = page.getByRole('complementary').last()
  await page.getByRole('button', { name: 'Снять выделение' }).click()          // back to the list of the floor
  await page.getByRole('button', { name: 'Кушетка', exact: true }).click()
  await page.keyboard.press('Delete')
  await page.waitForTimeout(1200)
  await page.getByRole('button', { name: 'Рабочий стол', exact: true }).click()
  await page.keyboard.press('r')
  await page.waitForTimeout(1500)
  expect(panel).toBeTruthy()
  expect(alerts).toEqual([])

  // the fact is as it was
  expect((await asset(couch.id)).state).toBe('in_use')
  expect((await asset(desk.id)).angle).toBe(0)
  expect(((await (await page.request.get(`/api/assets/v1/assets?building_id=${building}`)).json()).items as unknown[]).length).toBe(3)

  // ---- the section: what differs from the fact, the specification with prices
  await page.goto(`/#/b/${building}/variants`)
  await page.getByTestId('variants').locator('[data-variant="Перестановка"]').click()
  await expect(card.getByTestId('counts')).toHaveText('добавлено 1 · убрано 1 · перемещено 1 · изменено 0')
  await expect(card.getByTestId('changes')).toContainText('поворот')
  const row = (n: string) => card.getByTestId('spec').locator(`[data-type="${n}"]`)
  await expect(row('Кресло посетителя')).toContainText('+1')
  await expect(row('Кушетка')).toContainText('-1')
  await expect(card.getByTestId('total')).toContainText('разница -11 500 ₽')
  await expect(card.getByTestId('total')).toContainText('19 000 ₽')
  await page.screenshot({ path: 'screenshots/variant.png', fullPage: true })
  // the new chair needs a number before it can be placed
  await card.getByTestId('numbers').getByRole('textbox').fill(`КР-${stamp}-2`)
  await card.getByTestId('numbers').getByRole('button', { name: 'Задать' }).click()
  await expect(card.getByTestId('numbers')).toHaveCount(0)

  // ---- meanwhile the desk is moved in the fact: the variant is stale
  const moved = await page.request.post(`/api/assets/v1/assets/${desk.id}/move`, { data: { floor_id: f1, x: 8.5, y: 6.5, version: (await asset(desk.id)).version } })
  expect(moved.status()).toBe(200)
  await expect(card.getByTestId('stale')).toContainText('перемещён', { timeout: 15_000 })
  await expect(page.getByTestId('variants').locator('[data-variant="Перестановка"]')).toContainText('устарел')

  // ---- applied: the turn of the desk conflicts and is refused; the rest is done, with the objects' history
  await card.getByRole('button', { name: 'Применить' }).click()
  await expect(card.getByTestId('apply-result')).toContainText('выполнено 2, отклонено 1')
  await expect(card.getByTestId('apply-result')).toContainText('переместить: объект изменён после того, как вариант был составлен')
  expect((await asset(couch.id)).state).toBe('retired')
  const history = (await (await page.request.get(`/api/assets/v1/assets/${couch.id}/history`)).json()).items as { action: string }[]
  expect(history[0].action).toBe('retired')
  const all = (await (await page.request.get(`/api/assets/v1/assets?building_id=${building}`)).json()).items as { inventory_no: string }[]
  expect(all.map(a => a.inventory_no)).toContain(`КР-${stamp}-2`)
  expect((await asset(desk.id)).x).toBe(8.5)                              // the fact's move stands

  // ---- without the planning service the editor and the cabinet work, with the fact only
  execSync('docker compose -f ../deploy/docker-compose.yml stop planning', { stdio: 'ignore' })
  try {
    await page.goto(`/#/b/${building}`)
    await expect(page.getByTestId('summary')).toBeVisible()
    const drawings = (await (await page.request.get(`/api/buildings/v1/buildings/${building}/drawings`)).json()).items as { id: string }[]
    await page.goto(`/#/f/${drawings[0].id}`)
    await expect(page.getByText('объектов на чертеже: 3')).toBeVisible({ timeout: 30_000 })
    await page.locator('button').first().click()
    await expect(page.locator('li', { hasText: 'Мебель и оборудование' }).first()).toBeVisible()
    await expect(page.locator('li', { hasText: 'Перестановка' })).toHaveCount(0)
  } finally {
    execSync('docker compose -f ../deploy/docker-compose.yml up -d --wait planning', { stdio: 'ignore' })
  }
})
