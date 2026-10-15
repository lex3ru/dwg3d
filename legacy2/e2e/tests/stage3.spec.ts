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

test('a type is hung on the ceiling in the editor, and a save keeps what the form does not show', async ({ page }) => {
  test.setTimeout(60_000)
  const name = `Светильник ${Date.now().toString().slice(-6)}`
  await signIn(page, 'admin')
  const category = ((await (await page.request.get('/api/catalog/v1/categories')).json()).items as { id: string; name: string }[])
    .find(c => c.name === 'Освещение')!.id
  const made = await page.request.post('/api/catalog/v1/types', { data: { category_id: category, name, w: 0.6, d: 0.6, h: 0.04,
    elevation: 2.7, shape: 'lamp_panel', color: '#fcc419', article: 'LP-600', price: 1000 } })
  expect(made.status(), await made.text()).toBe(201)
  const id = (await made.json()).id as string
  const type = async () => (await (await page.request.get(`/api/catalog/v1/types/${id}`)).json()) as Record<string, unknown>

  await page.goto(`/#/catalog/types/${id}`)
  await expect(page.getByLabel('Монтаж')).toHaveValue('floor')
  await expect(page.getByLabel('Высота установки')).toHaveValue('2.7')
  await page.getByLabel('Монтаж').selectOption({ label: 'на потолке' })
  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByTestId('types').getByRole('link', { name: new RegExp(name) })).toContainText('на потолке')
  // what the form does not show stays: the shape in 3D, the colour, the article, the price, the mounting height
  expect(await type()).toMatchObject({ ceiling_mounted: true, wall_mounted: false, shape: 'lamp_panel', color: '#fcc419',
    article: 'LP-600', price: 1000, elevation: 2.7 })

  // on a wall instead: one or the other; both at once are refused
  await page.goto(`/#/catalog/types/${id}`)
  await page.getByLabel('Монтаж').selectOption({ label: 'на стене' })
  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByTestId('types').getByRole('link', { name: new RegExp(name) })).toContainText('на стене')
  const t = await type()
  expect(t).toMatchObject({ ceiling_mounted: false, wall_mounted: true })
  const { id: _, size, model: _m, active: _a, schema_version: _s, schema: _x, ...rest } = t as Record<string, any>  // eslint-disable-line @typescript-eslint/no-explicit-any
  const both = await page.request.patch(`/api/catalog/v1/types/${id}`, { data: { ...rest, w: size[0], d: size[1], h: size[2],
    ceiling_mounted: true } })
  expect(both.status()).toBe(422)
  await page.request.post(`/api/catalog/v1/types/${id}/archive`)
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
