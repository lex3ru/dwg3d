// The viewer was written for the single-application API (legacy/): one drawing
// with its result, plans and pins under /api/drawings/<id>. Its data now lives
// in two services — import (files, builds) and buildings (floors, rooms, pins,
// the map, the facade). This module answers the viewer's old requests from the
// new services, so the viewer itself is carried over unchanged.
//
// Furniture and equipment placed in the scene are the objects of the assets service: «Мебель и оборудование» and a layer
// for each engineering system (systems.ts); the viewer's catalog is the catalog service, its coverage parameters
// those of the catalog's property sets. Variants of the planning service are variants of these layers. What is
// not built yet answers "empty": routes of people, zones, cables (stage 8), the copilot (stage 9).
import { layerOf, SYSTEMS, systemOf } from './systems'

/** Parts of the viewer whose data arrives with later services; their entry points are hidden until then. */
export const LATER = {
  layers: true,        // the layer of the objects of the assets service
  newLayers: false,    // layers of planning: routes, zones, cables, variants — stage 8
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
/** the same for objects placed in the scene: viewer id <-> object id in the assets service */
const objectIds = new Map<string, string>()
const viewerIds = new Map<string, string>()
/** what the viewer shows of an object besides the placed item: its number, where its card is */
const objectInfo = new Map<string, { number: string; card: string }>()

/** An object of accounting (not a free piece of furniture): its inventory number and the address of its card. */
export function assetOf(viewerId: string): { number: string; card: string } | null {
  return objectInfo.get(objectIds.get(viewerId) ?? viewerId) ?? null
}
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
  const [model, building, config, placed] = await Promise.all([
    call('GET', `${BUILDINGS}/buildings/${d.building_id}/model`),
    call('GET', `${BUILDINGS}/buildings/${d.building_id}`),
    call('GET', `${IMPORT}/drawings/${id}/config`),
    call('GET', `${BUILDINGS}/buildings/${d.building_id}/drawings`),
  ])
  const shown = (model.drawings as Json[]).find((x) => x.id === id)
  const b = d.build ?? { status: 'queued', stage: 'queued', progress: 0, message: '' }
  // a build that would retire rooms waits as a draft: the model stays at the published one
  const revision = (placed.items as Json[]).find((x) => x.id === id)?.revision
  const decided = !!revision && revision.n >= (b.n ?? 0)
  // built, but the building has not taken the build in yet (it follows the event)
  const publishing = b.status === 'done' && shown?.build_id !== b.id && !decided
  const floors = new Map<string, string>()
  for (const f of shown?.result?.floors ?? []) if (f.floor_id) floors.set(f.id, f.floor_id)
  const others = shown ? (model.drawings as Json[]).filter((x) => x.id !== id && x.result) : []
  const neighbours = others.map((x) => ({ id: x.id, name: x.name, url: x.model_url, ...relative(shown!, x) }))
  known.set(id, { building: d.building_id, build: shown?.build_id ?? null, n: shown?.build_n ?? 0, floors, neighbours })
  const marks = await pins(id)
  const variants = admin ? await variantsOf(d.building_id) : []
  const facade = building.facade
  return {
    id, project_id: d.building_id, name: d.name, filename: d.filename ?? '',
    status: publishing ? 'running' : b.status, stage: publishing ? 'export' : b.stage,
    progress: publishing ? 0.99 : b.progress, message: publishing ? 'Публикация' : b.message, error: b.error ?? undefined,
    result: shown?.result, model_url: shown ? shown.model_url : undefined, build: shown?.build_n ?? 0,
    draft: revision?.status === 'draft' && revision.n >= (b.n ?? 0)
      ? { revision: revision.id, n: revision.n, retired: revision.summary?.retired ?? 0, merged: revision.summary?.merged ?? 0 }
      : undefined,
    config: config.config,
    view: {
      name: d.name,
      site: building.site ? { ...building.site, azimuth: building.site.bearing } : undefined,
      detail: facade ? { file: facade.name, size: facade.size, version: building.version,
        offset: [facade.dx, facade.dz, facade.dy], rotation: facade.rotation, scale: facade.scale } : undefined,
      markers: marks.markers, comments: marks.comments,
      furniture: shown ? [...await objects(id), ...await variantObjects(id, variants)] : [], shapes: [],
    },
    layers: [...assetsLayers(), ...variants.flatMap(variantLayers)], my_role: admin ? 'owner' : 'viewer',
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
  if (typeof v.name === 'string' && v.name.trim()) await call('PATCH', `${IMPORT}/drawings/${id}`, { name: v.name.trim() })
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

// ---------------------------------------------------- objects and catalog ---
const ASSETS = '/api/assets/v1'
const CATALOG = '/api/catalog/v1'
const LAYER = 'assets'
/** The kinds of layers: «Мебель и оборудование» takes every section of the catalog but those of the systems, which go to
 * their own layers — so a camera placed while «Мебель и оборудование» is being edited lands in «Видеонаблюдение». */
async function layerKinds(): Promise<Json> {
  const systems = new Set(SYSTEMS.map((x) => x.category))
  let rest: string[] | null = null
  try { rest = ((await call('GET', `${CATALOG}/categories`)).items as Json[]).map((c) => c.id).filter((id) => !systems.has(id)) } catch { /* the catalog is down: anything goes */ }
  return { ...EMPTY_KINDS, kinds: [{ kind: 'furniture', name: 'Мебель и оборудование', geoms: ['point'], categories: rest },
    ...SYSTEMS.map((x) => ({ kind: x.kind, name: x.name, geoms: ['point'], categories: [x.category] }))] }
}
const assetsLayers = (): Json[] => [
  { id: LAYER, kind: 'furniture', name: 'Мебель и оборудование', visible: true, locked: !admin, sort: 0, props: { variant_group: LAYER }, version: 1 },
  ...SYSTEMS.map((x, i) => ({ id: `${LAYER}.${x.kind}`, kind: x.kind, name: x.name, visible: true, locked: !admin, sort: 100 * (i + 1),
    props: { variant_group: `${LAYER}.${x.kind}` }, version: 1 })),
]
const assetsLayer = (): Json => assetsLayers()[0]
/** the section of each catalog type, for the items of variants (the objects carry theirs) */
const typeCategory = new Map<string, string | null>()
async function knowTypes(): Promise<void> {
  if (typeCategory.size) return
  for (const active of ['true', 'false']) {
    for (const t of (await call('GET', `${CATALOG}/types?active=${active}`)).items as Json[]) typeCategory.set(t.id, t.category_id ?? null)
  }
}

// ------------------------------------------------------------- variants ---
// Each draft variant of the planning service is a variant of the layer of objects: the viewer shows one of
// them at a time and compares them. Its items are the fact with the variant laid over it; what is done to
// them goes to the variant (planning), not to the objects. Without the planning service — the fact only.
const PLANNING = '/api/planning/v1'
const VARIANT = 'variant:'
/** an item of a variant layer, by the id the viewer knows it by */
const variantItems = new Map<string, { vid: string; layer: string; asset_id?: string; op_id?: string; version?: number; floor: string; at: [number, number]; angle: number; note: string }>()

async function variantsOf(building: string): Promise<Json[]> {
  try {
    const r = await real(`${PLANNING}/variants?building_id=${building}`)
    return r.ok ? ((await r.json()).items as Json[]).filter((v) => v.status === 'draft') : []
  } catch { return [] }
}

/** A variant of the planning service is a variant of each layer of objects: `variant:<id>` of «Мебель и оборудование»,
 * `variant:<id>.<system>` of a system's layer. */
const variantLayers = (v: Json, i: number): Json[] => assetsLayers().map((l) => ({ id: VARIANT + v.id + systemOf(l.id), kind: l.kind,
  name: `${v.name}${v.stale ? ' (устарел)' : ''}`, visible: true, locked: !admin, sort: l.sort + i + 1,
  props: { variant_group: l.id }, version: v.version }))
const variantOfLayer = (layer: string) => layer.slice(VARIANT.length).split('.')[0]

/** The items of the variants on the floors of the drawing. */
async function variantObjects(id: string, list: Json[]): Promise<Json[]> {
  const k = known.get(id)!
  if (list.length) await knowTypes()
  const byFloor = new Map([...k.floors].map(([candidate, floor]) => [floor, candidate]))
  const out: Json[] = []
  for (const v of list) {
    let view: Json
    try { view = await call('GET', `${PLANNING}/variants/${v.id}/view`) } catch { continue }
    for (const o of view.items as Json[]) {
      const floor = byFloor.get(o.floor_id)
      if (o.removed || o.x == null || !floor) continue
      const vid = `${v.id}~${o.key}`
      const layer = VARIANT + v.id + systemOf(layerOf(typeCategory.get(o.type_id)))
      variantItems.set(vid, { vid: v.id, layer, asset_id: o.asset_id ?? undefined, op_id: o.op_id ?? undefined, version: o.version ?? undefined,
        floor, at: [o.x, o.y], angle: o.angle ?? 0, note: o.note ?? '' })
      out.push({ id: vid, version: 1, layer, geom: 'point', floor, item: o.type_id, at: [o.x, o.y],
        angle: ((o.angle ?? 0) + 360) % 360, note: o.note ?? '' })
    }
  }
  return out
}

const isVariantOp = (op: Json) => (op.op === 'create' ? String(op.layer ?? '').startsWith(VARIANT) : variantItems.has(op.id))

/** Changes of items of a variant layer, as edits of the variant. */
async function variantOps(id: string, ops: Json[]): Promise<Json[]> {
  const k = known.get(id)!
  const byVariant = new Map<string, Json[]>()
  for (const op of ops) {
    const vid = op.op === 'create' ? variantOfLayer(String(op.layer)) : variantItems.get(op.id)!.vid
    byVariant.set(vid, [...(byVariant.get(vid) ?? []), op])
  }
  const items: Json[] = []
  for (const [vid, list] of byVariant) {
    const edits: Json[] = []
    const after: Json[] = []
    for (const op of list) {
      if (op.op === 'update' && (op.item !== undefined || op.size !== undefined)) throw refuse('Тип и размер объекта задаёт каталог')
      if (op.op === 'create') {
        const type = (await call('GET', `${CATALOG}/types/${op.item}`)).name
        const number = (await askNumber({ title: 'Новый объект в варианте', optional: true, suggestion: await nextNumber(k.building, op.item),
          generate: generator(op.item, 1).generate,
          text: `Инвентарный номер «${type}» — можно оставить пустым и указать перед применением варианта` }))?.trim()
        edits.push({ kind: 'place', type_id: op.item, floor_id: k.floors.get(op.floor), x: op.at[0], y: op.at[1], angle: op.angle ?? 0,
          inventory_no: number || null, note: op.note ?? '' })
        after.push({ op, was: null })
        continue
      }
      const was = variantItems.get(op.id)!
      const who = was.asset_id ? { asset_id: was.asset_id, version: was.version } : { op_id: was.op_id }
      if (op.op === 'delete') edits.push({ kind: 'remove', ...who })
      else {
        if ('at' in op || 'angle' in op || 'floor' in op) {
          const at = op.at ?? was.at
          edits.push({ kind: 'move', ...who, floor_id: k.floors.get(op.floor ?? was.floor), x: at[0], y: at[1], angle: op.angle ?? was.angle })
        }
        if ('note' in op) edits.push({ kind: 'note', ...who, note: op.note ?? '' })
      }
      after.push({ op, was })
    }
    const { results } = await call('POST', `${PLANNING}/variants/${vid}/edits`, { edits })
    let i = 0
    for (const { op, was } of after) {
      if (op.op === 'create') {
        const opId = results[i++].op_id
        variantItems.set(op.id, { vid, layer: op.layer, op_id: opId, floor: op.floor, at: op.at, angle: op.angle ?? 0, note: op.note ?? '' })
        items.push({ ...op, op: undefined, version: 1, layer: op.layer })
        continue
      }
      i += op.op === 'delete' ? 1 : ('at' in op || 'angle' in op || 'floor' in op ? 1 : 0) + ('note' in op ? 1 : 0)
      if (op.op === 'delete') { variantItems.delete(op.id); continue }
      const now = { ...was, floor: op.floor ?? was.floor, at: op.at ?? was.at, angle: op.angle ?? was.angle, note: op.note ?? was.note }
      variantItems.set(op.id, now)
      items.push({ id: op.id, version: 1, layer: was.layer, geom: 'point', floor: now.floor, item: op.item ?? undefined,
        at: now.at, angle: now.angle, note: now.note })
    }
  }
  return items
}

/** Two variants (or the fact and a variant) compared, as the viewer's comparison of layers. */
async function compareVariants(building: string, a: string, b: string): Promise<Json> {
  const side = (l: string) => (l.startsWith(VARIANT) ? variantOfLayer(l) : 'fact')
  const [cmp, list] = await Promise.all([call('GET', `${PLANNING}/compare?building_id=${building}&a=${side(a)}&b=${side(b)}`),
    variantsOf(building)])
  const layers = [...assetsLayers(), ...list.flatMap(variantLayers)]
  const floorOf = new Map<string, { drawing: string; name: string; floor: string }>()
  for (const [drawing, k] of known) for (const [candidate, floor] of k.floors) floorOf.set(floor, { drawing, name: '', floor: candidate })
  return {
    a: layers.find((l) => l.id === a) ?? assetsLayer(), b: layers.find((l) => l.id === b) ?? assetsLayer(),
    counts: cmp.counts,
    objects: (cmp.objects as Json[]).map((o) => {
      const f = floorOf.get(o.floor_id)
      return { key: o.key, change: o.change, what: o.what, id_a: o.change === 'added' ? null : o.key, id_b: o.change === 'removed' ? null : o.key,
        item: o.type_id, name: `${o.name}${o.inventory_no ? ` · ${o.inventory_no}` : ''}`, geom: 'point', drawing_id: f?.drawing ?? '',
        drawing: '', floor: f?.floor ?? '', floor_name: '', room: '', at: o.at,
        ...(o.from ? { from: { drawing_id: f?.drawing ?? '', floor: floorOf.get(o.from.floor_id)?.floor ?? '', floor_name: '', room: '', at: o.from.at } } : {}) }
    }),
    items: (cmp.items as Json[]).map((i) => ({ item: i.type_id, name: i.name, category: i.category_id ?? '', price: i.price, currency: i.currency,
      qty_a: i.qty_a, qty_b: i.qty_b, delta: i.delta, sum_a: i.sum_a, sum_b: i.sum_b })),
    totals: cmp.totals,
  }
}

/** What the viewer computes coverage from — a camera's view, a radio's reach, a detector's radius, a light's flux —
 * out of the values of the catalog's property sets «Видеокамера», «Радиосвязь», «Пожарный извещатель», «Светильник». */
function systemParams(v: Json): Json {
  const n = (k: string) => (typeof v[k] === 'number' ? v[k] : undefined)
  const out: Json = {}
  if (n('cam_fov') && n('cam_range')) out.cam = { fov: n('cam_fov'), range: n('cam_range'), ident: n('cam_ident') ?? 0 }
  const params: Json = {}
  if (n('radio_tx') != null && n('radio_range')) params.radio = { tx: n('radio_tx'), range: n('radio_range') }
  if (n('detect_radius')) params.detect = { radius: n('detect_radius') }
  if (n('light_flux')) params.light = { flux: n('light_flux'), power: n('light_power') ?? 0, beam: n('light_beam') ?? 120, cct: n('light_cct') ?? 4000 }
  if (Object.keys(params).length) out.params = params
  return out
}

/** The catalog's types as the viewer's catalog items: size, the procedural shape or the GLB of the type. */
async function catalog(): Promise<Json> {
  const [cats, on, off] = await Promise.all([call('GET', `${CATALOG}/categories`), call('GET', `${CATALOG}/types?active=true`),
    call('GET', `${CATALOG}/types?active=false`)])
  const color = new Map((cats.items as Json[]).map((c) => [c.id, c.color]))
  const items = [...on.items, ...off.items].map((t: Json) => ({
    id: t.id, name: t.name, cat: t.category_id, w: t.size[0], d: t.size[1], h: t.size[2], kind: t.shape || 'device',
    color: t.color ?? color.get(t.category_id) ?? undefined, wall: t.wall_mounted, ceiling: t.ceiling_mounted, elev: t.elevation ?? undefined,
    model: t.model?.name, modelUrl: t.model ? `${CATALOG}/types/${t.id}/model.glb?v=${t.version}` : undefined,
    modelRot: t.model?.rotation ?? 0, article: t.article ?? undefined, supplier: t.supplier ?? undefined,
    price: t.price ?? undefined, currency: t.currency ?? undefined, active: t.active, ...systemParams(t.values ?? {}),
  }))
  return { categories: (cats.items as Json[]).map((c) => ({ id: c.id, name: c.name, color: c.color })), items }
}

/** An object of the assets service as a placed item of the viewer, under the id the viewer knows it by. */
function objectOut(a: Json, floor: string, id = viewerIds.get(a.id) ?? a.id): Json {
  objectInfo.set(a.id, { number: a.inventory_no, card: `#/b/${a.building_id}/assets/${a.id}` })
  return { id, version: a.version, layer: layerOf(a.category_id), geom: 'point', floor, item: a.type_id, at: [a.x, a.y],
    angle: ((a.angle ?? 0) + 360) % 360, note: a.note ?? '', ...(a.elevation != null ? { elev: a.elevation } : {}) }
}

/** The objects standing on the floors of the drawing (those in containers stand with their container). */
async function objects(id: string): Promise<Json[]> {
  const k = known.get(id)!
  const out: Json[] = []
  for (const [candidate, floor] of k.floors) {
    for (let cursor: number | null = 0; cursor != null;) {
      const page: Json = await call('GET', `${ASSETS}/assets?floor_id=${floor}&limit=500&cursor=${cursor}`)
      for (const a of page.items) if (a.x != null && !a.container_id) out.push(objectOut(a, candidate))
      cursor = page.next
    }
  }
  return out
}

const refuse = (detail: string) => new Failed(json({ detail }, 422))

/** How the inventory number of a new object is asked: the editor shows its own dialog (scene/ui/NumberAsk.tsx);
 * the browser's prompt is only the fallback — a browser may be told to stop showing it, and then every object
 * dropped would vanish. `null` — not placed. */
export type NumberQuestion = { title: string; text: string; suggestion: string; optional: boolean
  /** numbers free in the whole system, from the assets service: for one who has none at hand */
  generate: () => Promise<string> }
let askNumber: (q: NumberQuestion) => Promise<string | null> = async (q) => window.prompt(q.text, q.suggestion)
export function setNumberAsker(ask: typeof askNumber): () => void {
  const before = askNumber
  askNumber = ask
  return () => { askNumber = before }
}

/** The next number for a new object of a type: after the last one given in this building (КР-0007 → КР-0008). */
/** Free numbers for `count` new objects of a type (the assets service checks the whole system); the first one
 * is offered, the rest kept for a row. */
function generator(type: string, count: number): { generate: () => Promise<string>; row: (first: string) => string[] | null } {
  let got: string[] = []
  return {
    generate: async () => { got = (await call('GET', `${ASSETS}/inventory-numbers?type_id=${type}&count=${count}`)).numbers; return got[0] },
    row: (first) => (got[0] === first ? got : null),
  }
}

async function nextNumber(building: string, type: string): Promise<string> {
  try {
    // the numbers of objects written off stay taken too
    const pages = await Promise.all(['', '&state=retired'].map((state) =>
      call('GET', `${ASSETS}/assets?building_id=${building}&type_id=${type}${state}&limit=200`)))
    const items = pages.flatMap((p) => p.items as Json[])
    const numbered = items.map((a) => String(a.inventory_no)).filter((n) => /\d+$/.test(n))
    const last = numbered.sort((a, b) => Number(/(\d+)$/.exec(a)![1]) - Number(/(\d+)$/.exec(b)![1])).pop()
    return last ? inRow(last, 2)[1] : ''
  } catch { return '' }
}

/** «КР-0007» and the next ones: КР-0008, КР-0009… (no number at the end — «-2», «-3» are added). */
export function inRow(first: string, n: number): string[] {
  const m = /^(.*?)(\d+)$/.exec(first)
  if (!m) return [first, ...Array.from({ length: n - 1 }, (_, i) => `${first}-${i + 2}`)]
  return Array.from({ length: n }, (_, i) => `${m[1]}${String(Number(m[2]) + i).padStart(m[2].length, '0')}`)
}

/** The viewer's changes of placed items: a new item is a new object (its inventory number is asked for),
 * a moved or turned one is moved, a note is the object's note. Removing and resizing happen elsewhere. */
async function objectOps(id: string, all: Json[]): Promise<Json> {
  const k = known.get(id)!
  const byFloor = new Map([...k.floors].map(([candidate, floor]) => [floor, candidate]))
  // which are the variants' is decided before any of them is done (a removed item is forgotten)
  const mine = all.filter(isVariantOp)
  const ops = all.filter((op) => !mine.includes(op))
  const deleted = mine.filter((op) => op.op === 'delete').map((op) => op.id)
  const items: Json[] = await variantOps(id, mine)
  if (ops.some((op) => op.op === 'delete')) throw refuse('Объект учёта не удаляется из сцены: списать его можно в карточке объекта')
  // several new at once (a copy, a row): one number asked, the next ones go in a row
  const creates = ops.filter((op) => op.op === 'create')
  let numbers: string[] = []
  if (creates.length) {
    const type = (await call('GET', `${CATALOG}/types/${creates[0].item}`)).name
    const gen = generator(creates[0].item, creates.length)
    const first = (await askNumber({ title: creates.length > 1 ? `Новые объекты: ${creates.length}` : 'Новый объект', optional: false,
      suggestion: await nextNumber(k.building, creates[0].item), generate: gen.generate,
      text: creates.length > 1 ? `Инвентарный номер первого из «${type}» — следующие пойдут подряд` : `Инвентарный номер «${type}»` }))?.trim()
    if (!first) throw refuse('Объект не поставлен: нужен инвентарный номер')
    numbers = gen.row(first) ?? inRow(first, creates.length)
  }
  for (const op of ops) {
    const server = objectIds.get(op.id) ?? op.id
    if (op.op === 'create') {
      const number = numbers.shift()!
      const a = await call('POST', `${ASSETS}/assets`, { type_id: op.item, floor_id: k.floors.get(op.floor), x: op.at[0], y: op.at[1],
        angle: op.angle ?? 0, inventory_no: number, note: op.note ?? '' })
      objectIds.set(op.id, a.id)
      viewerIds.set(a.id, op.id)
      items.push(objectOut(a, op.floor, op.id))
      continue
    }
    if ('item' in op || 'size' in op) throw refuse('Тип и размер объекта задаёт каталог; тип меняется в карточке объекта')
    let a: Json = await call('GET', `${ASSETS}/assets/${server}`)
    if (a.version !== op.version) {
      throw new Failed(json({ detail: 'Объект изменил кто-то другой', conflicts: [{ id: op.id, current: objectOut(a, byFloor.get(a.floor_id) ?? '', op.id) }] }, 409))
    }
    if ('at' in op || 'angle' in op || 'floor' in op || 'elev' in op) {
      const at = op.at ?? [a.x, a.y]
      a = await call('POST', `${ASSETS}/assets/${server}/move`, { floor_id: op.floor ? k.floors.get(op.floor) : a.floor_id,
        x: at[0], y: at[1], angle: op.angle ?? a.angle ?? 0, elevation: 'elev' in op ? op.elev : a.elevation, version: a.version })
    }
    if ('note' in op) a = await call('PATCH', `${ASSETS}/assets/${server}`, { note: op.note ?? '', version: a.version })
    items.push(objectOut(a, byFloor.get(a.floor_id) ?? op.floor ?? '', op.id))
  }
  return { items, deleted }
}

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
  // the drawing with the 2D editor's corrections; with `objects` — and the objects of accounting on its floors as
  // blocks with attributes (the gateway's report gathers their numbers, states, people and rooms)
  ['GET', /^\/api\/drawings\/([^/]+)\/drawing\.(dxf|dwg)$/, async (m, _, url) => {
    if (!url.searchParams.has('objects')) {
      const r = await real(`${IMPORT}/drawings/${m[1]}/export?format=${m[2]}`)
      return r.ok ? r : failure(r)
    }
    const k = known.get(m[1]) ?? (await job(m[1]), known.get(m[1])!)
    const r = await real(`/api/reports/buildings/${k.building}/drawing`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ drawing_id: m[1], format: m[2] }) })
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
  ['GET', /^\/api\/drawings\/([^/]+)\/objects$/, async (m) => {
    if (!known.has(m[1])) await job(m[1])
    const k = known.get(m[1])!
    const variants = admin ? await variantsOf(k.building) : []
    return { build: k.n, items: [...await objects(m[1]), ...await variantObjects(m[1], variants)] }
  }],
  ['POST', /^\/api\/drawings\/([^/]+)\/objects:batch$/, async (m, init) => {
    if (!known.has(m[1])) await job(m[1])
    return objectOps(m[1], JSON.parse(String(init?.body)).ops)
  }],
  ['GET', /^\/api\/projects\/([^/]+)\/layers$/, async (m) => [...assetsLayers(), ...(admin ? (await variantsOf(m[1])).flatMap(variantLayers) : [])]],
  ['GET', /^\/api\/projects\/([^/]+)\/layers\/compare$/, (m, _, url) =>
    compareVariants(m[1], url.searchParams.get('a') ?? LAYER, url.searchParams.get('b') ?? LAYER)],
  ['PATCH', /^\/api\/projects\/([^/]+)\/layers\/([^/]+)$/, async (m, init) => {
    const list = admin ? await variantsOf(m[1]) : []
    const layer = [...assetsLayers(), ...list.flatMap(variantLayers)].find((l) => l.id === decodeURIComponent(m[2])) ?? assetsLayer()
    return { ...layer, ...JSON.parse(String(init?.body ?? '{}')) }
  }],
  ['GET', /^\/api\/projects\/([^/]+)\/checks$/, () => ({ fire: [] })],
  ['GET', /^\/api\/projects\/([^/]+)\/proposals$/, () => []],
  ['POST', /^\/api\/projects\/([^/]+)\/ui-context$/, () => null],
  ['GET', /^\/api\/layer-kinds$/, layerKinds],
  ['GET', /^\/api\/catalog$/, catalog],
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
