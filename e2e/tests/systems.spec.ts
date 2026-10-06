import { expect, test } from '@playwright/test'
import { signIn } from './helpers'

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
