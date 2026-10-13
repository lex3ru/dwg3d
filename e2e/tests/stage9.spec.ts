import { execSync } from 'node:child_process'
import { resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { signIn } from './helpers'

// Stage 9 (docs/ACCEPTANCE.md, section 11): the copilot. The model is a stand-in (tools/fake-model.py) run as a
// container on the stack's network: it calls the copilot's tools by keywords and answers from their results.

const MODEL = 'twin-fake-model-e2e'
const sh = (cmd: string) => execSync(cmd, { stdio: 'ignore' })

test.beforeAll(() => {
  try { sh(`docker rm -f ${MODEL}`) } catch { /* not running */ }
  const script = resolve(process.cwd(), '../tools/fake-model.py')
  sh(`docker run -d --name ${MODEL} --network twin_default -v ${script}:/fake-model.py:ro python:3.12-alpine python /fake-model.py --port 18089`)
})
test.afterAll(() => { try { sh(`docker rm -f ${MODEL}`) } catch { /* gone */ } })

async function configure(page: Page, enabled: boolean) {
  const r = await page.request.put('/api/copilot/v1/settings', { data: { base_url: `http://${MODEL}:18089/v1`, model: 'fake-model', enabled } })
  expect(r.status(), await r.text()).toBe(200)
}

/** The answer of the copilot to one message, through the API: the text and the tools it used. */
async function askByApi(page: Page, building: string, text: string) {
  const chat = await (await page.request.post('/api/copilot/v1/chats', { data: { building_id: building } })).json() as { id: string }
  const r = await page.request.post(`/api/copilot/v1/chats/${chat.id}/messages`, { data: { text, ui: { building: { id: building, name: 'здание' } } } })
  expect(r.status(), await r.text()).toBe(200)
  const events = (await r.text()).split('\n').filter(l => l.startsWith('data:')).map(l => JSON.parse(l.slice(5)) as { type: string; text?: string; name?: string; error?: string })
  return { text: events.filter(e => e.type === 'text').map(e => e.text).join(''), tools: events.filter(e => e.type === 'tool') }
}

test('the copilot answers from the user\'s data, links into it, remembers the talk and is gone when switched off', async ({ page }) => {
  test.setTimeout(240_000)
  const stamp = Date.now().toString().slice(-7)
  await page.setViewportSize({ width: 1400, height: 850 })
  await signIn(page, 'admin')
  await configure(page, true)

  // a building with a floor and one object
  const created = await page.request.post('/api/buildings/v1/buildings', { data: { name: `Помощник ${stamp}` } })
  expect(created.status(), await created.text()).toBe(201)
  const building = (await created.json() as { id: string }).id
  await page.goto(`/#/b/${building}/drawings`)
  await page.getByTestId('file').setInputFiles('fixtures/sample.dxf')
  await expect(page.locator('[data-drawing="sample.dxf"]')).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
  const floors = (await (await page.request.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors as { id: string; level: number }[]
  const types = (await (await page.request.get('/api/catalog/v1/types?active=true')).json()).items as { id: string; name: string }[]
  const desk = types.find(t => t.name === 'Рабочий стол')!
  const number = `СТ-${stamp}`
  const put = await page.request.post('/api/assets/v1/assets', { data: { type_id: desk.id, floor_id: floors.find(f => f.level === 1)!.id, x: 9, y: 6.5, inventory_no: number } })
  expect(put.status(), await put.text()).toBe(201)

  // the pane: a question, the tool used, the answer with a link that opens the object's card
  await page.goto(`/#/b/${building}`)
  await page.getByTestId('copilot-open').click()
  const pane = page.getByTestId('copilot')
  await expect(pane).toBeVisible()
  await pane.getByLabel('Вопрос помощнику').fill('какие есть объекты?')
  await pane.getByLabel('Вопрос помощнику').press('Enter')
  await expect(pane.getByTestId('copilot-tool')).toContainText('поиск объектов')
  const link = pane.getByRole('link', { name: new RegExp(number) })
  await expect(link).toBeVisible({ timeout: 20_000 })
  await expect(pane.getByTestId('copilot-busy')).toHaveCount(0)
  await link.click()
  await expect(page.getByTestId('panel')).toContainText(number)

  // the talk is kept: after a reload the pane shows it again, and a second question continues it
  await page.reload()
  await expect(page.getByTestId('copilot')).toContainText('какие есть объекты?')
  await expect(page.getByTestId('copilot').getByRole('link', { name: new RegExp(number) })).toBeVisible()
  const chats = (await (await page.request.get(`/api/copilot/v1/chats?building_id=${building}`)).json()).items as { title: string }[]
  expect(chats.length).toBeGreaterThanOrEqual(1)

  // the usage is counted and shown
  const status = await (await page.request.get('/api/copilot/v1/status')).json() as { used_today: number; enabled: boolean }
  expect(status.enabled).toBe(true)
  expect(status.used_today).toBeGreaterThanOrEqual(2)

  // someone with no right to the building gets nothing of it: the services answer them, not the copilot's memory
  const other = await page.context().browser()!.newContext()
  const stranger = await other.newPage()
  await signIn(stranger, 'user')
  const answer = await askByApi(stranger, building, 'какие есть объекты?')
  expect(answer.text).not.toContain(number)
  expect(answer.tools.map(t => t.name)).toContain('find_assets')
  await other.close()

  // switched off, the copilot is not on screen at all; the rest works
  await configure(page, false)
  await page.reload()
  await expect(page.getByTestId('building-name')).toHaveText(`Помощник ${stamp}`)
  await expect(page.getByTestId('copilot-open')).toHaveCount(0)
  await expect(page.getByTestId('copilot')).toHaveCount(0)
})
