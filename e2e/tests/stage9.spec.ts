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
  // the stand's own model settings come back at the end: the scenario borrows them, it does not own them
  const previous = await (await page.request.get('/api/copilot/v1/settings')).json() as Record<string, unknown>
  const restore = async () => {
    const { base_url, model, enabled, daily_limit, max_steps, temperature } = previous
    await page.request.put('/api/copilot/v1/settings', { data: { base_url, model, daily_limit, max_steps, temperature, enabled: false } })
    if (enabled && base_url && model) await page.request.put('/api/copilot/v1/settings', { data: { enabled: true } })
  }
  try {
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

  // a change is a proposal: the administrator sees what will be done and applies it with their own hand
  const tree = (await (await page.request.get(`/api/buildings/v1/buildings/${building}/tree`)).json()).floors as { rooms: { id: string; version: number }[] }[]
  const target = tree.flatMap(f => f.rooms)[0]
  const named = await page.request.patch(`/api/buildings/v1/rooms/${target.id}`, { data: { name: `Переговорная ${stamp}`, version: target.version } })
  expect(named.status(), await named.text()).toBe(200)
  await page.goto(`/#/b/${building}`)
  const pane2 = page.getByTestId('copilot')
  await pane2.getByLabel('Вопрос помощнику').fill(`переименуй помещение Переговорная ${stamp} в «Приёмная»`)
  await pane2.getByLabel('Вопрос помощнику').press('Enter')
  const card = pane2.getByTestId('copilot-proposal')
  await expect(card).toHaveAttribute('data-status', 'open', { timeout: 20_000 })
  await expect(card).toContainText('Приёмная')
  const rooms = async () => (await (await page.request.get(`/api/buildings/v1/rooms?building_id=${building}&q=Приёмная`)).json()).items as unknown[]
  expect(await rooms()).toHaveLength(0)
  await card.getByRole('button', { name: 'Применить' }).click()
  await expect(card).toHaveAttribute('data-status', 'applied')
  expect(await rooms()).toHaveLength(1)
  // the journal names the person, not the copilot
  const journal = (await (await page.request.get(`/api/journal/v1/events?building_id=${building}&type=buildings.room.changed`)).json()).items as { actor: { id: string } }[]
  expect(journal.length).toBeGreaterThanOrEqual(1)
  expect(journal[0].actor.id).not.toContain('copilot')

  // detectors by area: the copilot makes a variant of the places, opened from its card
  await page.goto(`/#/b/${building}/plan/${floors.find(f => f.level === 1)!.id}`)
  const pane4 = page.getByTestId('copilot')
  await pane4.getByLabel('Вопрос помощнику').fill('поставь извещатели на этаже')
  await pane4.getByLabel('Вопрос помощнику').press('Enter')
  const detectorsCard = pane4.getByTestId('copilot-proposal').last()
  await expect(detectorsCard).toHaveAttribute('data-status', 'open', { timeout: 20_000 })
  await expect(detectorsCard).toContainText('Извещатель')
  // shown on the plan as green marks before anything is done
  await detectorsCard.getByTestId('copilot-show-plan').click()
  await expect(page.getByTestId('plan-proposal')).toBeVisible()
  await expect(page.getByTestId('plan-mark').first()).toBeVisible()
  const detectorsBefore = (await (await page.request.get(`/api/assets/v1/assets?building_id=${building}&q=Извещатель`)).json()).total as number
  expect(detectorsBefore).toBe(0)
  await detectorsCard.getByRole('button', { name: 'Применить' }).click()
  await expect(detectorsCard).toHaveAttribute('data-status', 'applied')
  await expect.poll(async () => (await (await page.request.get(`/api/assets/v1/assets?building_id=${building}&q=Извещатель`)).json()).total as number).toBeGreaterThan(0)

  // a drawn plan with mistakes: the copilot proposes the repair, the open editor takes it — with undo — and saves
  const made = await page.request.post('/api/import/v1/sketches', { data: { building_id: building, name: 'План с ошибками' } })
  expect(made.status(), await made.text()).toBe(201)
  const sketchId = (await made.json() as { id: string }).id
  const wall = (a: string, b: string, t = 0.25, kind = 'bearing') => ({ a, b, thickness: t, height: null, kind })
  const broken = { version: 1, floors: [{ id: 'f1', name: 'Этаж 1', level: 1, elevation: 0, height: 2.7,
    nodes: { a: [0, 0], e: [2, 0], b: [4, 0], c: [4, 3], f: [2, 3], d: [0, 3], s1: [1, 1], s2: [1, 1.003] },
    walls: { w1: wall('a', 'e'), w2: wall('e', 'b'), w3: wall('b', 'c'), w4: wall('c', 'f'), w5: wall('f', 'd'), w6: wall('d', 'a'),
      p: wall('e', 'f', 0.1, 'partition'), short: wall('s1', 's2', 0.1, 'partition'), twin: wall('a', 'e') },
    openings: {}, rooms: { r1: { at: [1, 1.5], name: 'Кухня', number: '101', type: null } } }] }
  const v0 = (await (await page.request.get(`/api/import/v1/drawings/${sketchId}/sketch`)).json() as { version: number }).version
  const saved = await page.request.put(`/api/import/v1/drawings/${sketchId}/sketch`, { data: { sketch: broken, version: v0 } })
  expect(saved.status(), await saved.text()).toBe(200)
  await page.goto(`/#/sketch/${sketchId}`)
  await expect(page.getByText('Две стены между одними и теми же точками')).toBeVisible()
  const pane3 = page.getByTestId('copilot')
  await pane3.getByLabel('Вопрос помощнику').fill('проверь план и исправь ошибки')
  await pane3.getByLabel('Вопрос помощнику').press('Enter')
  const fix = pane3.getByTestId('copilot-proposal').last()
  await expect(fix).toHaveAttribute('data-status', 'open', { timeout: 20_000 })
  await expect(fix).toContainText('twin')
  await fix.getByRole('button', { name: 'Применить' }).click()
  await expect(fix).toHaveAttribute('data-status', 'applied')
  // the plan in the editor is repaired, the step can be undone, and the repaired plan is what got saved
  await expect(page.getByText('Две стены между одними и теми же точками')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Отменить' })).toBeEnabled()
  await expect.poll(async () => {
    const s = await (await page.request.get(`/api/import/v1/drawings/${sketchId}/sketch`)).json() as { sketch: { floors: { walls: Record<string, unknown> }[] }; version: number }
    return [s.version, Object.keys(s.sketch.floors[0].walls).sort().join()]
  }, { timeout: 10_000 }).toEqual([v0 + 2, 'p,w1,w2,w3,w4,w5,w6'])

  // a plan from a few words: a new drawn plan of the building, proposed, applied and opened in the editor
  await page.goto(`/#/b/${building}`)
  const pane5 = page.getByTestId('copilot')
  await pane5.getByLabel('Вопрос помощнику').fill('нарисуй коридор с 6 кабинетами')
  await pane5.getByLabel('Вопрос помощнику').press('Enter')
  const drawn = pane5.getByTestId('copilot-proposal').last()
  await expect(drawn).toHaveAttribute('data-status', 'open', { timeout: 20_000 })
  await expect(drawn).toContainText('7 помещений')
  await drawn.getByRole('button', { name: 'Применить' }).click()
  await expect(drawn).toHaveAttribute('data-status', 'applied')
  await drawn.getByRole('link', { name: 'Открыть план в редакторе' }).click()
  await expect(page).toHaveURL(/#\/sketch\//)
  await expect(page.getByText('Коридор', { exact: true })).toBeVisible({ timeout: 15_000 })
  const drawings = (await (await page.request.get(`/api/import/v1/drawings?building_id=${building}`)).json()).items as { name: string; kind: string }[]
  expect(drawings.some(d => d.kind === 'sketch' && d.name === 'Коридор с 6 кабинетами')).toBe(true)

  // switched off, the copilot is not on screen at all; the rest works
  await configure(page, false)
  await page.goto(`/#/b/${building}`)
  await page.reload()
  await expect(page.getByTestId('building-name')).toHaveText(`Помощник ${stamp}`)
  await expect(page.getByTestId('copilot-open')).toHaveCount(0)
  await expect(page.getByTestId('copilot')).toHaveCount(0)
  } finally {
    await restore()
  }
})
