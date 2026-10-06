import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { answerNumber, signIn } from './helpers'

// Objects in the 3D editor (stage 4, criterion 2, deferred to the editor): the catalog's types are dragged
// onto the floor, the objects of the assets service are moved and turned there.

/** The floor fitted in the 2D view of the editor: a point of the plan (metres) on the screen. */
async function screen(page: Page, x: number, y: number) {
  const box = (await page.locator('canvas').first().boundingBox())!
  const k = (box.width * 0.85) / 12                                  // the sample's floor is 12 × 8 m, fitted with margins
  return [box.x + box.width / 2 + (x - 6) * k, box.y + box.height / 2 - (y - 4.05) * k] as const
}

test('a type is dragged from the catalog onto the floor and becomes an object; the object is moved and turned', async ({ page }) => {
  test.setTimeout(240_000)
  const stamp = Date.now().toString().slice(-7)
  await page.setViewportSize({ width: 1400, height: 850 })
  await signIn(page, 'admin')
  await page.getByRole('button', { name: 'Создать здание' }).click()
  await page.getByLabel('Название').fill(`Расстановка 3D ${stamp}`)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await page.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(page.url())![1]
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  const row = page.locator('[data-drawing="sample.dxf"]')
  await expect(row).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const floors = (await (await page.request.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors as
    { id: string; level: number; rooms: { id: string; name: string }[] }[]
  const first = floors.find(f => f.level === 1)!
  const office = first.rooms.find(r => r.name === 'Кабинет')!.id
  const left = first.rooms.find(r => r.name !== 'Кабинет')!.id
  const objects = async () => (await (await page.request.get(`/api/assets/v1/assets?building_id=${building}`)).json()).items as
    { id: string; inventory_no: string; room_id: string; x: number; y: number; angle: number; version: number }[]

  // the editor: floor 1, the layer of the objects, the plan from above
  await row.getByRole('link', { name: 'Открыть' }).click()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.locator('button').first().click()
  await page.getByText('План 1-го этажа').first().click()
  await page.locator('li', { hasText: 'Объекты учёта' }).locator('button:has(svg.lucide-pencil)').click()
  await expect(page.getByText('Кресло посетителя')).toBeVisible()
  await page.getByRole('button', { name: '2D', exact: true }).click()
  await page.waitForTimeout(2500)

  // dragged from the catalog into the office: the inventory number is asked; without one nothing is placed
  let dropped: readonly [number, number] = [0, 0]
  const drop = async (x: number, y: number, answer: string | null) => {
    const item = (await page.getByText('Кресло посетителя').boundingBox())!
    await page.mouse.move(item.x + 20, item.y + 8)
    await page.mouse.down()
    const [sx, sy] = await screen(page, x, y)
    dropped = [sx, sy]
    await page.mouse.move(sx - 40, sy, { steps: 5 })
    await page.mouse.move(sx, sy, { steps: 5 })
    await page.mouse.up()
    await answerNumber(page, answer)
  }
  page.on('dialog', d => { if (d.type() === 'alert') void d.accept() })
  await drop(8.5, 4, null)
  await page.waitForTimeout(1500)
  expect(await objects()).toEqual([])
  await page.reload()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.locator('button').first().click()
  await page.getByText('План 1-го этажа').first().click()
  await page.locator('li', { hasText: 'Объекты учёта' }).locator('button:has(svg.lucide-pencil)').click()
  await page.getByRole('button', { name: '2D', exact: true }).click()
  await page.waitForTimeout(2500)
  await drop(8.5, 4, `КР-${stamp}`)
  await expect.poll(async () => (await objects()).length, { timeout: 10_000 }).toBe(1)
  let [chair] = await objects()
  expect(chair.inventory_no).toBe(`КР-${stamp}`)
  expect(chair.room_id).toBe(office)
  expect(Math.abs(chair.x - 8.5)).toBeLessThan(1.5)                  // where dropped (snapping to a wall moves it a little)
  await page.screenshot({ path: 'screenshots/placed-3d.png' })

  // dragged into the other room (a third of the view to the left): the object moves there, with its history
  const [cx, cy] = dropped
  const canvas = (await page.locator('canvas').first().boundingBox())!
  const [tx, ty] = [cx - canvas.width / 3, cy + 40]
  await page.mouse.move(cx, cy)
  await page.mouse.down()
  await page.mouse.move(cx - 30, cy, { steps: 4 })
  await page.mouse.move(tx, ty, { steps: 8 })
  await page.mouse.up()
  await expect.poll(async () => (await objects())[0].room_id, { timeout: 10_000 }).toBe(left)
  const history = (await (await page.request.get(`/api/assets/v1/assets/${chair.id}/history`)).json()).items as { action: string }[]
  expect(history[0].action).toBe('moved')

  // turned by the key; removing is not done in the scene
  ;[chair] = await objects()
  await page.mouse.click(tx, ty)
  await page.keyboard.press('r')
  await expect.poll(async () => (await objects())[0].angle, { timeout: 10_000 }).not.toBe(chair.angle)
  await page.keyboard.press('Delete')
  await page.waitForTimeout(1500)
  expect((await objects()).length).toBe(1)

  // the panel of the selected object (the refused removal reloaded the scene: select it again)
  await page.mouse.click(tx, ty)
  await expect(page.getByTestId('asset-link')).toHaveText(`инв. № КР-${stamp} — карточка`)
  await expect(page.getByRole('button', { name: 'Удалить' })).toHaveCount(0)
  // a row of three: the number asked once, the others go in a row
  await page.getByRole('button', { name: 'Ряд…' }).click()
  await page.getByRole('button', { name: 'Создать ряд' }).click()
  await answerNumber(page, `РЯ-${stamp}-01`)
  await expect.poll(async () => (await objects()).map(o => o.inventory_no).sort(), { timeout: 10_000 })
    .toEqual([`КР-${stamp}`, `РЯ-${stamp}-01`, `РЯ-${stamp}-02`])
  // the size is the type's in the catalog: shown, not edited
  await expect(page.getByText('Габариты').first()).toBeVisible()
  await expect(page.getByLabel('Ширина, см')).toHaveCount(0)

  // the drawing saved from the tree carries the objects as blocks with their numbers
  await page.getByRole('tab', { name: 'Здание' }).click()
  const saved = page.waitForEvent('download')
  await page.getByLabel('Действия с чертежом').click()
  await page.getByRole('menuitem', { name: 'Сохранить DXF с правками' }).click()
  const dxf = readFileSync(await (await saved).path(), 'latin1')
  expect(dxf).toContain(`${stamp}-02`)

  // a layer locked against a slip of the hand stays locked for this viewer after a reload
  const assetsLayer = page.locator('li', { hasText: 'Объекты учёта' }).first()
  await assetsLayer.getByRole('button', { name: 'Блокировка' }).click()
  await expect(assetsLayer.getByRole('button', { name: 'Редактировать слой' })).toBeDisabled()
  await page.reload()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.locator('button').first().click()
  await page.getByText('План 1-го этажа').first().click()
  await expect(assetsLayer.getByRole('button', { name: 'Блокировка' })).toHaveAttribute('aria-pressed', 'true')
  await assetsLayer.getByRole('button', { name: 'Блокировка' }).click()
  await expect(assetsLayer.getByRole('button', { name: 'Редактировать слой' })).toBeEnabled()
  await assetsLayer.getByRole('button', { name: 'Редактировать слой' }).click()
  await page.getByRole('button', { name: '2D', exact: true }).click()
  await page.waitForTimeout(2500)
  // the view is fitted anew after the reload: the chair is found by where it stands, not where it was clicked before
  const now = (await objects()).find(o => o.id === chair.id)!
  await page.mouse.click(...await screen(page, now.x, now.y))
  await page.getByTestId('asset-link').click()
  await expect(page).toHaveURL(new RegExp(`#/b/${building}/assets/${chair.id}`))

  // the same object on the 2D plan of the building, in its new room
  await page.goto(`/#/b/${building}/plan/${first.id}`)
  await expect(page.getByTestId('plan').locator(`[data-asset="${chair.id}"]`)).toBeVisible()
})
