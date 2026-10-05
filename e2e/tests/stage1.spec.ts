import { expect, test, type Page } from '@playwright/test'
import { existsSync } from 'node:fs'
import { signIn } from './helpers'

// Stage 1 (docs/ACCEPTANCE.md, section 3): drawings become a building.
// fixtures/sample.dxf is a small two-storey plan (services/import/tests/make_sample.py).

const REAL = ['../legacy/2022-06-02 - Поэтажные планы.dwg', '../legacy/mnogoprofilny_meditsinskiy_tsentr.dwg']

async function newBuilding(page: Page, name: string) {
  await signIn(page, 'admin')
  await page.getByRole('button', { name: 'Создать здание' }).click()
  await page.getByLabel('Название').fill(name)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

const drawing = (page: Page, name: string) => page.locator(`[data-drawing="${name}"]`)

test('the administrator makes a building from a drawing, opens it in 3D and 2D and finds a room', async ({ page }) => {
  test.setTimeout(120_000)
  const failed: string[] = []
  page.on('pageerror', e => failed.push(String(e)))
  page.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/api/me')) failed.push(`${r.status()} ${r.url()}`) })
  await page.setViewportSize({ width: 1400, height: 800 })
  const name = `Проверка ${Date.now()}`
  await newBuilding(page, name)

  // upload: the build runs by itself, its state is shown as it goes
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  const row = drawing(page, 'sample.dxf')
  await expect(row).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  await expect(page.getByTestId('totals')).toHaveText('Этажей: 2 · помещений: 4')
  await expect(page.getByTestId('floors').locator('li')).toHaveCount(2)

  // the same file again builds nothing
  await row.getByRole('button', { name: 'Новый файл' }).click()
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(page.getByRole('alert')).toContainText('тот же файл')
  await expect(row).toContainText('сборка 1')

  // the viewer: 3D, then the plan of a floor, then a room found by its name
  await row.getByRole('link', { name: 'Открыть' }).click()
  await expect(page).toHaveURL(/#\/f\/[\w-]+/)
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: '3D', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '2D', exact: true }).click()
  await expect(page).toHaveURL(/\/floor_\w+\/2d/)

  await page.locator('button').first().click()                       // the left dock: the tree of the building
  const search = page.getByPlaceholder('Помещение, этаж или слой')
  await search.fill('Кабинет')
  const found = page.getByText('Кабинет', { exact: true }).first()
  await expect(found).toBeVisible()
  await found.click()
  await expect(page.getByText(/48[.,]7/).first()).toBeVisible()      // its card: the area

  // back to the list: the building is there with its numbers
  await page.goto('/#/buildings')
  await expect(page.getByTestId('buildings').getByText(name)).toBeVisible()
  expect(failed).toEqual([])
})

test('a file that is not a drawing fails with a message, not a hanging build', async ({ page }) => {
  await newBuilding(page, `Сбой ${Date.now()}`)
  await page.getByTestId('file').setInputFiles('fixtures/broken.dxf')
  const row = drawing(page, 'broken.dxf')
  await expect(row).toHaveAttribute('data-status', 'error', { timeout: 60_000 })
  await expect(row.getByRole('alert')).not.toBeEmpty()
  await expect(row.getByRole('link', { name: 'Открыть' })).toHaveCount(0)

  page.once('dialog', d => d.accept())
  await row.getByTitle('Удалить чертёж').click()
  await expect(row).toHaveCount(0)
})

test('an ordinary user does not get to buildings and drawings yet', async ({ page }) => {
  await signIn(page, 'user')
  for (const path of ['/api/buildings/v1/buildings', '/api/import/v1/config/default']) {
    expect((await page.request.get(path)).status(), path).toBe(403)
  }
})

test('the two real drawings build into one building', async ({ page }) => {
  test.skip(!REAL.every(f => existsSync(f)), 'the real drawings are not in legacy/ (they are not in the repository)')
  test.setTimeout(900_000)
  await page.setViewportSize({ width: 1400, height: 800 })
  await newBuilding(page, `Два чертежа ${Date.now()}`)
  for (const file of REAL) {
    await page.getByTestId('file').setInputFiles(file)
    const row = drawing(page, file.split('/').pop()!)
    await expect(row).toHaveAttribute('data-status', 'done', { timeout: 600_000 })
  }
  const totals = await page.getByTestId('totals').textContent()
  console.log('real drawings:', totals)
  expect(Number(/Этажей: (\d+)/.exec(totals!)![1])).toBeGreaterThanOrEqual(14)
  await expect(page.getByRole('link', { name: 'Открыть' })).toHaveCount(2)
})
