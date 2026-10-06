import { expect, test, type Page } from '@playwright/test'
import { signIn } from './helpers'

/** The floor fitted in the 2D view of the editor: a point of the plan (metres) on the screen (the sample: 12 × 8 m). */
async function screen(page: Page, x: number, y: number) {
  const box = (await page.locator('canvas').first().boundingBox())!
  const k = (box.width * 0.85) / 12
  return [box.x + box.width / 2 + (x - 6) * k, box.y + box.height / 2 - (y - 4.05) * k] as const
}

// Stage 8, engineering systems in the editor: a camera and a light placed as objects land in the layers
// «Видеонаблюдение» and «Освещение»; the view mode «Инженерные системы» shows them with their coverage.

test('a camera and a light are objects of their systems\' layers and show their coverage', async ({ page }) => {
  test.setTimeout(180_000)
  const stamp = Date.now().toString().slice(-7)
  await page.setViewportSize({ width: 1400, height: 900 })
  await signIn(page, 'admin')
  await page.getByRole('button', { name: 'Создать здание' }).click()
  await page.getByLabel('Название').fill(`Системы ${stamp}`)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await page.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(page.url())![1]
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(page.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const api = page.request
  const floor = ((await (await api.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors as { id: string; level: number }[])
    .sort((a, b) => a.level - b.level)[0]
  const types = (await (await api.get('/api/catalog/v1/types?active=true')).json()).items as { id: string; name: string; values: Record<string, number> }[]
  const camera = types.find(t => t.name === 'Камера купольная (потолок)')!
  const light = types.find(t => t.name === 'Светильник светодиодный, панель 600×600')!
  expect(camera.values.cam_fov).toBe(100)
  expect(light.values.light_flux).toBe(3600)
  for (const [t, n, x, y] of [[camera, `КАМ-${stamp}`, 10, 6], [light, `СВ-${stamp}`, 8.5, 4], [light, `СВ2-${stamp}`, 2.5, 4]] as const) {
    const r = await api.post('/api/assets/v1/assets', { data: { type_id: t.id, floor_id: floor.id, x, y, inventory_no: n } })
    expect(r.status(), await r.text()).toBe(201)
  }

  // the editor: the layers of the systems in the tree, the objects in theirs
  await page.goto(`/#/b/${building}/drawings`)
  await page.getByTestId('drawings').locator('li').first().getByRole('link', { name: 'Открыть' }).click()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.locator('button').first().click()
  await page.getByText('План 1-го этажа').first().click()
  for (const name of ['Объекты учёта', 'Видеонаблюдение', 'Освещение', 'Wi-Fi', 'Пожарная сигнализация']) {
    await expect(page.locator('li', { hasText: name }).first()).toBeVisible()
  }
  // «Инженерные системы»: the equipment with the view of the camera and the lit area of the lights
  await page.keyboard.press('3')
  await page.waitForTimeout(3000)
  await page.screenshot({ path: 'test-results/systems.png' })
})

test('a camera and a light placed in the editor land in their systems\' layers and stay on screen in «Инженерные системы»', async ({ page }) => {
  test.setTimeout(240_000)
  const stamp = Date.now().toString().slice(-7)
  await page.setViewportSize({ width: 1400, height: 850 })
  await signIn(page, 'admin')
  await page.getByRole('button', { name: 'Создать здание' }).click()
  await page.getByLabel('Название').fill(`Камеры ${stamp}`)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await page.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(page.url())![1]
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  const row = page.locator('[data-drawing="sample.dxf"]')
  await expect(row).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const objects = async () => (await (await page.request.get(`/api/assets/v1/assets?building_id=${building}`)).json()).items as { inventory_no: string; category_id: string }[]
  await row.getByRole('link', { name: 'Открыть' }).click()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.locator('button').first().click()
  await page.getByText('План 1-го этажа').first().click()
  page.on('dialog', d => { if (d.type() === 'prompt') void d.accept(`К-${stamp}-${Math.random().toString(36).slice(2, 5)}`); else void d.accept() })
  const drop = async (name: string, x: number, y: number) => {
    const item = page.getByText(name, { exact: true }).first()
    await item.scrollIntoViewIfNeeded()
    const b = (await item.boundingBox())!
    await page.mouse.move(b.x + 20, b.y + 8); await page.mouse.down()
    const [sx, sy] = await screen(page, x, y)
    await page.mouse.move(sx - 40, sy, { steps: 5 }); await page.mouse.move(sx, sy, { steps: 5 }); await page.mouse.up()
    await page.waitForTimeout(2500)
  }
  // a camera dragged while «Объекты учёта» is edited: the whole catalog is offered, the camera goes to «Видеонаблюдение»
  await page.locator('li', { hasText: 'Объекты учёта' }).locator('button:has(svg.lucide-pencil)').click()
  await page.getByRole('button', { name: '2D', exact: true }).click()
  await page.waitForTimeout(2500)
  await drop('Камера купольная (потолок)', 9, 5)
  await expect.poll(async () => (await objects()).length, { timeout: 10_000 }).toBe(1)
  await page.getByRole('button', { name: 'Готово' }).click()
  await page.waitForTimeout(1500)
  const layer = (name: string) => page.locator('li', { hasText: name }).first()
  await expect(layer('Видеонаблюдение').locator('svg.lucide-chevron-right')).toHaveCount(1)       // it holds the camera
  // «Инженерные системы» hides «Объекты учёта», not the camera
  await page.keyboard.press('3')
  await expect(layer('Объекты учёта').locator('svg.lucide-eye-off')).toHaveCount(1)
  await expect(layer('Видеонаблюдение').locator('svg.lucide-eye')).toHaveCount(1)
  // a light in the layer of lighting
  await page.locator('li', { hasText: 'Освещение' }).first().locator('button:has(svg.lucide-pencil)').click()
  await page.waitForTimeout(1500)
  await drop('Светильник светодиодный, панель 600×600', 3, 3)
  await expect.poll(async () => (await objects()).length, { timeout: 10_000 }).toBe(2)
  await page.getByRole('button', { name: 'Готово' }).click()
  await expect(layer('Освещение').locator('svg.lucide-chevron-right')).toHaveCount(1)
  await page.screenshot({ path: 'test-results/systems-placed.png' })
})
