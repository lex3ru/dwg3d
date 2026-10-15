import { expect, test, type Browser, type Page } from '@playwright/test'
import { signIn, users } from './helpers'
import { xlsx } from './xlsx'

// Stage 4 (docs/ACCEPTANCE.md, section 6): objects on the plan.

async function as(browser: Browser, who: keyof typeof users): Promise<Page> {
  const page = await (await browser.newContext({ locale: 'ru-RU', viewport: { width: 1360, height: 860 } })).newPage()
  await signIn(page, who)
  return page
}

test('an object is placed, filled in, given to someone who then keeps it — and every change is in its history', async ({ browser }) => {
  test.setTimeout(240_000)
  const stamp = Date.now().toString().slice(-7)
  const keeper = `Хранитель ${stamp}`, number = `Э-${stamp}`

  // the administrator: a building from a drawing, a person of the directory
  const root = await as(browser, 'admin')
  await root.getByRole('button', { name: 'Создать здание' }).click()
  await root.getByLabel('Название').fill(`Объекты ${stamp}`)
  await root.getByRole('button', { name: 'Создать', exact: true }).click()
  await root.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(root.url())![1]
  await root.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(root.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  await root.goto(`/#/b/${building}/people`)
  await root.getByRole('button', { name: 'Добавить' }).click()
  await root.getByLabel('ФИО').fill(keeper)
  await root.getByLabel(/Почта/).fill(`${users.keeper.login}@example.test`)
  await root.getByRole('button', { name: 'Добавить', exact: true }).last().click()
  await expect(root.locator(`[data-person="${keeper}"]`)).toBeVisible()

  // an object is put on the plan: a type of the catalog, a number, a click — its room is found by the point
  await root.goto(`/#/b/${building}/plan`)
  await root.getByRole('button', { name: 'Поставить объект' }).click()
  await root.getByTestId('placing').getByLabel('Тип объекта').selectOption({ label: 'Гастроскоп' })
  await root.getByTestId('placing').getByLabel('Инвентарный номер').fill(number)
  const plan = await root.getByTestId('plan').boundingBox()
  await root.mouse.click(plan!.x + plan!.width * 0.7, plan!.y + plan!.height * 0.5)
  const card = root.getByTestId('panel').getByTestId('asset-card')
  await expect(card.getByRole('heading', { name: 'Гастроскоп' })).toBeVisible()
  await expect(card).toContainText(number)
  await expect(card).toContainText('Кабинет')                               // the room the point is in

  // outside the building nothing is placed
  await root.goto(`/#/b/${building}/plan`)
  await root.getByRole('button', { name: 'Поставить объект' }).click()
  await root.getByTestId('placing').getByLabel('Тип объекта').selectOption({ label: 'Кушетка' })
  await root.getByTestId('placing').getByLabel('Инвентарный номер').fill(`К-${stamp}`)
  const box = await root.getByTestId('plan').boundingBox()
  await root.mouse.click(box!.x + 3, box!.y + 3)
  await expect(root.getByRole('alert')).toContainText('не попадает ни в одно помещение')

  // the administrator fills in what is theirs, attaches a photo and a document, names who answers
  await root.goto(`/#/b/${building}/assets`)
  await root.getByTestId('assets').locator(`[data-asset="${number}"]`).click()
  await card.getByLabel('Год выпуска').fill('2021')
  await card.getByLabel('Год выпуска').blur()
  await root.getByTestId('asset-file').setInputFiles('fixtures/photo.png')
  await expect(card.getByTestId('asset-files').getByRole('img')).toBeVisible()
  await root.getByTestId('asset-file').setInputFiles({ name: 'Паспорт.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4') })
  await expect(card.getByTestId('asset-files')).toContainText('Паспорт.pdf')
  await card.getByLabel('Ответственный').selectOption({ label: keeper })
  await expect(card.getByTestId('asset-history')).toContainText('ответственный')

  // that person signs in: the building opens, the object is theirs to keep
  const clerk = await as(browser, 'keeper')
  await expect(clerk).toHaveURL(new RegExp(`#/b/${building}`), { timeout: 20_000 })
  await clerk.getByRole('complementary', { name: 'Меню' }).getByRole('link', { name: 'Объекты', exact: true }).click()
  await clerk.getByTestId('assets').locator(`[data-asset="${number}"]`).click()
  const mine = clerk.getByTestId('panel').getByTestId('asset-card')
  await expect(mine.getByLabel('Год выпуска')).toHaveCount(0)               // the administrator's: text, not a field
  await expect(mine).toContainText('2021')
  await mine.getByLabel('Дата следующего ТО').fill('2026-12-01')
  await mine.getByLabel('Дата следующего ТО').blur()
  await expect(mine.getByTestId('asset-history')).toContainText('Дата следующего ТО: — → 2026-12-01')
  await mine.getByLabel('Состояние объекта').selectOption({ label: 'неисправен' })
  await expect(mine.getByTestId('asset-history')).toContainText('Состояние: в работе → неисправен')
  // and they cannot do the administrator's part
  const asset = /assets\/([\w-]+)/.exec(clerk.url())![1]
  const now = await (await clerk.request.get(`/api/assets/v1/assets/${asset}`)).json()
  const refused = await clerk.request.patch(`/api/assets/v1/assets/${asset}`, { data: { props: { made: 1999 }, version: now.version } })
  expect(refused.status()).toBe(403)
  expect((await refused.json()).detail).toContain('Год выпуска')

  // the administrator sees it at once, without reloading: in the list and in the card, with the author
  await expect(root.getByTestId('assets').locator(`[data-asset="${number}"]`)).toContainText('неисправен', { timeout: 5000 })
  await expect(card.getByTestId('asset-history')).toContainText(keeper)
  // takes the date back
  const entry = card.getByTestId('asset-history').locator('li').filter({ hasText: 'Дата следующего ТО: — → 2026-12-01' })
  await entry.getByRole('button', { name: 'Откатить' }).click()
  await expect(card.getByTestId('asset-history').locator('li').first()).toContainText('откат')
  await expect(card.getByLabel('Дата следующего ТО')).toHaveValue('')
  await root.screenshot({ path: 'screenshots/asset-card.png' })

  // on the plan the object is drawn in its room
  await card.getByRole('link', { name: 'На плане' }).click()
  await expect(root.getByTestId('plan').locator(`[data-asset="${asset}"]`)).toBeVisible()
})

test('objects are placed in a row and loaded from a file; one is put inside another and taken out to a new place', async ({ browser }) => {
  test.setTimeout(240_000)
  const stamp = Date.now().toString().slice(-7)
  const root = await as(browser, 'admin')
  await root.getByRole('button', { name: 'Создать здание' }).click()
  await root.getByLabel('Название').fill(`Расстановка ${stamp}`)
  await root.getByRole('button', { name: 'Создать', exact: true }).click()
  await root.waitForURL(/#\/p\//)
  const building = /#\/p\/([\w-]+)/.exec(root.url())![1]
  await root.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(root.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const at = async (fx: number, fy: number) => {
    const box = (await root.getByTestId('plan').boundingBox())!
    await root.mouse.click(box.x + box.width * fx, box.y + box.height * fy)
  }

  // three couches at once: the places are clicked, the numbers go in a row
  await root.goto(`/#/b/${building}/plan`)
  await root.getByRole('button', { name: 'Поставить несколько' }).click()
  const series = root.getByTestId('series')
  await series.getByLabel('Тип объектов').selectOption({ label: 'Кушетка' })
  await series.getByLabel('Начало номера').fill(`КШ-${stamp}-`)
  await series.getByLabel('Цифр').fill('3')
  await at(0.68, 0.48); await at(0.72, 0.48); await at(0.7, 0.53); await at(0.74, 0.53)
  await series.getByRole('button', { name: 'Убрать последнюю' }).click()
  await expect(root.getByTestId('series-numbers')).toHaveText(`отмечено 3: КШ-${stamp}-001 … КШ-${stamp}-003`)
  await series.getByRole('button', { name: 'Поставить 3' }).click()
  await expect(series).toHaveCount(0)
  await expect(root.getByTestId('plan').locator('[data-asset]')).toHaveCount(3)

  // a desk and a gastroscope; the card of the gastroscope shows what the catalog says of every such one
  for (const [type, number] of [['Рабочий стол', `СТ-${stamp}`], ['Гастроскоп', `ГС-${stamp}`]]) {
    await root.goto(`/#/b/${building}/plan`)
    await root.getByRole('button', { name: 'Поставить объект' }).click()
    await root.getByTestId('placing').getByLabel('Тип объекта').selectOption({ label: type })
    await root.getByTestId('placing').getByLabel('Инвентарный номер').fill(number)
    await at(0.7, 0.44)
    await expect(root.getByTestId('panel').getByTestId('asset-card')).toContainText(number)
  }
  const card = root.getByTestId('panel').getByTestId('asset-card')
  await expect(card).toContainText('Вид')
  await expect(card).toContainText('видео')

  // it is put into the desk: no place of its own any more; then taken out — to where the plan is clicked
  await card.getByLabel('Поставить внутрь').selectOption({ label: `Рабочий стол · СТ-${stamp}` })
  await expect(card).toContainText('Стоит внутри: Рабочий стол')
  await expect(card.getByRole('link', { name: 'На плане' })).toHaveCount(0)
  const asset = /assets\/([\w-]+)/.exec(root.url())![1]
  await card.getByRole('link', { name: 'Переместить' }).click()
  await expect(root.getByTestId('moving')).toContainText(`ГС-${stamp}`)
  await at(0.66, 0.56)
  await expect(card).toContainText(`ГС-${stamp}`)
  await expect(card).not.toContainText('Стоит внутри')
  await expect(card.getByTestId('asset-history')).toContainText('перемещ')
  const moved = await (await root.request.get(`/api/assets/v1/assets/${asset}`)).json()
  expect(moved.container_id).toBeNull()
  expect(moved.x).not.toBeNull()

  // from Excel: a file with a mistake loads nothing and names the row; a correct one loads all
  await root.goto(`/#/b/${building}/assets`)
  await expect(root.getByTestId('assets-total')).toHaveText('5')
  const head = ['Тип', 'Инвентарный номер', 'Серийный номер', 'Этаж', 'X', 'Y', 'Примечание']
  const row = (type: string, n: string, dx: number) => [type, n, `SN-${n}`, 1, moved.x + dx, moved.y, 'из файла']
  await root.getByTestId('assets-file').setInputFiles({ name: 'objects.xlsx', mimeType: 'application/octet-stream',
    buffer: xlsx([head, row('Кушетка', `Ф-${stamp}-1`, 0.1), row('Нет такого', `Ф-${stamp}-2`, 0.2)]) })
  await expect(root.getByTestId('assets-report')).toContainText('строка 3')
  await expect(root.getByTestId('assets-report')).toContainText('Нет такого')
  await expect(root.getByTestId('assets-total')).toHaveText('5')
  await root.getByTestId('assets-file').setInputFiles({ name: 'objects.xlsx', mimeType: 'application/octet-stream',
    buffer: xlsx([head, row('Кушетка', `Ф-${stamp}-1`, 0.1), row('Гастроскоп', `Ф-${stamp}-2`, 0.2)]) })
  await expect(root.getByTestId('assets-report')).toHaveText('Добавлено объектов: 2')
  await expect(root.getByTestId('assets-total')).toHaveText('7')
  await expect(root.getByTestId('assets').locator(`[data-asset="Ф-${stamp}-2"]`)).toBeVisible()
})
