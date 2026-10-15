import { mkdirSync, writeFileSync } from 'node:fs'
import { expect, type APIRequestContext, type Page } from '@playwright/test'

// What a trial needs: to talk to the copilot as the signed-in person, to read what it proposed, and to measure
// places against the rooms. Nothing here applies a proposal.

export type XY = [number, number]
export type Ring = XY[]
export type Opening = { kind: string; width: number; center: XY; poly: XY[] }
export type RoomGeo = { id: string; name: string; number: string; floor_id: string; area: number; ring: Ring }
export type TypeInfo = { id: string; name: string; size: [number, number, number]; wall_mounted: boolean; ceiling_mounted: boolean; elevation: number | null; values: Record<string, unknown> }
export type Action = { label: string; kind?: string; type_id?: string; x?: number; y?: number; angle?: number; floor_id?: string
  method?: string; path?: string; body?: Record<string, unknown>; show?: { kind: string; floor_id: string; x: number; y: number; from?: { x: number; y: number } } }
export type Proposal = { id: string; summary: string; status: string; actions: Action[]; shows: { kind: string; floor_id: string; x: number | null; y: number | null }[] }
export type Answer = { text: string; interim: string; tools: { name: string; error?: string }[]; proposals: Proposal[]; steps: number; seconds: number; error?: string }

export const API = { copilot: '/api/copilot/v1', buildings: '/api/buildings/v1', import: '/api/import/v1', assets: '/api/assets/v1', catalog: '/api/catalog/v1' }

export async function json<T>(r: Promise<import('@playwright/test').APIResponse> | import('@playwright/test').APIResponse): Promise<T> {
  const res = await r
  if (!res.ok()) throw new Error(`${res.url()}: ${res.status()} ${await res.text()}`)
  return await res.json() as T
}

/** One message to the copilot in a chat of its own; the whole answer, read from the stream. */
export async function ask(req: APIRequestContext, building: string, question: string, ui: Record<string, unknown>): Promise<Answer> {
  const chat = await json<{ id: string }>(req.post(`${API.copilot}/chats`, { data: { building_id: building } }))
  const started = Date.now()
  const r = await req.post(`${API.copilot}/chats/${chat.id}/messages`, { data: { text: question, ui: { building: { id: building, name: 'Проверка копилота' }, ...ui } }, timeout: 15 * 60_000 })
  const seconds = Math.round((Date.now() - started) / 1000)
  if (!r.ok()) return { text: '', interim: '', tools: [], proposals: [], steps: 0, seconds, error: `${r.status()} ${await r.text()}` }
  const events = (await r.text()).split('\n').filter(l => l.startsWith('data:')).map(l => JSON.parse(l.slice(5)) as Record<string, unknown>)
  let text = '', interim = ''
  const tools: Answer['tools'] = []
  const proposals: Proposal[] = []
  let error: string | undefined
  let steps = 0
  for (const e of events) {
    if (e.type === 'text') text += e.text as string
    else if (e.type === 'interim') { interim += text + '\n'; text = '' }
    else if (e.type === 'tool') { tools.push({ name: e.name as string, error: e.error as string | undefined }); steps++ }
    else if (e.type === 'proposal') proposals.push(await json<Proposal>(req.get(`${API.copilot}/proposals/${(e.proposal as { id: string }).id}`)))
    else if (e.type === 'error') error = e.message as string
  }
  return { text: text.trim(), interim: interim.trim(), tools, proposals, steps, seconds, error }
}

// ------------------------------------------------------------------ geometry ---
export function outerRing(polygon: unknown): Ring {
  if (!Array.isArray(polygon) || !polygon.length) return []
  const first = polygon[0]
  const pts = Array.isArray(first) && Array.isArray(first[0]) ? first as unknown[] : polygon as unknown[]
  return pts.filter((p): p is XY => Array.isArray(p) && p.length >= 2).map(p => [Number(p[0]), Number(p[1])])
}

export function inside(p: XY, ring: Ring): boolean {
  let hit = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j]
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi || 1e-12) + xi) hit = !hit
  }
  return hit
}

export const dist = (a: XY, b: XY) => Math.hypot(a[0] - b[0], a[1] - b[1])

function toSegment(p: XY, a: XY, b: XY): number {
  const ab: XY = [b[0] - a[0], b[1] - a[1]]
  const ln = ab[0] ** 2 + ab[1] ** 2
  const t = ln < 1e-12 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / ln))
  return dist(p, [a[0] + ab[0] * t, a[1] + ab[1] * t])
}

/** Distance from a point to the nearest wall of the room. */
export function toWall(p: XY, ring: Ring): number {
  let best = Infinity
  for (let i = 0; i < ring.length; i++) best = Math.min(best, toSegment(p, ring[i], ring[(i + 1) % ring.length]))
  return best
}

/** The item's front direction for an angle (the viewer's convention: (sin a, −cos a)). */
export const front = (angle: number): XY => [Math.sin((angle * Math.PI) / 180), -Math.cos((angle * Math.PI) / 180)]

/** Whether an item at `p` with `angle` looks at `target` (within 60°). */
export function faces(p: XY, angle: number, target: XY): boolean {
  const f = front(angle)
  const d: XY = [target[0] - p[0], target[1] - p[1]]
  const ln = Math.hypot(...d) || 1
  return (f[0] * d[0] + f[1] * d[1]) / ln > 0.5
}

/** Within `margin` of an opening's edge (its half-width counted): a thing there blocks or hangs over it. */
export const nearOpening = (p: XY, openings: Opening[], margin = 0.3) => openings.some(o => dist(p, o.center) < (o.width ?? 0.9) / 2 + margin)

// ------------------------------------------------------------------- catalog ---
export const ROLE: Record<string, RegExp> = {
  desk: /^(рабочий стол|стол офисный|стол письменный|стол врача|стол для совещаний|стол\b)/i,
  seat: /^(кресло|стул)(?! ?-коляска)/i,
  storage: /^(шкаф для|стеллаж)/i,
  screen: /экран|телевизор|панель информационная|табло/i,
  light: /светильник/i,
  detector: /извещатель/i,
}

export function roleOf(types: Map<string, TypeInfo>, id: string | undefined): string {
  const t = id ? types.get(id) : undefined
  if (!t) return 'unknown'
  for (const [role, re] of Object.entries(ROLE)) if (re.test(t.name)) return role
  return 'other'
}

/** The things a proposal would put or move: where, with what role, facing where. */
export function placed(p: Proposal, types: Map<string, TypeInfo>) {
  return p.actions.map(a => {
    if (a.kind === 'asset_new') return { role: roleOf(types, a.type_id), type: types.get(a.type_id!)?.name ?? a.type_id ?? '?', at: [a.x!, a.y!] as XY, angle: a.angle ?? 0, floor: a.floor_id!, kind: 'new' as const }
    if (a.path?.endsWith('/move') && a.body) return { role: 'moved', type: a.label, at: [a.body.x as number, a.body.y as number] as XY, angle: (a.body.angle as number) ?? 0, floor: a.body.floor_id as string, kind: 'move' as const }
    return null
  }).filter((x): x is NonNullable<typeof x> => !!x)
}

// --------------------------------------------------------------------- text ---
export const sentences = (text: string) => text.split(/[.!?…]+\s/).filter(s => s.trim().length > 2).length
export function cyrillicShare(text: string): number {
  // link targets (room:<uuid>), inventory numbers and units are not words
  const words = text.replace(/\([a-z]+:[^)]*\)/g, '').replace(/[A-Za-z]*\d[\w-]*/g, '').replace(/\b(м|м²|лк|лм|Вт|мм|см|кВт|лк)\b/g, '')
  const letters = words.match(/\p{L}/gu) ?? []
  const cyr = words.match(/\p{Script=Cyrillic}/gu) ?? []
  return letters.length ? cyr.length / letters.length : 1
}

// ------------------------------------------------------------------- report ---
export type Result = { name: string; prompt: string; ok: boolean; failures: string[]; notes: string[]; answer: Answer }
export const results: Result[] = []

export function check(name: string, prompt: string, answer: Answer, rules: [string, boolean][], notes: string[] = []): Result {
  const failures = rules.filter(([, ok]) => !ok).map(([what]) => what)
  if (answer.error) failures.push(`ошибка ответа: ${answer.error}`)
  const r: Result = { name, prompt, ok: failures.length === 0, failures, notes, answer }
  results.push(r)
  return r
}

export function writeReport(model: string, building: string) {
  mkdirSync('eval-results', { recursive: true })
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')
  const passed = results.filter(r => r.ok).length
  const lines = [`# Копилот: прогон ${stamp}`, '', `Модель: ${model}. Здание: ${building}. Прошло ${passed} из ${results.length}.`, '',
    '| Сценарий | Итог | Шагов | Сек | Предл. | Замечания |', '|---|---|---|---|---|---|',
    ...results.map(r => `| ${r.name} | ${r.ok ? '✓' : '✗'} | ${r.answer.steps} | ${r.answer.seconds} | ${r.answer.proposals.length} | ${[...r.failures, ...r.notes.map(n => `_${n}_`)].join('; ')} |`),
    '']
  for (const r of results) {
    lines.push(`## ${r.name}`, '', `**Вопрос:** ${r.prompt}`, '', `**Инструменты:** ${r.answer.tools.map(t => t.name + (t.error ? ` (ошибка: ${t.error.slice(0, 80)})` : '')).join(', ') || '—'}`, '')
    if (r.answer.interim) lines.push(`**Между делом:** ${r.answer.interim.replace(/\n+/g, ' ').slice(0, 600)}`, '')
    lines.push(`**Ответ:** ${r.answer.text.slice(0, 1500)}`, '')
    for (const p of r.answer.proposals) lines.push(`**Предложение:** ${p.summary} — ${p.actions.length} действий: ${p.actions.slice(0, 12).map(a => a.label).join('; ')}`, '')
    if (r.failures.length) lines.push(`**Не так:** ${r.failures.join('; ')}`, '')
  }
  const path = `eval-results/${stamp}.md`
  writeFileSync(path, lines.join('\n'))
  writeFileSync(`eval-results/${stamp}.json`, JSON.stringify(results, null, 1))
  return path
}

export async function signInApi(page: Page, who: 'admin' | 'user') {
  const { signIn } = await import('../tests/helpers')
  await signIn(page, who)
  expect(page).toBeTruthy()
  return page.request
}
