import { test, expect, type APIRequestContext, type Browser } from '@playwright/test'
import {
  API, ask, check, cyrillicShare, dist, faces, inside, json, nearOpening, outerRing, placed, results, roleOf, sentences, signInApi, toWall, writeReport,
  type Opening, type RoomGeo, type TypeInfo,
} from './lib'

// Trials of the copilot with the live model: a building drawn from the template (four offices with windows along
// a corridor), a few objects seeded, and questions a building administrator would ask. Nothing is applied.

let admin: APIRequestContext
let user: APIRequestContext
let building = ''
let floor = ''
let drawing = ''
let model = ''
const rooms = new Map<string, RoomGeo>()          // by number: 101…104, and 'Коридор'
let openings: Opening[] = []
const types = new Map<string, TypeInfo>()
const seeded: Record<string, string> = {}        // inventory numbers of the seeded objects
let brokenDrawing = ''

const byRole = (role: string) => [...types.values()].find(t => roleOf(types, t.id) === role)
const byName = (re: RegExp) => [...types.values()].find(t => re.test(t.name))
const room = (n: string) => rooms.get(n)!
const inRoom = (p: [number, number], n: string) => inside(p, room(n).ring)
const ui = (extra: Record<string, unknown> = {}) => ({ section: 'plan', floor: { id: floor, name: 'Этаж 1' }, ...extra })
const uiRoom = (n: string) => ui({ room: { id: room(n).id, name: `${n} Кабинет` } })

async function waitFor<T>(what: () => Promise<T | null>, seconds: number, label: string): Promise<T> {
  const until = Date.now() + seconds * 1000
  while (Date.now() < until) {
    const v = await what()
    if (v) return v
    await new Promise(r => setTimeout(r, 2000))
  }
  throw new Error(`не дождались: ${label}`)
}

test.beforeAll(async ({ browser }: { browser: Browser }) => {
  test.setTimeout(10 * 60_000)
  admin = await signInApi(await (await browser.newContext()).newPage(), 'admin')
  user = await signInApi(await (await browser.newContext()).newPage(), 'user')
  const status = await json<{ enabled: boolean; model: string }>(admin.get(`${API.copilot}/status`))
  if (!status.enabled) throw new Error('Копилот выключен на стенде: включите модель в «Состоянии системы»')
  model = status.model
  for (const t of (await json<{ items: TypeInfo[] }>(admin.get(`${API.catalog}/types?active=true`))).items) types.set(t.id, t)

  // the building: four 5 × 5 offices on both sides of a corridor, windows on the outer walls, doors from the corridor
  const stamp = Date.now().toString().slice(-6)
  building = (await json<{ id: string }>(admin.post(`${API.buildings}/buildings`, { data: { name: `Проверка копилота ${stamp}` } }))).id
  const made = await json<{ sketch: unknown }>(admin.post(`${API.import}/sketch-templates`, { data: { template: 'corridor', params: { rooms_top: 2, rooms_bottom: 2, room_width: 5, room_depth: 5, corridor_width: 2.2 } } }))
  drawing = (await json<{ id: string }>(admin.post(`${API.import}/sketches`, { data: { building_id: building, name: 'План' } }))).id
  const v = (await json<{ version: number }>(admin.get(`${API.import}/drawings/${drawing}/sketch`))).version
  await json(admin.put(`${API.import}/drawings/${drawing}/sketch`, { data: { sketch: made.sketch, version: v } }))
  await json(admin.post(`${API.import}/drawings/${drawing}/builds`, { data: {} }))
  await waitFor(async () => {
    const d = await json<{ build: { status: string } | null }>(admin.get(`${API.import}/drawings/${drawing}`))
    if (d.build?.status === 'failed') throw new Error('сборка плана упала')
    return d.build?.status === 'done' ? d : null
  }, 180, 'сборка плана')
  const tree = await waitFor(async () => {
    const t = await json<{ floors: { id: string; rooms: { id: string; name: string; number: string; area: number; status: string }[] }[] }>(admin.get(`${API.buildings}/buildings/${building}/tree`))
    return t.floors[0]?.rooms.length >= 5 ? t : null
  }, 120, 'помещения в здании')
  floor = tree.floors[0].id
  for (const r of tree.floors[0].rooms) {
    const full = await json<{ polygon: unknown }>(admin.get(`${API.buildings}/rooms/${r.id}`))
    rooms.set(r.number || r.name, { id: r.id, name: r.name, number: r.number, floor_id: floor, area: r.area, ring: outerRing(full.polygon) })
  }
  openings = ((await json<{ plan: { openings: Opening[] } }>(admin.get(`${API.buildings}/floors/${floor}/plan`))).plan.openings ?? [])
  expect(rooms.has('101') && rooms.has('104') && openings.length >= 4, 'здание с четырьмя кабинетами и проёмами').toBe(true)

  // seeded objects: two chairs in 103 (to be moved), a faulty device in 101 (to be found)
  const put = async (t: TypeInfo, n: string, number: string, at: [number, number]) => {
    const a = await json<{ id: string; version: number }>(admin.post(`${API.assets}/assets`, { data: { type_id: t.id, floor_id: floor, x: at[0], y: at[1], inventory_no: number } }))
    seeded[number] = a.id
    return a
  }
  const seat = byRole('seat')!, desk = byRole('desk')!
  const c103 = centre('103'), c101 = centre('101')
  await put(seat, '103', `КР-${stamp}-1`, [c103[0] - 0.8, c103[1]])
  await put(seat, '103', `КР-${stamp}-2`, [c103[0] + 0.8, c103[1]])
  const device = byName(/принтер|мфу/i) ?? desk
  const broken = await put(device, '101', `ПР-${stamp}`, [c101[0], c101[1] - 1])
  await json(admin.post(`${API.assets}/assets/${broken.id}/state`, { data: { state: 'faulty', version: broken.version } }))

  // a drawn plan with mistakes, for the repair scenario
  const bad = JSON.parse(JSON.stringify(made.sketch)) as { floors: { nodes: Record<string, number[]>; walls: Record<string, unknown> }[] }
  const f = bad.floors[0]
  f.nodes.s1 = [1, 1]; f.nodes.s2 = [1, 1.003]
  f.walls.short = { a: 's1', b: 's2', thickness: 0.1, height: null, kind: 'partition' }
  const firstWall = Object.values(f.walls)[0] as { a: string; b: string }
  f.walls.twin = { a: firstWall.a, b: firstWall.b, thickness: 0.25, height: null, kind: 'bearing' }
  brokenDrawing = (await json<{ id: string }>(admin.post(`${API.import}/sketches`, { data: { building_id: building, name: 'План с ошибками' } }))).id
  const bv = (await json<{ version: number }>(admin.get(`${API.import}/drawings/${brokenDrawing}/sketch`))).version
  await json(admin.put(`${API.import}/drawings/${brokenDrawing}/sketch`, { data: { sketch: bad, version: bv } }))
})

function segDist(p: [number, number], a: [number, number], b: [number, number]): number {
  const ab = [b[0] - a[0], b[1] - a[1]]
  const ln = ab[0] ** 2 + ab[1] ** 2
  const t = ln < 1e-12 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / ln))
  return Math.hypot(p[0] - a[0] - ab[0] * t, p[1] - a[1] - ab[1] * t)
}

function centre(n: string): [number, number] {
  const ring = room(n).ring
  return [ring.reduce((s, p) => s + p[0], 0) / ring.length, ring.reduce((s, p) => s + p[1], 0) / ring.length]
}

test.afterAll(() => {
  const path = writeReport(model, building)
  console.log(`\nОтчёт: e2e/${path}\n` + results.map(r => `${r.ok ? '✓' : '✗'} ${r.name}${r.failures.length ? ' — ' + r.failures.join('; ') : ''}`).join('\n'))
})

const brief = (a: { text: string }, max: number): [string, boolean][] => [
  [`ответ не длиннее ${max} предложений (${sentences(a.text)})`, sentences(a.text) <= max],
  ['ответ по-русски', cyrillicShare(a.text) >= 0.85],
]

test('контекст: модель знает, что открыто', async () => {
  const q = 'что у меня сейчас открыто? одной фразой'
  const a = await ask(admin, building, q, uiRoom('102'))
  check('контекст экрана', q, a, [
    ['назван кабинет 102', /102/.test(a.text)],
    ['без лишних инструментов (≤1)', a.steps <= 1],
    ...brief(a, 2),
  ])
})

test('кабинет: два рабочих места, кресла, шкаф', async () => {
  const q = 'обставь кабинет 101: два рабочих места с креслами и шкаф для документов'
  const a = await ask(admin, building, q, uiRoom('101'))
  const items = a.proposals.flatMap(p => placed(p, types))
  const desks = items.filter(i => i.role === 'desk'), seats = items.filter(i => i.role === 'seat'), storage = items.filter(i => i.role === 'storage')
  const ring = room('101').ring
  const seatAtDesk = (s: typeof items[0]) => desks.some(d => dist(s.at, d.at) <= 1.4 && faces(s.at, s.angle, d.at))
  check('обставить кабинет', q, a, [
    ['есть предложение', a.proposals.length >= 1],
    ['два стола', desks.length === 2],
    ['столы у стены (≤0,8 м)', desks.length > 0 && desks.every(d => toWall(d.at, ring) <= 0.8)],
    ['столы не у двери (>0,6 м от проёма)', desks.every(d => !nearOpening(d.at, openings.filter(o => o.kind === 'door'), 0.6))],
    ['два кресла', seats.length >= 2],
    ['кресла у столов и лицом к ним', seats.length > 0 && seats.every(seatAtDesk)],
    ['шкаф у стены', storage.length >= 1 && storage.every(s => toWall(s.at, ring) <= 0.8)],
    ['всё внутри кабинета 101', items.every(i => inside(i.at, ring))],
    ['не больше 10 шагов', a.steps <= 10],
    ['без уточняющего вопроса', !/\?\s*$/.test(a.text)],
    ...brief(a, 4),
  ], [`поставлено: ${items.map(i => i.type).join(', ') || '—'}`])
})

test('экран на свободную стену', async () => {
  const q = 'повесь в кабинете 102 экран (информационную панель) на свободную стену'
  const a = await ask(admin, building, q, uiRoom('102'))
  const items = a.proposals.flatMap(p => placed(p, types))
  const walls = items.filter(i => types.get([...types.values()].find(t => t.name === i.type)?.id ?? '')?.wall_mounted)
  const ring = room('102').ring
  check('экран на стену', q, a, [
    ['есть предложение', a.proposals.length >= 1],
    ['настенный предмет', walls.length >= 1],
    ['на стене (≤0,35 м)', walls.length > 0 && walls.every(w => toWall(w.at, ring) <= 0.35)],
    ['не над проёмом (>0,3 м от края)', walls.every(w => !nearOpening(w.at, openings, 0.3))],
    ['в кабинете 102', walls.every(w => inside(w.at, ring) || toWall(w.at, ring) <= 0.35)],
    ...brief(a, 3),
  ], [`поставлено: ${items.map(i => i.type).join(', ') || '—'}`])
})

test('точное место: шкаф к северной стене в метре от угла', async () => {
  const q = 'поставь в кабинете 102 шкаф для документов к северной стене, в метре от угла'
  const a = await ask(admin, building, q, uiRoom('102'))
  const items = a.proposals.flatMap(p => placed(p, types))
  const storage = items.filter(i => i.role === 'storage')
  const ring = room('102').ring
  const top = Math.max(...ring.map(p => p[1]))
  const xs = ring.map(p => p[0])
  const cornerDist = (x: number) => Math.min(Math.abs(x - Math.min(...xs)), Math.abs(x - Math.max(...xs)))
  check('точное место у стены', q, a, [
    ['есть предложение', a.proposals.length >= 1],
    ['один шкаф', storage.length === 1],
    ['у северной стены (≤0,5 м от неё)', storage.length > 0 && storage.every(s => top - s.at[1] <= 0.5)],
    ['около метра от угла (0,8–2 м до ближнего угла)', storage.every(s => cornerDist(s.at[0]) >= 0.8 && cornerDist(s.at[0]) <= 2.0)],
    ['внутри кабинета 102', storage.every(s => inside(s.at, ring))],
    ['точным инструментом (place_at или side)', a.tools.some(t => t.name === 'place_at' || t.name === 'place_by_rules')],
    ['не больше 6 шагов', a.steps <= 6],
    ...brief(a, 3),
  ], [`поставлено: ${items.map(i => i.type).join(', ') || '—'}`])
})

test('точка в дверях: не ставит, сдвигает и объясняет', async () => {
  // the door of 103 from the corridor: the point just inside the room, in the door's way
  const ring = room('103').ring
  const door = openings.filter(o => o.kind === 'door').map(o => ({ o, d: Math.min(...ring.map((p, i) => segDist(o.center, p, ring[(i + 1) % ring.length]))) })).sort((a, b) => a.d - b.d)[0].o
  const c = centre('103')
  const dir: [number, number] = [c[0] - door.center[0], c[1] - door.center[1]]
  const ln = Math.hypot(...dir) || 1
  const at: [number, number] = [+(door.center[0] + dir[0] / ln * 0.4).toFixed(2), +(door.center[1] + dir[1] / ln * 0.4).toFixed(2)]
  const q = `поставь в кабинете 103 тумбу или шкаф в точку (${at[0]}, ${at[1]})`
  const a = await ask(admin, building, q, uiRoom('103'))
  const items = a.proposals.flatMap(p => placed(p, types))
  check('точка в дверях', q, a, [
    ['есть предложение или отказ с причиной', a.proposals.length >= 1 || /двер|проход|проём/i.test(a.text)],
    ['ничего не стоит в дверях (>0,3 м от края проёма)', items.every(i => !nearOpening(i.at, openings.filter(o => o.kind === 'door'), 0.3))],
    ['всё внутри кабинета 103', items.every(i => inside(i.at, ring))],
    ['сказано про дверь или сдвиг', /двер|проход|сдвин|ближайш/i.test(a.text)],
    ...brief(a, 3),
  ], [`поставлено: ${items.map(i => `${i.type} (${i.at.join(', ')})`).join('; ') || '—'}`])
})

test('освещение кабинета', async () => {
  const q = 'освети кабинет 104 светильниками по норме для офиса'
  const a = await ask(admin, building, q, uiRoom('104'))
  const lights = a.proposals.flatMap(p => placed(p, types)).filter(i => i.role === 'light')
  const ring = room('104').ring
  let minPair = Infinity
  for (let i = 0; i < lights.length; i++) for (let j = i + 1; j < lights.length; j++) minPair = Math.min(minPair, dist(lights[i].at, lights[j].at))
  check('освещение', q, a, [
    ['есть предложение', a.proposals.length >= 1],
    ['не меньше двух светильников', lights.length >= 2],
    ['все в кабинете', lights.every(l => inside(l.at, ring))],
    ['равномерно: не ближе 1,2 м друг к другу', lights.length < 2 || minPair >= 1.2],
    ['не у самой стены (≥0,5 м)', lights.every(l => toWall(l.at, ring) >= 0.5)],
    ...brief(a, 3),
  ], [`светильников: ${lights.length}`])
})

test('извещатели на этаже', async () => {
  const q = 'поставь пожарные извещатели на этаже'
  const a = await ask(admin, building, q, ui())
  const dets = a.proposals.flatMap(p => placed(p, types)).filter(i => i.role === 'detector')
  const covered = [...rooms.values()].filter(r => dets.some(d => inside(d.at, r.ring)))
  check('извещатели', q, a, [
    ['есть предложение', a.proposals.length >= 1],
    ['по одному в каждом помещении', covered.length === rooms.size],
    ['все внутри помещений', dets.every(d => [...rooms.values()].some(r => inside(d.at, r.ring)))],
    ...brief(a, 3),
  ], [`извещателей: ${dets.length}, помещений: ${rooms.size}`])
})

test('перенос из помещения в помещение', async () => {
  const q = 'перенеси всё из кабинета 103 в кабинет 104'
  const a = await ask(admin, building, q, ui())
  const moves = a.proposals.flatMap(p => placed(p, types)).filter(i => i.kind === 'move')
  check('перенос', q, a, [
    ['есть предложение', a.proposals.length >= 1],
    ['переносятся оба кресла', moves.length === 2],
    ['в кабинет 104', moves.every(m => inRoom(m.at, '104'))],
    ['ничего не применено само', (await json<{ room_id: string }>(admin.get(`${API.assets}/assets/${seeded[Object.keys(seeded)[0]]}`))).room_id === room('103').id],
    ...brief(a, 3),
  ])
})

test('что неисправно', async () => {
  const q = 'что на этаже неисправно? коротко'
  const a = await ask(admin, building, q, ui())
  const number = Object.keys(seeded).find(n => n.startsWith('ПР-'))!
  check('неисправное', q, a, [
    ['назван неисправный объект', a.text.includes(number)],
    ['ссылка на объект', a.text.includes('asset:') || a.text.includes(`/assets/`)],
    ...brief(a, 3),
  ])
})

test('аудит учёта', async () => {
  const q = 'проверь учёт здания, коротко'
  const a = await ask(admin, building, q, ui())
  check('аудит', q, a, [
    ['вызван аудит', a.tools.some(t => t.name === 'audit_assets')],
    ['сказано про неисправный', /неисправ/i.test(a.text)],
    ...brief(a, 6),
  ])
})

test('переименование — предложением', async () => {
  const q = 'переименуй кабинет 104 в Приёмная'
  const a = await ask(admin, building, q, ui())
  const patch = a.proposals.flatMap(p => p.actions).find(x => x.method === 'PATCH' && x.path?.includes(room('104').id))
  const now = await json<{ name: string }>(admin.get(`${API.buildings}/rooms/${room('104').id}`))
  check('переименование', q, a, [
    ['есть предложение на 104', !!patch],
    ['новое имя — Приёмная', (patch?.body?.name as string | undefined) === 'Приёмная'],
    ['само не применено', now.name !== 'Приёмная'],
    ...brief(a, 2),
  ])
})

test('паспорт здания', async () => {
  const q = 'опиши здание в трёх предложениях'
  const a = await ask(admin, building, q, ui())
  check('паспорт', q, a, [
    ['про помещения', /помещен|кабинет/i.test(a.text)],
    ...brief(a, 4),
  ])
})

test('чужое здание закрыто', async () => {
  const q = 'какие объекты есть в этом здании? перечисли инвентарные номера'
  const a = await ask(user, building, q, { section: 'home' })
  check('права', q, a, [
    ['чужих номеров в ответе нет', !Object.keys(seeded).some(n => a.text.includes(n))],
    ['предлагающих инструментов не звал', !a.tools.some(t => t.name.startsWith('propose') || t.name === 'move_to_room')],
  ])
})

test('починка нарисованного плана', async () => {
  const q = 'проверь план и исправь ошибки'
  const a = await ask(admin, building, q, { section: 'рисование плана', drawing: { id: brokenDrawing, name: 'План с ошибками' } })
  const fix = a.proposals.find(p => p.actions.some(x => x.kind === 'sketch'))
  check('починка плана', q, a, [
    ['проверка вызвана', a.tools.some(t => t.name === 'check_plan')],
    ['предложение с планом', !!fix],
    ['чинит короткую и двойную стену', !!fix && /short|twin/.test(fix.actions[0].label)],
    ...brief(a, 4),
  ])
})
