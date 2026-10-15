import { expect, test, type Browser, type Page } from '@playwright/test'
import { signIn, users } from './helpers'

// An object stands on the plan with or without an inventory number: one without is not on the books and can be
// deleted or put on the books; one on the books is only written off (docs/TZ.md, 4.4).

async function as(browser: Browser, who: keyof typeof users): Promise<Page> {
  const page = await (await browser.newContext({ locale: 'ru-RU', viewport: { width: 1360, height: 860 } })).newPage()
  await signIn(page, who)
  return page
}

test('an object is placed without a number, put on the books later; one off the books is deleted, one on them is not', async ({ browser }) => {
  test.setTimeout(240_000)
  const stamp = Date.now().toString().slice(-7)
  const root = await as(browser, 'admin')
  await root.getByRole('button', { name: 'Создать здание' }).click()
  await root.getByLabel('Название').fill(`Учёт ${stamp}`)
  await root.getByRole('button', { name: 'Создать', exact: true }).click()
  await root.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(root.url())![1]
  await root.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(root.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const at = async (fx: number, fy: number) => {
    const box = (await root.getByTestId('plan').boundingBox())!
    await root.mouse.click(box.x + box.width * fx, box.y + box.height * fy)
  }
  const card = root.getByTestId('panel').getByTestId('asset-card')

  // a couch is placed with the number left empty: it stands on the plan, its card says it is not on the books
  await root.goto(`/#/b/${building}/plan`)
  await root.getByRole('button', { name: 'Поставить объект' }).click()
  await root.getByTestId('placing').getByLabel('Тип объекта').selectOption({ label: 'Кушетка' })
  await at(0.7, 0.5)
  await expect(card.getByRole('heading', { name: 'Кушетка' })).toBeVisible()
  await expect(card.getByTestId('unaccounted')).toHaveText('не на учёте')
  const couch = /assets\/([\w-]+)/.exec(root.url())![1]
  // «списан» is not among its states; the list tells those on the books from those off them
  await expect(card.getByLabel('Состояние объекта').locator('option', { hasText: 'списан' })).toHaveCount(0)
  await root.goto(`/#/b/${building}/assets`)
  await root.getByLabel('Учёт').selectOption('без учёта')
  await expect(root.getByTestId('assets').locator(`[data-asset="${couch}"]`)).toContainText('без номера')
  await root.getByLabel('Учёт').selectOption('на учёте')
  await expect(root.getByTestId('assets').locator('[data-asset]')).toHaveCount(0)

  // put on the books with the next free number of its type: from now on it is written off, not deleted
  await root.goto(`/#/b/${building}/assets/${couch}`)
  await card.getByRole('button', { name: 'Поставить на учёт' }).click()
  await card.getByTestId('numbering').getByRole('button', { name: 'На учёт' }).click()
  await expect(card.getByTestId('unaccounted')).toHaveCount(0)
  const given = await (await root.request.get(`/api/assets/v1/assets/${couch}`)).json()
  expect(given.inventory_no).toMatch(/^\S+\d+$/)
  await expect(card).toContainText(given.inventory_no)
  await expect(card.getByTestId('asset-history')).toContainText('поставлен на учёт')
  await expect(card.getByRole('button', { name: 'Удалить' })).toHaveCount(0)
  await expect(card.getByLabel('Состояние объекта').locator('option', { hasText: 'списан' })).toHaveCount(1)
  const refused = await root.request.delete(`/api/assets/v1/assets/${couch}`)
  expect(refused.status()).toBe(409)

  // another one off the books is deleted from the scene for good
  await root.goto(`/#/b/${building}/plan`)
  await root.getByRole('button', { name: 'Поставить объект' }).click()
  await root.getByTestId('placing').getByLabel('Тип объекта').selectOption({ label: 'Кушетка' })
  await at(0.66, 0.56)
  await expect(card.getByTestId('unaccounted')).toBeVisible()
  const loose = /assets\/([\w-]+)/.exec(root.url())![1]
  root.once('dialog', d => d.accept())
  await card.getByRole('button', { name: 'Удалить' }).click()
  await expect(root.getByTestId('plan').locator('[data-asset]')).toHaveCount(1)
  expect((await root.request.get(`/api/assets/v1/assets/${loose}`)).status()).toBe(404)

  // several at once without numbers
  await root.getByRole('button', { name: 'Поставить несколько' }).click()
  const series = root.getByTestId('series')
  await series.getByLabel('Тип объектов').selectOption({ label: 'Кушетка' })
  await series.getByLabel('С инвентарными номерами').uncheck()
  await at(0.68, 0.44); await at(0.72, 0.44)
  await expect(root.getByTestId('series-numbers')).toHaveText('отмечено 2: без учёта … без учёта')
  await series.getByRole('button', { name: 'Поставить 2' }).click()
  await expect(series).toHaveCount(0)
  await expect(root.getByTestId('plan').locator('[data-asset]')).toHaveCount(3)
  const all = await (await root.request.get(`/api/assets/v1/assets?building_id=${building}&accounted=false`)).json()
  expect(all.total).toBe(2)
})
