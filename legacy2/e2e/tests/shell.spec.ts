import { expect, test, type Page } from '@playwright/test'
import { signIn } from './helpers'

// The frame of the interface (docs/TZ.md, section 6): the menu, where one is, the card
// on the right, tabs on a phone — on a building made from fixtures/sample.dxf.

async function building(page: Page, name: string): Promise<string> {
  await signIn(page, 'admin')
  await page.getByRole('button', { name: 'Создать здание' }).click()
  await page.getByLabel('Название').fill(name)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await page.waitForURL(/#\/p\//)
  const id = /#\/p\/([\w-]+)/.exec(page.url())![1]
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(page.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  return id
}

test('the menu leads through a building: home, rooms with a card, the plan, the editor and back', async ({ page }) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1280, height: 760 })
  const name = `Каркас ${Date.now()}`
  const id = await building(page, name)
  const menu = page.getByRole('complementary', { name: 'Меню' })
  await expect(menu.getByTestId('building-name')).toHaveText(name)

  // «Обзор»: the building at a glance and, for its administrator, what waits for them
  await menu.getByRole('link', { name: 'Обзор' }).click()
  await expect(page.getByTestId('tasks')).toContainText('Всё в порядке')
  // a short guide: what the program is for and where its functions are, with the administrator's order of work
  const howto = page.getByTestId('howto')
  await expect(howto).toContainText('Цифровой двойник здания')
  await expect(howto).toContainText('Администратору здания: порядок работы')
  await expect(howto.getByRole('link', { name: '«Чертежи»' })).toHaveAttribute('href', `#/b/${id}/drawings`)
  await expect(page.getByTestId('summary')).toContainText('Этажи')
  await expect(page.getByTestId('summary').getByRole('link').first()).toContainText('2')
  await expect(page.getByTestId('summary').getByRole('link').nth(1)).toContainText('4')

  // the rooms: «План» shows them on the drawing or as a list with a search, a card on the right
  await menu.getByRole('link', { name: 'План' }).click()
  await page.getByTestId('plan-views').getByRole('link', { name: 'Список' }).click()
  await expect(page.getByTestId('rooms-total')).toHaveText('4')
  await page.getByLabel('Поиск помещения').fill('каб')
  await expect(page.getByTestId('rooms-total')).toHaveText('2')
  await page.getByTestId('rooms').getByRole('link', { name: /Кабинет/ }).first().click()
  const card = page.getByTestId('panel').getByTestId('room-card')
  await expect(card.getByRole('heading', { name: 'Кабинет' })).toBeVisible()
  await expect(card).toContainText('48,69 м²')
  await expect(page.getByTestId('crumbs')).toContainText('План')
  await expect(page).toHaveURL(new RegExp(`#/b/${id}/rooms/[\\w-]+`))
  await page.screenshot({ path: 'screenshots/shell-rooms.png' })

  // the administrator names the room right in the card
  await card.getByLabel('Переименовать', { exact: true }).click()
  await card.getByLabel('Название помещения').fill('Ординаторская')
  await card.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByTestId('panel').getByRole('heading', { name: 'Ординаторская' })).toBeVisible()
  await page.getByLabel('Поиск помещения').fill('')
  await expect(page.getByTestId('rooms').first()).toContainText('Ординаторская')

  // from the card to the plan: the room is highlighted there, the card stays beside it
  await page.getByTestId('panel').getByRole('link', { name: 'Показать на плане' }).click()
  await expect(page.getByTestId('plan').locator('[data-selected]')).toHaveCount(1)
  await expect(page.getByTestId('panel').getByRole('heading', { name: 'Ординаторская' })).toBeVisible()
  await expect(page.getByTestId('plan')).toContainText('Ординаторская')          // the plan shows the new name too
  await page.screenshot({ path: 'screenshots/shell-plan.png' })
  // another floor, another room by a click on the plan
  await page.getByTestId('floor-tabs').getByRole('link', { name: '1', exact: true }).click()
  await expect(page.getByTestId('plan').locator('[data-selected]')).toHaveCount(0)
  await page.getByTestId('plan').locator('[data-room]').first().click()
  await expect(page.getByTestId('panel').getByTestId('room-card')).toBeVisible()
  await page.getByTestId('panel').getByLabel('Закрыть', { exact: true }).click()
  await expect(page.getByTestId('panel')).toHaveCount(0)

  // the editor is a section too: the menu folds to icons and still leads back
  await menu.getByRole('link', { name: 'Редактор' }).click()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await menu.getByLabel('План', { exact: true }).click()
  await expect(page.getByTestId('floor-tabs')).toBeVisible()
  await page.goBack()
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
})

test('on a phone: tabs at the bottom, the card as a page, nothing wider than the screen', async ({ page }) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1280, height: 760 })
  const id = await building(page, `Телефон ${Date.now()}`)
  await page.setViewportSize({ width: 360, height: 740 })
  const fits = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)

  await page.goto(`/#/b/${id}`)
  const tabs = page.getByRole('navigation', { name: 'Вкладки' })
  await expect(tabs).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'Меню' })).toBeHidden()
  await fits()

  await tabs.getByRole('link', { name: 'План' }).click()
  await page.getByTestId('plan-views').getByRole('link', { name: 'Список' }).click()
  await page.getByTestId('rooms').getByRole('link', { name: /Кабинет/ }).first().click()
  await expect(page.getByTestId('room-card')).toBeVisible()            // the card took the place of the list
  await expect(page.getByLabel('Поиск помещения')).toBeHidden()
  await fits()
  await page.screenshot({ path: 'screenshots/shell-phone-card.png' })

  await page.getByRole('link', { name: 'Показать на плане' }).click()
  await expect(page.getByTestId('plan')).toBeVisible()                 // the plan stays; what is chosen is a strip under it
  await expect(page.getByTestId('plan').locator('[data-selected]')).toHaveCount(1)
  await fits()
  await page.screenshot({ path: 'screenshots/shell-phone-plan.png' })

  await tabs.getByRole('link', { name: 'Я', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Чертежи здания' })).toBeVisible()
  await expect(page.getByRole('main').getByRole('button', { name: 'Выйти' })).toBeVisible()
  await fits()
})
