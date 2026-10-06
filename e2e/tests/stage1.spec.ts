import { expect, test, type Page } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
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
  const search = page.getByPlaceholder('Помещение или этаж')
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

test('two drawings of a building stand in one scene, each where its placement puts it', async ({ page }) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1400, height: 800 })
  await newBuilding(page, `Два корпуса ${Date.now()}`)
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(drawing(page, 'sample.dxf')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  await page.getByTestId('file').setInputFiles({ name: 'second.dxf', mimeType: 'application/dxf', buffer: readFileSync('fixtures/sample.dxf') })
  const second = drawing(page, 'second.dxf')
  await expect(second).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  await expect(page.getByTestId('totals')).toHaveText('Этажей: 4 · помещений: 8')

  // the second one is moved 20 m to the right and turned
  const form = second.getByTestId('placement')
  await form.getByLabel('Сдвиг X, м').fill('20')
  await form.getByLabel('Поворот, °').fill('30')
  await form.getByRole('button', { name: 'Сохранить' }).click()
  await expect(second.getByTestId('placement').getByLabel('Сдвиг X, м')).toHaveValue('20')
  await page.reload()
  await expect(drawing(page, 'second.dxf').getByTestId('placement').getByLabel('Поворот, °')).toHaveValue('30')

  // the viewer of the first drawing loads both models
  const models = new Set<string>()
  page.on('response', r => { if (r.url().includes('/files/model.glb') && r.ok()) models.add(new URL(r.url()).pathname) })
  await drawing(page, 'sample.dxf').getByRole('link', { name: 'Открыть' }).click()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await expect.poll(() => models.size, { timeout: 20_000 }).toBe(2)
  await page.waitForTimeout(2500)
  await page.screenshot({ path: 'screenshots/two-drawings.png' })
})

test('a marker put on a floor is there after a reload', async ({ page }) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1400, height: 800 })
  await newBuilding(page, `Метка ${Date.now()}`)
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(drawing(page, 'sample.dxf')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  await drawing(page, 'sample.dxf').getByRole('link', { name: 'Открыть' }).click()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(3000)

  await page.getByRole('button', { name: 'Метка' }).click()
  await page.mouse.click(700, 450)
  await page.getByPlaceholder('Подпись').fill('Щиток')
  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByPlaceholder('Подпись')).toHaveCount(0)
  await page.waitForTimeout(1000)
  await page.reload()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  // markers inside a floor show when the floor is open: go through the floors
  let seen = 0
  for (const floor of ['c0', 'c1']) {
    await page.goto(page.url().replace(/\/(all|floor_\w+)\/3d.*/, `/floor_${floor}/3d`))
    await page.waitForTimeout(2500)
    seen += await page.getByText('Щиток').count()
  }
  expect(seen).toBeGreaterThan(0)
})

test('a room named in the 2D editor is rebuilt into the building, other rooms keep their ids', async ({ page }) => {
  test.setTimeout(150_000)
  await page.setViewportSize({ width: 1400, height: 800 })
  await newBuilding(page, `Редактор ${Date.now()}`)
  await page.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(page.url())![1]
  const rooms = async () => (await (await page.request.get(`/api/buildings/v1/rooms?building_id=${building}`)).json()).items as
    { id: string; name: string; area: number; floor_id: string }[]
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(drawing(page, 'sample.dxf')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const before = await rooms()
  expect(before.map(r => r.name).sort()).toEqual(['', '', 'Кабинет', 'Кабинет'])

  await drawing(page, 'sample.dxf').getByRole('link', { name: 'Открыть' }).click()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(2500)
  await page.locator('button').first().click()                                   // the tree
  await page.locator('button:has(svg.lucide-pencil-ruler)').first().click({ force: true })   // the plan editor of the top floor
  await expect(page.getByRole('button', { name: 'Применить' })).toBeVisible()

  await page.mouse.click(300, 300)                                               // the room without a name
  await page.getByPlaceholder('Название помещения').fill('Процедурная')
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: 'Применить' }).click()

  // the drawing is rebuilt and the building takes the build in
  await expect.poll(async () => (await rooms()).map(r => r.name).sort(), { timeout: 60_000 })
    .toEqual(['', 'Кабинет', 'Кабинет', 'Процедурная'])
  const after = await rooms()
  const named = after.find(r => r.name === 'Процедурная')!
  expect(before.find(r => r.id === named.id)?.name).toBe('')                       // the same room, now with a name
  expect(after.map(r => r.id).sort()).toEqual(before.map(r => r.id).sort())       // nobody got a new id
  await expect(page.getByText('Процедурная').first()).toBeVisible({ timeout: 20_000 })   // and the viewer shows it
})

test('the tools of the viewer work on the new services: display, measuring, walking, the map, the facade', async ({ page }) => {
  test.setTimeout(150_000)
  const failed: string[] = []
  page.on('pageerror', e => failed.push(String(e)))
  page.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/api/me')) failed.push(`${r.status()} ${r.request().method()} ${r.url()}`) })
  await page.setViewportSize({ width: 1400, height: 800 })
  await newBuilding(page, `Инструменты ${Date.now()}`)
  await page.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(page.url())![1]
  const get = async (path: string) => (await page.request.get(`/api/buildings/v1/buildings/${building}${path}`)).json()
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(drawing(page, 'sample.dxf')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  await drawing(page, 'sample.dxf').getByRole('link', { name: 'Открыть' }).click()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(3000)

  // display: floors apart, transparent walls — and the address remembers the view
  await page.getByRole('button', { name: 'Отображение' }).click()
  await page.getByText('Разнести этажи').click()
  await page.getByText('Прозрачные стены').click()
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/e=1/)
  await expect(page).toHaveURL(/x=1/)
  await page.mouse.click(1000, 620)

  // the ruler: two points on the building give a distance
  await page.getByRole('button', { name: 'Расстояние' }).click()
  await page.mouse.click(620, 420)
  await page.mouse.click(820, 440)
  await expect(page.getByText(/\d+[.,]\d+\s*м/).first()).toBeVisible()
  await page.keyboard.press('Escape')

  // navigation modes: orbit -> fly -> walk -> orbit (walking takes the pointer: click the button itself)
  const next = (icon: string) => page.locator(`button:has(svg.lucide-${icon})`).last().dispatchEvent('click')
  await next('orbit')
  await expect(page.getByText('Полёт · 3D')).toBeVisible()
  await next('plane')
  await expect(page.getByText('Прогулка · 3D')).toBeVisible()
  await next('footprints')
  await expect(page.getByText('Обзор · 3D')).toBeVisible()

  await page.locator('button:has(svg.lucide-sun)').first().click()              // time of day

  // the name of the drawing, the map, the detailed facade model
  await page.locator('button:has(svg.lucide-settings)').first().click()
  await page.getByRole('menuitem', { name: /Карта и детальная модель/ }).click()
  await page.getByPlaceholder('как в списке зданий').fill('Корпус Б')
  await page.getByPlaceholder('55.7539').fill('55.7539')
  await page.getByPlaceholder('37.6208').fill('37.6208')
  await page.locator('input[type="file"]').last().setInputFiles('fixtures/facade.glb')
  await page.waitForTimeout(1500)
  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect.poll(async () => (await get('')).site?.lat, { timeout: 10_000 }).toBe(55.7539)
  expect((await get('')).facade).toMatchObject({ name: 'facade.glb', scale: 1 })
  await expect.poll(async () => (await get('/drawings')).items[0].name).toBe('Корпус Б')
  await page.waitForTimeout(2000)                                                // the map and the facade load

  // the files of the build: IFC, OBJ, the model itself
  const build = (await get('/drawings')).items[0].build_id
  for (const file of ['model.ifc', 'model_obj.zip', 'model.glb']) {
    expect((await page.request.get(`/api/import/v1/builds/${build}/files/${file}`)).status(), file).toBe(200)
  }
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
  await row.getByLabel('Удалить чертёж', { exact: true }).click()
  await expect(row).toHaveCount(0)
})

test('someone with no rights sees no buildings and cannot make one', async ({ page }) => {
  await signIn(page, 'user')
  expect((await (await page.request.get('/api/buildings/v1/buildings')).json()).items).toEqual([])
  expect((await page.request.post('/api/buildings/v1/buildings', { data: { name: 'x' } })).status()).toBe(403)
  const nowhere = '0192f000-0000-7000-8000-000000000001'
  for (const path of [`/api/buildings/v1/buildings/${nowhere}`, `/api/import/v1/drawings?building_id=${nowhere}`]) {
    expect((await page.request.get(path)).status(), path).toBe(404)
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

  // how long a large drawing takes to open (criterion: a floor of 200 rooms within 3 s)
  const started = Date.now()
  const model = page.waitForResponse(r => r.url().includes('/files/model.glb') && r.ok())
  await drawing(page, REAL[0].split('/').pop()!).getByRole('link', { name: 'Открыть' }).click()
  await (await model).finished()
  await expect(page.locator('canvas').first()).toBeVisible()
  console.log('real drawing opened in', Date.now() - started, 'ms')
})
