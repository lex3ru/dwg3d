import { expect, test, type Page } from '@playwright/test'
import { signIn } from './helpers'

// A plan drawn from scratch (docs/TZ.md): the building's administrator draws walls, a partition and a door in
// the 2D editor, names a room; the plan is kept on the server as one draws, built into the building's floors and
// rooms, carried up to a new floor; a save made in another window is not overwritten; a picture goes under it,
// and a page of a PDF; a room is drawn by its inner faces, picked by a box and duplicated; a wall is typed.

// a 1 × 1 PNG
const PNG = Buffer.from('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082', 'hex')

/** Where a point of the plan (meters, Y up) is on the page, at the editor's current view. */
async function at(page: Page, x: number, y: number): Promise<[number, number]> {
  const svg = page.getByTestId('sketch-canvas')
  const box = (await svg.boundingBox())!
  const t = (await svg.locator(':scope > g[transform]').getAttribute('transform'))!
  const [s, , , , tx, ty] = t.slice(t.indexOf('(') + 1, -1).split(/[\s,]+/).map(Number)
  return [box.x + tx + s * x, box.y + ty - s * y]
}

async function click(page: Page, x: number, y: number) {
  const [px, py] = await at(page, x, y)
  await page.mouse.move(px, py)
  await page.mouse.click(px, py)
}

test('a plan drawn from scratch becomes the building', async ({ page }) => {
  test.setTimeout(240_000)
  await page.setViewportSize({ width: 1360, height: 900 })
  await signIn(page, 'admin')
  await page.getByRole('button', { name: 'Создать здание' }).click()
  await page.getByLabel('Название').fill(`Нарисованный ${Date.now()}`)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await page.waitForURL(/#\/p\//)
  const building = page.url().split('#/p/')[1]

  await page.getByTestId('new-sketch').click()
  await page.waitForURL(/#\/sketch\//)
  const summary = page.getByTestId('sketch-summary')
  await expect(summary).toHaveText('Стен: 0 · помещений: 0')
  await expect(page.getByTestId('sketch-build-button')).toBeDisabled()

  // 6 × 4 m of bearing walls (25 cm), corner to corner; the last click on the first corner closes the room
  // (left of and below the origin: the plan opens centred on it, and the panels cover its right top)
  for (const [x, y] of [[-6, -3], [0, -3], [0, 1], [-6, 1], [-6, -3]]) await click(page, x, y)
  await expect(summary).toHaveText('Стен: 4 · помещений: 1 · 21,56 м²')
  // a 10 cm partition from wall to wall cuts the room in two; a door goes into it
  await page.getByTestId('sketch-kind').selectOption('partition')
  await click(page, -3, 1)
  await click(page, -3, -3)
  await page.keyboard.press('Escape')
  await page.keyboard.press('o')
  await click(page, -3, -1)
  // the door placed (the one under the cursor is the next one's preview)
  await expect(page.locator('[data-testid=sketch-canvas] g:not(.op-preview) > .op-swing')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await page.keyboard.press('v')
  await page.keyboard.press('Escape')
  await expect(summary).toHaveText('Стен: 7 · помещений: 2 · 21,19 м²')

  // a room named in the inspector; everything is on the server a moment later
  await click(page, -4.5, -1)
  await page.getByTestId('room-name').fill('Кухня')
  await page.getByTestId('room-name').press('Enter')
  await expect(page.getByTestId('sketch-save')).toHaveText('Сохранено', { timeout: 10_000 })
  await page.reload()
  await expect(summary).toHaveText('Стен: 7 · помещений: 2 · 21,19 м²')
  await expect(page.locator('[data-testid=sketch-canvas] .room-name')).toContainText(['Кухня'])

  // built into the building: its floor and rooms, the named one among them
  await page.getByTestId('sketch-build-button').click()
  await expect(page.getByTestId('sketch-built')).toBeVisible({ timeout: 90_000 })
  // the plan as a DXF drawing
  const download = page.waitForEvent('download')
  await page.getByTestId('sketch-dxf').click()
  expect((await download).suggestedFilename()).toMatch(/\.dxf$/)
  const sketch = page.url()
  await page.goto(`/#/b/${building}/rooms`)
  await expect(page.locator('main')).toContainText('Кухня', { timeout: 30_000 })
  await page.goto(sketch)
  await expect(summary).toHaveText('Стен: 7 · помещений: 2 · 21,19 м²')

  // a save made in another window meanwhile: this one stops and offers to load it
  const other = await page.context().newPage()
  await other.goto(sketch)
  await other.getByTestId('floor-name').fill('Первый')
  await other.getByTestId('floor-name').press('Enter')
  await expect(other.getByTestId('sketch-save')).toHaveText('Сохранено', { timeout: 10_000 })
  await other.close()
  await page.getByTestId('floor-name').fill('Цокольный')
  await page.getByTestId('floor-name').press('Enter')
  const load = page.getByRole('button', { name: 'Загрузить сохранённый' })
  await expect(load).toBeVisible({ timeout: 10_000 })
  await load.click()
  await expect(page.getByTestId('floor-name')).toHaveValue('Первый')

  // a new floor starts with the bearing walls under it, without the partition
  await page.getByTestId('sketch-add-floor').click()
  await page.getByTestId('add-floor-bearing').click()
  await expect(page.getByTestId('sketch-floor')).toHaveValue(/.+/)
  await expect(summary).toHaveText('Стен: 4 · помещений: 1 · 21,56 м²')

  // a picture under the new floor, scaled by two points
  await page.getByTestId('underlay-file').setInputFiles({ name: 'plan.png', mimeType: 'image/png', buffer: PNG })
  const picture = page.getByTestId('sketch-underlay')
  await expect(picture).toBeVisible({ timeout: 10_000 })
  await expect(page.getByTestId('underlay-calibrate-hint')).toBeVisible()
  const before = await picture.getAttribute('transform')
  await click(page, -6, -3)
  await click(page, 0, -3)
  await page.getByTestId('underlay-length').fill('300')
  await page.getByTestId('underlay-length').press('Enter')
  await expect(picture).not.toHaveAttribute('transform', before!)
  await expect(page.getByTestId('sketch-save')).toHaveText('Сохранено', { timeout: 10_000 })

  // a PDF of two pages instead: the second page goes under the floor as a picture
  await page.getByRole('button', { name: 'Убрать подложку' }).click()
  await expect(picture).toHaveCount(0)
  await page.getByTestId('underlay-file').setInputFiles({ name: 'plan.pdf', mimeType: 'application/pdf', buffer: twoPagePdf() })
  await page.getByTestId('underlay-pdf-page').selectOption('2')
  await page.getByTestId('underlay-pdf').getByRole('button', { name: 'Положить' }).click()
  await expect(picture).toBeVisible({ timeout: 15_000 })
  await expect(picture).toHaveAttribute('width', '4000')
  await expect(page.getByTestId('sketch-save')).toHaveText('Сохранено', { timeout: 10_000 })

  // a room drawn by its inner faces, as measured: 4 × 3 m inside, the 25 cm walls go outside
  await page.getByTestId('sketch-add-floor').click()
  await page.getByTestId('add-floor-empty').click()
  await expect(summary).toHaveText('Стен: 0 · помещений: 0')
  await page.keyboard.press('w')
  await page.getByTestId('sketch-kind').selectOption('bearing')
  await page.getByTestId('sketch-draw-by').selectOption('faces')
  for (const [x, y] of [[-5, -2], [-1, -2], [-1, 1], [-5, 1], [-5, -2]]) await click(page, x, y)
  await expect(summary).toHaveText('Стен: 4 · помещений: 1 · 12,00 м²')

  // the room's walls picked by a box and duplicated beside it: one more room
  await page.getByTestId('sketch-tool-select').click()
  await page.keyboard.press('f')                                   // the whole floor in view, with room round it
  // from the bottom left (the toolbar is over the top left of the plan) to the top right
  const [bx0, by0] = await at(page, -5.35, -2.35), [bx1, by1] = await at(page, -0.65, 1.35)
  await page.mouse.move(bx0, by0)
  await page.mouse.down()
  await page.mouse.move(bx1, by1, { steps: 5 })
  await page.mouse.up()
  await expect(page.getByTestId('group-title')).toHaveText('Выбрано стен: 4')
  await page.keyboard.press('Control+d')
  await expect(page.getByTestId('group-title')).toHaveText('Выбрано стен: 4')     // the copy, now picked
  await page.keyboard.press('Escape')
  await expect(summary).toHaveText('Стен: 8 · помещений: 2 · 24,00 м²')

  // a wall typed by its length and its angle: 150 cm straight up
  await page.getByTestId('sketch-tool-wall').click()
  await page.getByTestId('sketch-draw-by').selectOption('axis')
  await click(page, -4.5, -1.5)                                    // inside the first room, in view
  const [ux, uy] = await at(page, -3.5, -1.5)
  await page.mouse.move(ux, uy)
  await page.keyboard.type('150')
  await page.keyboard.press('Comma')
  await page.keyboard.type('90')
  await expect(page.locator('[data-testid=sketch-canvas] .len')).toHaveText('150 см ∠90° ⏎')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  await expect(summary).toHaveText(/^Стен: 9 /)
  await expect(page.getByTestId('sketch-save')).toHaveText('Сохранено', { timeout: 10_000 })
})

/** A PDF of two landscape pages, a rectangle drawn on each. */
function twoPagePdf(): Buffer {
  const page = (content: number) => `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /Contents ${content} 0 R >>`
  const stream = (s: string) => `<< /Length ${s.length} >>\nstream\n${s}\nendstream`
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>', page(5), page(6),
    stream('0 0 0 RG 8 w 50 50 500 300 re S'), stream('0 0 1 RG 8 w 100 100 400 200 re S')]
  let pdf = '%PDF-1.4\n'
  const at: number[] = []
  objects.forEach((o, i) => { at.push(pdf.length); pdf += `${i + 1} 0 obj\n${o}\nendobj\n` })
  const xref = pdf.length
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${at.map(o => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`
  return Buffer.from(pdf, 'latin1')
}
