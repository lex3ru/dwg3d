import { expect, test, type Page } from '@playwright/test'
import { signIn } from './helpers'

// Makes and models of a type: added in the catalog, named when an object is placed and in its card; the object
// keeps the name, the variant is priced by the model (the services' tests cover the prices).

/** The floor fitted in the 2D view of the editor: a point of the plan (metres) on the screen (the sample: 12 × 8 m). */
async function screen(page: Page, x: number, y: number) {
  const box = (await page.locator('canvas').first().boundingBox())!
  const k = (box.width * 0.85) / 12
  return [box.x + box.width / 2 + (x - 6) * k, box.y + box.height / 2 - (y - 4.05) * k] as const
}

test('a make and model is added to a type, named at placing and changed in the card', async ({ page }) => {
  test.setTimeout(240_000)
  const stamp = Date.now().toString().slice(-7)
  await page.setViewportSize({ width: 1400, height: 850 })
  await signIn(page, 'admin')
  const chair = ((await (await page.request.get('/api/catalog/v1/types?active=true')).json()).items as { id: string; name: string }[])
    .find(t => t.name === 'Кресло посетителя')!

  // ---- the catalog: a model with its price, listed on the type
  await page.goto(`/#/catalog/types/${chair.id}`)
  await page.getByRole('button', { name: 'Модель', exact: true }).click()
  const form = page.getByTestId('product-form')
  await form.getByLabel('Производитель').fill('Бюрократ')
  await form.getByLabel('Модель', { exact: true }).fill(`CH-${stamp}`)
  await form.getByLabel('Артикул').fill(`A-${stamp}`)
  await form.getByLabel('Цена модели').fill('4900')
  await form.getByRole('button', { name: 'Добавить' }).click()
  const row = page.getByTestId('products').locator(`[data-product="Бюрократ CH-${stamp}"]`)
  await expect(row).toContainText('4 900')
  const products = (await (await page.request.get(`/api/catalog/v1/types/${chair.id}/products`)).json()).items as { id: string; name: string }[]
  const product = products.find(p => p.name === `CH-${stamp}`)!
  await page.goto('/#/catalog')
  await expect(page.getByTestId('types').getByRole('link', { name: /^Кресло посетителя/ })).toContainText(/\d+ модел/)

  try {
    // ---- the editor: the question about the number asks which model, and the object keeps it
    await page.goto('/#/buildings')
    await page.getByRole('button', { name: 'Создать здание' }).click()
    await page.getByLabel('Название').fill(`Модели ${stamp}`)
    await page.getByRole('button', { name: 'Создать', exact: true }).click()
    await page.waitForURL(/#\/p\//)
    const building = /#\/p\/([\w-]+)/.exec(page.url())![1]
    await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
    const drawing = page.locator('[data-drawing="sample.dxf"]')
    await expect(drawing).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
    await drawing.getByRole('link', { name: 'Открыть' }).click()
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
    await page.locator('button').first().click()
    await page.getByText('План 1-го этажа').first().click()
    await page.getByRole('listitem', { name: 'Мебель и оборудование' }).getByRole('button', { name: 'Редактировать слой' }).click()
    await page.getByRole('button', { name: '2D', exact: true }).click()
    await page.waitForTimeout(2500)
    const item = (await page.getByText('Кресло посетителя').first().boundingBox())!
    await page.mouse.move(item.x + 20, item.y + 8)
    await page.mouse.down()
    const [sx, sy] = await screen(page, 8.5, 4)
    await page.mouse.move(sx - 40, sy, { steps: 5 }); await page.mouse.move(sx, sy, { steps: 5 }); await page.mouse.up()
    const ask = page.getByTestId('number-ask')
    await expect(ask).toBeVisible({ timeout: 10_000 })
    await ask.getByLabel('Инвентарный номер').fill(`КР-${stamp}`)
    await ask.getByLabel('Марка и модель').selectOption(product.id)
    await ask.getByRole('button', { name: 'Поставить' }).click()
    await expect(ask).toHaveCount(0)
    const objects = async () => (await (await page.request.get(`/api/assets/v1/assets?building_id=${building}`)).json()).items as { id: string; product_id: string | null; product_name: string }[]
    await expect.poll(async () => (await objects())[0]?.product_name, { timeout: 10_000 }).toBe(`Бюрократ CH-${stamp}`)
    // the inspector names the model; the card shows it with the article and lets the administrator change it
    await expect(page.getByText(`Бюрократ CH-${stamp}`).first()).toBeVisible()
    const [a] = await objects()
    await page.goto(`/#/b/${building}/assets/${a.id}`)
    const card = page.getByTestId('asset-card')
    await expect(card.getByLabel('Марка и модель')).toHaveValue(product.id)
    await expect(card).toContainText(`арт. A-${stamp}`)
    await card.getByLabel('Марка и модель').selectOption('')
    await expect.poll(async () => (await objects())[0]?.product_id, { timeout: 10_000 }).toBeNull()
    await expect(card.getByTestId('asset-history')).toContainText(`Марка и модель: Бюрократ CH-${stamp} → —`)
    // the list of objects finds by the model's name once it is named again
    await card.getByLabel('Марка и модель').selectOption(product.id)
    await expect.poll(async () => (await objects())[0]?.product_id, { timeout: 10_000 }).toBe(product.id)
    await page.goto(`/#/b/${building}/assets`)
    await page.getByLabel('Поиск объекта').fill(`CH-${stamp}`)
    await expect(page.getByTestId('assets').locator('li')).toHaveCount(1)
  } finally {
    await page.request.post(`/api/catalog/v1/products/${product.id}/archive`)
  }
})
