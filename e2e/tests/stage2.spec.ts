import { expect, test, type Browser, type Page } from '@playwright/test'
import { signIn, users } from './helpers'

// Stage 2 (docs/ACCEPTANCE.md, section 4): people and rights by area.

async function as(browser: Browser, who: keyof typeof users): Promise<Page> {
  const page = await (await browser.newContext({ locale: 'ru-RU', viewport: { width: 1280, height: 760 } })).newPage()
  await signIn(page, who)
  return page
}

async function newBuilding(page: Page, name: string, withDrawing: boolean): Promise<string> {
  await page.goto('/#/buildings')
  await page.getByRole('button', { name: 'Создать здание' }).click()
  await page.getByLabel('Название').fill(name)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await page.waitForURL(/#\/p\//)
  const id = /#\/p\/([\w-]+)/.exec(page.url())![1]
  if (withDrawing) {
    await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
    await expect(page.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  }
  return id
}

async function addPerson(page: Page, building: string, name: string, email: string) {
  await page.goto(`/#/b/${building}/people`)
  await page.getByRole('button', { name: 'Добавить' }).click()
  await page.getByLabel('ФИО').fill(name)
  await page.getByLabel(/Почта/).fill(email)
  await page.getByRole('button', { name: 'Добавить', exact: true }).last().click()
  await expect(page.locator(`[data-person="${name}"]`)).toBeVisible()
}

async function give(page: Page, building: string, name: string, role: string, where: RegExp | string) {
  await page.goto(`/#/b/${building}/access`)
  const form = page.getByTestId('grant-form')
  await form.getByLabel('Кому').selectOption({ label: name })
  await form.getByLabel('Что может').selectOption({ label: role })
  const option = form.getByLabel('Где').locator('option').filter({ hasText: where }).first()
  await form.getByLabel('Где').selectOption(await option.getAttribute('value') as string)
  await form.getByRole('button', { name: 'Выдать' }).click()
  await expect(page.locator(`[data-grant="${name}"]`)).toBeVisible()
}

const visible = async (page: Page) =>
  ((await (await page.request.get('/api/buildings/v1/buildings')).json()).items as { id: string }[]).map(b => b.id)

test('rights go from the system administrator to the administrator of a building to a colleague — and back', async ({ browser }) => {
  test.setTimeout(240_000)
  const stamp = Date.now()
  const bossName = `Начальник ${stamp}`, clerkName = `Сотрудник ${stamp}`

  // the system administrator: two buildings, a person, who administers the first one
  const root = await as(browser, 'admin')
  const a = await newBuilding(root, `Корпус А ${stamp}`, true)
  const b = await newBuilding(root, `Корпус Б ${stamp}`, false)
  await addPerson(root, a, bossName, `${users.boss.login}@example.test`)
  await give(root, a, bossName, 'администратор', 'всё здание')

  // that person signs in for the first time: the account finds its person by the e-mail,
  // and the only building opens at once, with what its administrator needs
  const boss = await as(browser, 'boss')
  await expect(boss).toHaveURL(new RegExp(`#/b/${a}`))
  const menu = boss.getByRole('complementary', { name: 'Меню' })
  await expect(menu.getByRole('link', { name: 'Доступ' })).toBeVisible()
  await expect(menu.getByRole('link', { name: 'Состояние системы' })).toHaveCount(0)
  expect(await visible(boss)).toEqual([a])
  // not in the other building, and no buildings of their own
  expect((await boss.request.get(`/api/access/v1/grants?building_id=${b}`)).status()).toBe(404)
  expect((await boss.request.post('/api/buildings/v1/buildings', { data: { name: 'x' } })).status()).toBe(403)
  expect((await boss.request.post('/api/access/v1/grants', { data: {
    person_id: '0192f000-0000-7000-8000-000000000001', role: 'admin', building_id: b, scope: { kind: 'building', id: b } } })).status()).toBe(404)

  // gives a colleague one floor to look at
  await addPerson(boss, a, clerkName, `${users.clerk.login}@example.test`)
  await give(boss, a, clerkName, 'просмотр', /1-го этажа/)

  // the colleague sees the building — its plan, no management — and not the other building, even by its address
  const clerk = await as(browser, 'clerk')
  await expect(clerk).toHaveURL(new RegExp(`#/b/${a}`))
  await expect(clerk.getByTestId('summary')).toBeVisible()
  const clerkMenu = clerk.getByRole('complementary', { name: 'Меню' })
  await expect(clerkMenu.getByRole('link', { name: 'План' })).toBeVisible()
  await expect(clerkMenu.getByRole('link', { name: 'Доступ' })).toHaveCount(0)
  await expect(clerkMenu.getByRole('link', { name: 'Чертежи' })).toHaveCount(0)
  await clerkMenu.getByRole('link', { name: 'План' }).click()
  await expect(clerk.getByTestId('plan')).toBeVisible()
  await clerk.goto(`/#/b/${b}`)
  await expect(clerk.getByText('Здание не найдено')).toBeVisible()
  for (const path of [`/api/buildings/v1/buildings/${b}`, `/api/buildings/v1/buildings/${b}/tree`, `/api/import/v1/drawings?building_id=${b}`]) {
    expect((await clerk.request.get(path)).status(), path).toBe(404)
  }
  expect((await clerk.request.patch(`/api/buildings/v1/buildings/${a}`, { data: { name: 'x', version: 1 } })).status()).toBe(403)
  expect((await clerk.request.get('/api/people/v1/people')).status()).toBe(403)

  // the right is taken away: within 30 seconds the building is gone for the colleague
  await boss.goto(`/#/b/${a}/access`)
  await boss.locator(`[data-grant="${clerkName}"]`).getByRole('button', { name: 'Отозвать' }).click()
  await expect(boss.locator(`[data-grant="${clerkName}"]`)).toHaveCount(0)
  const since = Date.now()
  await expect.poll(() => visible(clerk), { timeout: 40_000, intervals: [2000] }).toEqual([])
  console.log('revoked right gone after', Math.round((Date.now() - since) / 1000), 's')
  expect(Date.now() - since).toBeLessThan(30_000)

  // the administrator of the building leaves: every right is gone, the account opens nothing
  await root.goto(`/#/b/${a}/people`)
  root.once('dialog', d => d.accept())
  await root.locator(`[data-person="${bossName}"]`).getByRole('button', { name: 'Выбыл' }).click()
  await expect(root.locator(`[data-person="${bossName}"]`)).toHaveCount(0)
  await expect.poll(() => visible(boss), { timeout: 40_000, intervals: [2000] }).toEqual([])
  await boss.goto('/#/buildings')
  await expect(boss.getByText('отмечены как выбывший')).toBeVisible()
})

test('an account that is not in the directory of people sees nothing and is told whom to ask', async ({ page }) => {
  await signIn(page, 'user')
  await expect(page.getByText('Зданий пока нет')).toBeVisible()
  await expect(page.getByText('нет в справочнике людей')).toBeVisible()
  const me = await (await page.request.get('/api/me')).json()
  expect(me.person).toBeNull()
  expect(me.reason).toBe('unknown')
  expect(me.scopes.buildings).toEqual([])
})
