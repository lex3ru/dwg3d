// The viewer was written for the single-application API (legacy/): one drawing
// with its result, plans and pins under /api/drawings/<id>. Its data now lives
// in two services — import (files, builds) and buildings (floors, rooms, pins,
// the map, the facade). This module answers the viewer's old requests from the
// new services, so the viewer itself is carried over unchanged.
//
// What is not built yet answers "empty": layers and placed objects (stage 4),
// routes of people and zones (stage 8), the copilot (stage 9).

/** Parts of the viewer whose data arrives with later services; their entry points are hidden until then. */
export const LATER = {
  layers: false,       // layers and what is placed on them: the assets service, stage 4
  reports: false,      // the equipment list: stages 4–5
  catalog: false,      // the catalog editor: stage 3
  copilot: false,      // stage 9
}

type Json = Record<string, any>   // eslint-disable-line @typescript-eslint/no-explicit-any

const IMPORT = '/api/import/v1'
const BUILDINGS = '/api/buildings/v1'
const real = globalThis.fetch.bind(globalThis)

const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** A failure of a new service in the shape the viewer reads (`detail`). */
async function failure(r: Response): Promise<Response> {
  let detail = `${r.status} ${r.statusText}`
  try { const p = await r.json(); detail = p.detail ?? p.title ?? detail } catch { /* not JSON */ }
  if (r.status === 401) location.assign(`/auth/login?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`)
  return json({ detail }, r.status)
}

class Failed extends Error {
  response: Response
  constructor(response: Response) { super('request failed'); this.response = response }
}

async function call<T = Json>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) { init.body = JSON.stringify(body); init.headers = { 'Content-Type': 'application/json' } }
  const r = await real(url, init)
  if (!r.ok) throw new Failed(await failure(r))
  return (r.status === 204 ? null : await r.json()) as T
}

// ------------------------------------------------------------ what we know ---
/** drawing -> its building and published build (filled by every GET of the drawing) */
/** Another drawing of the same building, placed in the scene of the drawing on screen. */
export interface Neighbour { id: string; name: string; url: string; position: [number, number, number]; turn: number }
const known = new Map<string, {
  building: string; build: string | null; n: number; floors: Map<string, string>; neighbours: Neighbour[]
}>()
/** ids the viewer gave to pins it created -> the ids they got in the buildings service */
const pinIds = new Map<string, string>()
let admin = false
export const setAdmin = (value: boolean) => { admin = value }

/** Where a file of the drawing's published build is (the viewer's loaders fetch it themselves). */
export function buildFileUrl(drawing: string, path: string): string {
  const build = known.get(drawing)?.build
  return build ? `${IMPORT}/builds/${build}/files/${path}` : `${IMPORT}/builds/00000000-0000-0000-0000-000000000000/files/${path}`
}
export const neighbours = (drawing: string): Neighbour[] => known.get(drawing)?.neighbours ?? []

/**
 * Where the model of drawing `b` stands in the scene of drawing `a`.
 * A model's origin is the plan point `center` of its drawing (x right, plan y = -z);
 * `placement` puts a drawing's plan into the building: turn (degrees, counter-clockwise), then shift.
 */
function relative(a: Json, b: Json): Pick<Neighbour, 'position' | 'turn'> {
  const rad = (d: number) => (d * Math.PI) / 180
  const turn = (v: [number, number], t: number): [number, number] =>
    [v[0] * Math.cos(t) - v[1] * Math.sin(t), v[0] * Math.sin(t) + v[1] * Math.cos(t)]
  const ta = rad(a.placement.rotation), tb = rad(b.placement.rotation)
  const [ca, cb] = [a.result.center ?? [0, 0], b.result.center ?? [0, 0]]
  const q = turn(cb, tb)                                       // b's origin in the building…
  const inA = turn([q[0] + b.placement.dx - a.placement.dx, q[1] + b.placement.dy - a.placement.dy], -ta)   // …and in a's plan
  return { position: [inA[0] - ca[0], b.placement.dz - a.placement.dz, -(inA[1] - ca[1])], turn: tb - ta }
}

export const facadeUrl = (drawing: string, version: number) =>
  `${BUILDINGS}/buildings/${known.get(drawing)?.building}/facade.glb?v=${version}`

async function job(id: string): Promise<Json> {
  const d = await call('GET', `${IMPORT}/drawings/${id}`)
  const [model, building, config] = await Promise.all([
    call('GET', `${BUILDINGS}/buildings/${d.building_id}/model`),
    call('GET', `${BUILDINGS}/buildings/${d.building_id}`),
    call('GET', `${IMPORT}/drawings/${id}/config`),
  ])
  const shown = (model.drawings as Json[]).find((x) => x.id === id)
  const b = d.build ?? { status: 'queued', stage: 'queued', progress: 0, message: '' }
  // built, but the building has not taken the build in yet (it follows the event)
  const publishing = b.status === 'done' && shown?.build_id !== b.id
  const floors = new Map<string, string>()
  for (const f of shown?.result?.floors ?? []) if (f.floor_id) floors.set(f.id, f.floor_id)
  const others = shown ? (model.drawings as Json[]).filter((x) => x.id !== id && x.result) : []
  const neighbours = others.map((x) => ({ id: x.id, name: x.name, url: x.model_url, ...relative(shown!, x) }))
  known.set(id, { building: d.building_id, build: shown?.build_id ?? null, n: shown?.build_n ?? 0, floors, neighbours })
  const marks = await pins(id)
  const facade = building.facade
  return {
    id, project_id: d.building_id, name: d.name, filename: d.filename ?? '',
    status: publishing ? 'running' : b.status, stage: publishing ? 'export' : b.stage,
    progress: publishing ? 0.99 : b.progress, message: publishing ? 'Публикация' : b.message, error: b.error ?? undefined,
    result: shown?.result, model_url: shown ? shown.model_url : undefined, build: shown?.build_n ?? 0,
    config: config.config,
    view: {
      name: d.name,
      site: building.site ? { ...building.site, azimuth: building.site.bearing } : undefined,
      detail: facade ? { file: facade.name, size: facade.size, version: building.version,
        offset: [facade.dx, facade.dz, facade.dy], rotation: facade.rotation, scale: facade.scale } : undefined,
      markers: marks.markers, comments: marks.comments, furniture: [], shapes: [],
    },
    layers: [], my_role: admin ? 'owner' : 'viewer',
  }
}

const summary = (d: Json): Json => ({
  id: d.id, project_id: d.building_id, filename: d.filename ?? '', name: d.name,
  status: d.build?.status ?? 'queued', progress: d.build?.progress ?? 0, floors: 0, build: d.build?.n ?? 0,
  size: d.size ?? 0, updated: Date.parse(d.updated_at) / 1000,
})

const PIN_KIND: Record<string, string> = { markers: 'marker', comments: 'comment' }

function pinOut(p: Json, floor: string, id = p.id): Json {
  return { id, version: p.version, floor, pos: p.pos, text: p.note, label: p.title, created: Date.parse(p.created_at) / 1000 }
}

async function pins(id: string): Promise<Json> {
  const k = known.get(id)!
  const byFloor = new Map([...k.floors].map(([candidate, floor]) => [floor, candidate]))
  const { items } = await call('GET', `${BUILDINGS}/buildings/${k.building}/pins`)
  const of = (kind: string) => (items as Json[]).filter((p) => p.kind === kind).map((p) => pinOut(p, byFloor.get(p.floor_id) ?? ''))
  return { build: k.n, markers: of('marker'), comments: of('comment') }
}

async function pinOps(id: string, ops: Json[]): Promise<Json> {
  const k = known.get(id)!
  const items: Json[] = [], deleted: string[] = []
  for (const op of ops) {
    const server = pinIds.get(op.id) ?? op.id
    if (op.op === 'delete') {
      await call('DELETE', `${BUILDINGS}/pins/${server}`)
      deleted.push(op.id)
      continue
    }
    const body = { pos: op.pos, title: op.label ?? '', note: op.text ?? '' }
    const p = op.op === 'create'
      ? await call('POST', `${BUILDINGS}/buildings/${k.building}/pins`,
        { ...body, kind: PIN_KIND[op.kind] ?? 'marker', floor_id: k.floors.get(op.floor) ?? null })
      : await call('PATCH', `${BUILDINGS}/pins/${server}`, { ...body, version: op.version })
    if (op.op === 'create') pinIds.set(op.id, p.id)
    items.push(pinOut(p, op.floor ?? '', op.id))          // under the id the viewer knows it by
  }
  return { items, deleted }
}

async function putView(id: string, v: Json): Promise<Json> {
  const k = known.get(id) ?? (await job(id), known.get(id)!)
  const building = `${BUILDINGS}/buildings/${k.building}`
  if ('site' in v) {
    const s = v.site
    await call('PUT', `${building}/site`, s ? { lat: s.lat, lon: s.lon, bearing: s.azimuth ?? 0, scale: s.scale ?? 1,
      tiles: s.tiles || null, attribution: s.attribution || null } : null)
  }
  if (v.detail) {
    const [dx = 0, dz = 0, dy = 0] = v.detail.offset ?? []
    await call('PATCH', `${building}/facade`, { dx, dy, dz, rotation: v.detail.rotation ?? 0, scale: v.detail.scale ?? 1 })
  }
  return (await job(id)).view
}

const EMPTY_KINDS = { kinds: [], flows: {}, flow_conflicts: [], zone_kinds: {}, zone_forbidden: {}, cables: {} }

// ------------------------------------------------------------------ routes ---
type Handler = (m: RegExpExecArray, init: RequestInit | undefined, url: URL) => Promise<unknown> | unknown
const routes: [string, RegExp, Handler][] = [
  ['GET', /^\/api\/drawings\/([^/]+)$/, (m) => job(m[1])],
  ['GET', /^\/api\/drawings$/, async (_, __, url) => {
    const building = url.searchParams.get('project')
    const [list, model] = await Promise.all([
      call('GET', `${IMPORT}/drawings?building_id=${building}`), call('GET', `${BUILDINGS}/buildings/${building}/model`)])
    const floors = new Map((model.drawings as Json[]).map((x) => [x.id, (x.result?.floors ?? []).length]))
    // the viewer offers the drawings that can be opened: the ones the building has taken in
    return (list.items as Json[]).map((d) => ({ ...summary(d), floors: floors.get(d.id) ?? 0,
      status: floors.has(d.id) ? 'done' : summary(d).status === 'done' ? 'running' : summary(d).status }))
  }],
  ['DELETE', /^\/api\/drawings\/([^/]+)$/, async (m) => { await call('DELETE', `${IMPORT}/drawings/${m[1]}`); return null }],
  ['POST', /^\/api\/drawings\/([^/]+)\/rebuild$/, async (m, init) => {
    await call('POST', `${IMPORT}/drawings/${m[1]}/builds`, { config: JSON.parse(String(init?.body ?? '{}')) })
    return job(m[1])
  }],
  ['POST', /^\/api\/drawings\/([^/]+)\/revision$/, async (m, init) => {
    await call('POST', `${IMPORT}/drawings/${m[1]}/files`, init?.body)
    return job(m[1])
  }],
  ['POST', /^\/api\/projects\/([^/]+)\/drawings$/, async (m, init) => {
    const form = init?.body as FormData
    form.append('building_id', m[1])
    return job((await call('POST', `${IMPORT}/drawings`, form)).id)
  }],
  ['GET', /^\/api\/drawings\/([^/]+)\/files\/(.+)$/, async (m) => {
    if (!known.get(m[1])?.build) await job(m[1])
    return call('GET', buildFileUrl(m[1], m[2]))
  }],
  ['GET', /^\/api\/drawings\/([^/]+)\/drawing\.(dxf|dwg)$/, async (m) => {
    const r = await real(`${IMPORT}/drawings/${m[1]}/export?format=${m[2]}`)
    return r.ok ? r : failure(r)
  }],
  ['PUT', /^\/api\/drawings\/([^/]+)\/view$/, (m, init) => putView(m[1], JSON.parse(String(init?.body ?? '{}')))],
  ['POST', /^\/api\/drawings\/([^/]+)\/detail$/, async (m, init) => {
    const k = known.get(m[1]) ?? (await job(m[1]), known.get(m[1])!)
    const r = await real(`${BUILDINGS}/buildings/${k.building}/facade`, { method: 'PUT', body: init?.body })
    if (!r.ok) throw new Failed(await failure(r))
    return (await job(m[1])).view
  }],
  ['DELETE', /^\/api\/drawings\/([^/]+)\/detail$/, async (m) => {
    await call('DELETE', `${BUILDINGS}/buildings/${known.get(m[1])!.building}/facade`)
    return (await job(m[1])).view
  }],
  ['GET', /^\/api\/drawings\/([^/]+)\/pins$/, async (m) => { if (!known.has(m[1])) await job(m[1]); return pins(m[1]) }],
  ['POST', /^\/api\/drawings\/([^/]+)\/pins:batch$/, (m, init) => pinOps(m[1], JSON.parse(String(init?.body)).ops)],
  ['GET', /^\/api\/drawings\/([^/]+)\/objects$/, (m) => ({ build: known.get(m[1])?.n ?? 0, items: [], unplaced: [] })],
  ['POST', /^\/api\/drawings\/([^/]+)\/objects:batch$/, () => ({ items: [], deleted: [] })],
  ['GET', /^\/api\/projects\/([^/]+)\/layers$/, () => []],
  ['GET', /^\/api\/projects\/([^/]+)\/checks$/, () => ({ fire: [] })],
  ['GET', /^\/api\/projects\/([^/]+)\/proposals$/, () => []],
  ['POST', /^\/api\/projects\/([^/]+)\/ui-context$/, () => null],
  ['GET', /^\/api\/layer-kinds$/, () => EMPTY_KINDS],
  ['GET', /^\/api\/catalog$/, () => ({ categories: [], items: [] })],
  ['GET', /^\/api\/copilot\/status$/, () => ({ enabled: false, model: null, daily_limit: 0, used_today: 0 })],
  ['GET', /^\/api\/config\/default$/, () => call('GET', `${IMPORT}/config/default`)],
]

/** `fetch` for the viewer's modules: the old addresses, answered by the new services. */
export async function fetch(input: string, init?: RequestInit): Promise<Response> {
  const url = new URL(input, location.origin)
  const method = (init?.method ?? 'GET').toUpperCase()
  for (const [verb, pattern, handler] of routes) {
    const m = verb === method ? pattern.exec(url.pathname) : null
    if (!m) continue
    try {
      const out = await handler(m, init, url)
      return out instanceof Response ? out : json(out, out === null ? 204 : 200)
    } catch (e) {
      if (e instanceof Failed) return e.response
      throw e
    }
  }
  console.warn('the viewer asked for something the new services do not have yet:', method, url.pathname)
  return json({ detail: 'Эта возможность появится на одном из следующих этапов' }, 404)
}
