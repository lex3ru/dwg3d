/**
 * A plan drawn from scratch: the native model of the 2D plan editor.
 *
 * Walls are a graph. Nodes are the points where walls end or meet; a wall is
 * the centre line between two nodes with its own thickness, so moving a node
 * moves the end of every wall that meets there. Where walls cross or one ends
 * on another, the graph has a node: rooms are found as the closed faces of this
 * graph (see rooms.ts) and are not stored, only their names (`rooms` keeps a
 * label point per named room).
 *
 * An opening belongs to a wall and is placed by the distance of its centre from
 * the wall's node `a`.
 *
 * Plan coordinates in meters, Y up, as everywhere in the building.
 */
import type { XY } from './vec.ts'

export const SKETCH_VERSION = 1

export type WallKind = 'bearing' | 'partition'
export type OpeningKind = 'door' | 'window' | 'vitrage' | 'passage'

export interface Wall {
  a: string
  b: string
  thickness: number
  /** null: the floor's height */
  height: number | null
  kind: WallKind
}

export interface Opening {
  wall: string
  kind: OpeningKind
  /** distance of the centre from the wall's node `a` along the centre line */
  at: number
  width: number
  height: number
  /** from the floor to the bottom of the opening */
  sill: number
  /** the end of the opening the leaf hangs on: towards node `a` or `b` */
  hinge: 'a' | 'b'
  /** where the leaf opens, looking from `a` to `b` */
  side: 'left' | 'right'
}

export interface RoomLabel {
  /** a point inside the room: the label belongs to the room that contains it */
  at: XY
  name: string
  number: string
  type: string | null
}

/** A picture of a plan under the floor to draw over: where its bottom-left corner lies and how many meters a pixel is. */
export interface Underlay {
  /** the picture's name in the drawing's store (import: /drawings/{id}/underlays/{image}) */
  image: string
  at: XY
  /** meters per pixel */
  scale: number
  /** pixels */
  width: number
  height: number
  opacity: number
  hidden: boolean
}

export interface Floor {
  id: string
  name: string
  level: number
  /** meters */
  elevation: number
  height: number
  nodes: Record<string, XY>
  walls: Record<string, Wall>
  openings: Record<string, Opening>
  rooms: Record<string, RoomLabel>
  underlay?: Underlay | null
}

export interface Sketch {
  version: typeof SKETCH_VERSION
  floors: Floor[]
}

export const WALL_DEFAULTS: Record<WallKind, Pick<Wall, 'thickness' | 'height' | 'kind'>> = {
  bearing: { thickness: 0.25, height: null, kind: 'bearing' },
  partition: { thickness: 0.1, height: null, kind: 'partition' },
}

export const OPENING_DEFAULTS: Record<OpeningKind, Pick<Opening, 'width' | 'height' | 'sill'>> = {
  door: { width: 0.9, height: 2.1, sill: 0 },
  window: { width: 1.2, height: 1.5, sill: 0.8 },
  vitrage: { width: 2.0, height: 2.4, sill: 0 },
  passage: { width: 0.9, height: 2.1, sill: 0 },
}

export const FLOOR_HEIGHT = 2.7

/** A short id not yet taken in `taken`. */
export function newId(taken: Record<string, unknown> = {}): string {
  const b = new Uint8Array(5)
  for (;;) {
    crypto.getRandomValues(b)
    const id = Array.from(b, x => x.toString(16).padStart(2, '0')).join('')
    if (!(id in taken)) return id
  }
}

export function emptyFloor(level = 1, patch: Partial<Floor> = {}): Floor {
  return {
    id: newId(), name: `Этаж ${level}`, level, elevation: (level - 1) * FLOOR_HEIGHT, height: FLOOR_HEIGHT,
    nodes: {}, walls: {}, openings: {}, rooms: {}, ...patch,
  }
}

export function emptySketch(): Sketch {
  return { version: SKETCH_VERSION, floors: [emptyFloor()] }
}

// ------------------------------------------------------------- reading

export class SketchError extends Error {}

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)

function fail(path: string, what: string): never {
  throw new SketchError(`${path}: ${what}`)
}
function obj(v: unknown, path: string): Obj {
  return isObj(v) ? v : fail(path, 'ожидался объект')
}
function num(v: unknown, path: string, min = -Infinity): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) fail(path, 'ожидалось число')
  if (v < min) fail(path, `не меньше ${min}`)
  return v
}
function str(v: unknown, path: string): string {
  return typeof v === 'string' ? v : fail(path, 'ожидалась строка')
}
function oneOf<T extends string>(v: unknown, path: string, values: readonly T[]): T {
  return values.includes(v as T) ? (v as T) : fail(path, `одно из: ${values.join(', ')}`)
}
function xy(v: unknown, path: string): XY {
  if (!Array.isArray(v) || v.length !== 2) fail(path, 'ожидалась точка [x, y]')
  return [num(v[0], `${path}[0]`), num(v[1], `${path}[1]`)]
}
function map<T>(v: unknown, path: string, item: (x: unknown, p: string) => T): Record<string, T> {
  const out: Record<string, T> = {}
  for (const [k, x] of Object.entries(obj(v, path))) out[k] = item(x, `${path}.${k}`)
  return out
}

const WALL_KINDS = ['bearing', 'partition'] as const
const OPENING_KINDS = ['door', 'window', 'vitrage', 'passage'] as const

function readFloor(v: unknown, path: string): Floor {
  const o = obj(v, path)
  const f: Floor = {
    id: str(o.id, `${path}.id`),
    name: str(o.name, `${path}.name`),
    level: num(o.level, `${path}.level`),
    elevation: num(o.elevation, `${path}.elevation`),
    height: num(o.height, `${path}.height`, 0.5),
    nodes: map(o.nodes, `${path}.nodes`, xy),
    walls: map(o.walls, `${path}.walls`, (x, p) => {
      const w = obj(x, p)
      return {
        a: str(w.a, `${p}.a`), b: str(w.b, `${p}.b`),
        thickness: num(w.thickness, `${p}.thickness`, 0.01),
        height: w.height === null ? null : num(w.height, `${p}.height`, 0.1),
        kind: oneOf(w.kind, `${p}.kind`, WALL_KINDS),
      }
    }),
    openings: map(o.openings, `${path}.openings`, (x, p) => {
      const d = obj(x, p)
      return {
        wall: str(d.wall, `${p}.wall`), kind: oneOf(d.kind, `${p}.kind`, OPENING_KINDS),
        at: num(d.at, `${p}.at`), width: num(d.width, `${p}.width`, 0.1),
        height: num(d.height, `${p}.height`, 0.1), sill: num(d.sill, `${p}.sill`, 0),
        hinge: oneOf(d.hinge, `${p}.hinge`, ['a', 'b'] as const),
        side: oneOf(d.side, `${p}.side`, ['left', 'right'] as const),
      }
    }),
    rooms: map(o.rooms, `${path}.rooms`, (x, p) => {
      const r = obj(x, p)
      return {
        at: xy(r.at, `${p}.at`), name: str(r.name, `${p}.name`), number: str(r.number, `${p}.number`),
        type: r.type === null ? null : str(r.type, `${p}.type`),
      }
    }),
  }
  if (o.underlay != null) {
    const u = obj(o.underlay, `${path}.underlay`), p = `${path}.underlay`
    f.underlay = {
      image: str(u.image, `${p}.image`), at: xy(u.at, `${p}.at`), scale: num(u.scale, `${p}.scale`, 1e-6),
      width: num(u.width, `${p}.width`, 1), height: num(u.height, `${p}.height`, 1),
      opacity: num(u.opacity, `${p}.opacity`, 0), hidden: u.hidden === true,
    }
  }
  for (const [id, w] of Object.entries(f.walls)) {
    if (!(w.a in f.nodes) || !(w.b in f.nodes)) fail(`${path}.walls.${id}`, 'конец стены ссылается на несуществующий узел')
    if (w.a === w.b) fail(`${path}.walls.${id}`, 'стена начинается и кончается в одном узле')
  }
  for (const [id, d] of Object.entries(f.openings))
    if (!(d.wall in f.walls)) fail(`${path}.openings.${id}`, 'проём ссылается на несуществующую стену')
  return f
}

/**
 * Reads a sketch from untrusted JSON (the server, a file): checks the shape and
 * that every reference resolves. Geometric problems (walls crossing without a
 * node, an opening off its wall) are not errors here: see `checkFloor`.
 */
export function parseSketch(v: unknown): Sketch {
  const o = obj(v, 'sketch')
  if (o.version !== SKETCH_VERSION) fail('sketch.version', `поддерживается версия ${SKETCH_VERSION}`)
  if (!Array.isArray(o.floors)) fail('sketch.floors', 'ожидался список')
  const floors = o.floors.map((f, i) => readFloor(f, `sketch.floors[${i}]`))
  const ids = new Set(floors.map(f => f.id))
  if (ids.size !== floors.length) fail('sketch.floors', 'идентификаторы этажей повторяются')
  return { version: SKETCH_VERSION, floors }
}
