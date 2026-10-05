import { expect, test } from '@playwright/test'
import { signIn } from './helpers'

// Stage 3 (docs/ACCEPTANCE.md, section 5): the catalog.

test('the catalog starts with the agreed sections, sets and types', async ({ page }) => {
  await signIn(page, 'admin')
  await page.getByRole('complementary', { name: 'Меню' }).getByRole('link', { name: 'Каталог' }).click()
  for (const name of ['Аппарат КТ', 'Гастроскоп', 'Рабочий стол', 'Кушетка', 'Кресло посетителя']) {
    await expect(page.getByTestId('types').getByRole('link', { name: new RegExp(`^${name}`) }).first()).toBeVisible()
  }
  for (const name of ['Учёт', 'Медицинское изделие', 'Мебель']) {
    await expect(page.getByTestId('sets').getByText(name, { exact: true })).toBeVisible()
  }
})

test('the system administrator makes a property set and a type with it, gives it a model, archives it', async ({ page }) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1280, height: 900 })
  const stamp = Date.now().toString().slice(-6)
  const setName = `Стерилизация ${stamp}`, typeName = `Эндоскоп ${stamp}`
  await signIn(page, 'admin')

  // a property set
  await page.goto('/#/catalog/sets/new')
  await page.getByLabel('Название набора').fill(setName)
  await page.getByRole('button', { name: 'Свойство' }).click()
  const first = page.getByTestId('properties').locator('> div').first()
  await first.getByLabel('Название свойства').fill('Дата стерилизации')
  await first.getByLabel('Ключ свойства').fill('sterilized')
  await first.getByLabel('Вид значения').selectOption({ label: 'дата' })
  await first.getByLabel('Кто правит').selectOption({ label: 'ответственный' })
  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByTestId('sets').getByText(setName)).toBeVisible()

  // a type: portable, with that set and «Медицинское изделие», and a property of its own kept with the type
  await page.goto('/#/catalog/types/new')
  await page.getByLabel('Название типа').fill(typeName)
  await page.getByLabel('Раздел', { exact: true }).selectOption({ label: 'Медицинская техника' })
  await page.getByLabel('Переносной').check()
  await page.getByTestId('type-sets').getByLabel(new RegExp(setName)).check()
  await page.getByTestId('type-sets').getByLabel(/Медицинское изделие/).check()
  await page.getByRole('button', { name: 'Свойство' }).click()
  const own = page.getByTestId('properties').locator('> div').first()
  await own.getByLabel('Название свойства').fill('Число каналов')
  await own.getByLabel('Вид значения').selectOption({ label: 'число' })
  await own.getByLabel('Где хранится').selectOption({ label: 'одно на тип' })

  // a key one of the sets already has is refused, with the reason
  await own.getByLabel('Ключ свойства').fill('manufacturer')
  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByRole('alert')).toContainText('встречается дважды')
  await own.getByLabel('Ключ свойства').fill('channels')
  await page.getByTestId('type-values').getByLabel('Число каналов').fill('2')
  await page.getByRole('button', { name: 'Сохранить' }).click()
  const row = page.getByTestId('types').getByRole('link', { name: new RegExp(typeName) })
  await expect(row).toContainText('переносной')

  // its schema: the sets in the order chosen, then its own property
  const types = (await (await page.request.get('/api/catalog/v1/types')).json()).items as { id: string; name: string }[]
  const id = types.find(t => t.name === typeName)!.id
  const schema = await (await page.request.get(`/api/catalog/v1/types/${id}/schema`)).json()
  expect(schema.portable).toBe(true)
  const keys = schema.properties.map((p: { key: string }) => p.key)
  expect([keys[0], keys[1], keys.at(-1)]).toEqual(['sterilized', 'manufacturer', 'channels'])

  // a model: far larger than the type — accepted, with a warning — and shown
  await row.click()
  await page.getByTestId('model-file').setInputFiles('fixtures/facade.glb')
  await expect(page.getByRole('status')).toContainText('больше чем вдвое')
  await expect(page.getByTestId('model-preview').locator('canvas')).toBeVisible({ timeout: 20_000 })
  await page.screenshot({ path: 'screenshots/catalog-type.png', fullPage: true })

  // archived: not offered, still opens by its address
  await page.getByRole('button', { name: 'В архив' }).click()
  await expect(page.getByTestId('types').first()).toBeVisible()
  await expect(page.getByTestId('types').getByRole('link', { name: new RegExp(typeName) })).toHaveCount(0)
  await page.getByLabel('архив').check()
  await expect(page.getByTestId('types').getByRole('link', { name: new RegExp(typeName) })).toBeVisible()
  await page.goto(`/#/catalog/types/${id}`)
  await expect(page.getByText('в архиве')).toBeVisible()
})

test('others read the catalog and do not change it', async ({ page }) => {
  await signIn(page, 'user')
  await expect(page.getByRole('link', { name: 'Каталог' })).toHaveCount(0)
  const types = await page.request.get('/api/catalog/v1/types')
  expect(types.status()).toBe(200)
  const one = (await types.json()).items[0].id
  expect((await page.request.post(`/api/catalog/v1/types/${one}/archive`)).status()).toBe(403)
  expect((await page.request.post('/api/catalog/v1/property-sets', { data: { name: 'x' } })).status()).toBe(403)
})
