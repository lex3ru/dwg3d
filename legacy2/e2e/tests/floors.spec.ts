import { expect, test } from '@playwright/test'
import { signIn } from './helpers'

// Floors whose plans carry no title (a plan made from a PDF): the same number twice is flagged on the drawings
// page, the administrator gives a floor its number and name there, and a new build keeps them.

test('a floor gets its number and name by hand when two floors share one', async ({ page }) => {
  test.setTimeout(180_000)
  await page.setViewportSize({ width: 1360, height: 900 })
  await signIn(page, 'admin')
  await page.getByRole('button', { name: 'Создать здание' }).click()
  await page.getByLabel('Название').fill(`Этажи ${Date.now()}`)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await page.waitForURL(/#\/p\//)
  // two drawings of two floors each: numbers 1 and 2 come twice
  for (const n of [1, 2]) {
    await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
    await expect(page.getByTestId('drawings').locator('li')).toHaveCount(n, { timeout: 30_000 })
  }
  await expect(page.getByTestId('drawings').locator('li[data-status="done"]')).toHaveCount(2, { timeout: 90_000 })
  const floors = page.getByTestId('floors')
  await expect(floors.locator('li')).toHaveCount(4, { timeout: 30_000 })
  await expect(floors.getByTestId('floor-twin')).toHaveCount(4)

  // the second drawing's floors are the third and the fourth
  const row = floors.locator('li').nth(1)
  await row.getByRole('button', { name: 'Изменить' }).click()
  await row.getByLabel('Номер этажа').fill('3')
  await row.getByLabel('Название этажа').fill('Третий этаж')
  await row.getByRole('button', { name: 'Сохранить' }).click()
  await expect(floors).toContainText('Третий этаж')
  await expect(floors.getByTestId('floor-twin')).toHaveCount(2)

  // a new build of the drawing keeps the number and the name given by hand
  for (const d of await page.getByTestId('drawings').locator('li').all()) await d.getByRole('button', { name: 'Собрать заново' }).click()
  await expect(page.getByTestId('drawings').locator('li').first()).toContainText('сборка 2', { timeout: 60_000 })
  await expect(page.getByTestId('drawings').locator('li').nth(1)).toContainText('сборка 2', { timeout: 60_000 })
  await expect(page.getByTestId('drawings').locator('li[data-status="done"]')).toHaveCount(2, { timeout: 90_000 })
  await expect(floors).toContainText('Третий этаж')
  await expect(floors.getByTestId('floor-twin')).toHaveCount(2)
})
