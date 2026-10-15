/**
 * Pieces of a plan: walls taken with their openings and the names of the
 * rooms they close, moved together, copied and put elsewhere — on the same
 * floor or another. A piece put down joins the walls it meets, as walls drawn
 * there would.
 */
import { fitCurves } from './arc.ts'
import { addWall, draft, ends, JOIN_TOL, nodeAt, removeWall, wallAt } from './graph.ts'
import type { Floor, Opening, RoomLabel, Wall } from './model.ts'
import { newId } from './model.ts'
import { addOpening } from './openings.ts'
import { findRooms } from './rooms.ts'
import { add, dist, lerp, type XY } from './vec.ts'

export interface Piece {
  /** each wall by its ends */
  walls: { a: XY; b: XY; props: Omit<Wall, 'a' | 'b'> }[]
  /** each opening by where its middle is and its wall's direction there */
  openings: { at: XY; props: Omit<Opening, 'wall' | 'at'> }[]
  rooms: RoomLabel[]
  /** the curved walls all of whose faces are in the piece, by their ends */
  curves: { id: string; a: XY; b: XY; bulge: number; segments: number }[]
  /** the middle of the piece, to put it down by, and its width and depth */
  center: XY
  size: XY
}

/** The walls given, their openings, and the names of the rooms these walls close all round. */
export function takePiece(f: Floor, wallIds: string[]): Piece | null {
  const ids = wallIds.filter(id => id in f.walls)
  if (!ids.length) return null
  const set = new Set(ids)
  const walls = ids.map(id => {
    const w = f.walls[id]
    const [a, b] = ends(f, w)
    return { a, b, props: { thickness: w.thickness, height: w.height, kind: w.kind, ...(w.curve ? { curve: w.curve } : {}) } }
  })
  const curves = Object.entries(f.curves ?? {})
    .filter(([id]) => Object.entries(f.walls).every(([w, x]) => x.curve !== id || set.has(w)) && ids.some(w => f.walls[w].curve === id))
    .map(([id, c]) => ({ id, a: f.nodes[c.a], b: f.nodes[c.b], bulge: c.bulge, segments: c.segments }))
  for (const w of walls) if (w.props.curve && !curves.some(c => c.id === w.props.curve)) delete w.props.curve
  const openings = Object.values(f.openings).filter(o => set.has(o.wall)).map(o => {
    const [a, b] = ends(f, f.walls[o.wall])
    return { at: lerp(a, b, o.at / dist(a, b)), props: { kind: o.kind, width: o.width, height: o.height, sill: o.sill, hinge: o.hinge, side: o.side } }
  })
  const rooms = findRooms(f).filter(r => r.label && r.walls.every(w => set.has(w)))
    .map(r => ({ at: r.label!.at, name: r.label!.name, number: r.label!.number, type: r.label!.type }))
  const ps = walls.flatMap(w => [w.a, w.b])
  const xs = ps.map(p => p[0]), ys = ps.map(p => p[1])
  return {
    walls, openings, rooms, curves,
    center: [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2],
    size: [Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)],
  }
}

/** The piece put down with its middle at `at`: its walls join those they meet, its openings go into its walls. */
export function putPiece(f: Floor, piece: Piece, at: XY): { floor: Floor; walls: string[]; openings: string[] } {
  const shift: XY = [at[0] - piece.center[0], at[1] - piece.center[1]]
  let floor = f
  const made: string[] = []
  // a curved wall put down is a new curve
  const renamed: Record<string, string> = {}
  if (piece.curves?.length) {
    const d = draft(floor)
    d.curves = { ...f.curves }
    for (const c of piece.curves) {
      const id = newId(d.curves)
      renamed[c.id] = id
      d.curves[id] = { a: '', b: '', bulge: c.bulge, segments: c.segments }
    }
    floor = d
  }
  for (const w of piece.walls) {
    const props = w.props.curve ? { ...w.props, curve: renamed[w.props.curve] } : w.props
    const r = addWall(floor, add(w.a, shift), add(w.b, shift), props)
    floor = r.floor
    made.push(...r.walls)
  }
  const openings: string[] = []
  for (const o of piece.openings) {
    const p = add(o.at, shift)
    const on = wallAt(floor, p, JOIN_TOL * 2)
    if (!on) continue
    const [a, b] = ends(floor, floor.walls[on.id])
    const r = addOpening(floor, on.id, on.t * dist(a, b), o.props.kind, o.props)
    if (r) { floor = r.floor; openings.push(r.id) }
  }
  if (piece.curves?.length) {
    const d = draft(floor)
    d.curves = { ...floor.curves }
    for (const c of piece.curves) {
      const id = renamed[c.id]
      const a = nodeAt(d, add(c.a, shift)), b = nodeAt(d, add(c.b, shift))
      if (a && b) d.curves[id] = { ...d.curves[id], a, b }
      else {
        delete d.curves[id]
        for (const [w, x] of Object.entries(d.walls)) if (x.curve === id) { const { curve: _, ...rest } = x; d.walls[w] = rest }
      }
    }
    floor = d
  }
  if (piece.rooms.length) {
    const d = draft(floor)
    for (const r of piece.rooms) d.rooms[newId(d.rooms)] = { ...r, at: add(r.at, shift) }
    floor = d
  }
  return { floor, walls: made.filter(id => id in floor.walls), openings }
}

/** The nodes moved together by `delta` (walls between them move whole, walls to others stretch). */
export function moveNodes(f: Floor, nodes: string[], delta: XY): Floor {
  const d = draft(f)
  for (const n of nodes) if (n in d.nodes) d.nodes[n] = add(d.nodes[n], delta)
  fitCurves(d)
  return d
}

/** The nodes of the walls given. */
export function nodesOf(f: Floor, wallIds: string[]): string[] {
  return [...new Set(wallIds.filter(id => id in f.walls).flatMap(id => [f.walls[id].a, f.walls[id].b]))]
}

/** The walls given taken away, with their openings; walls left in line join again. */
export function removeWalls(f: Floor, wallIds: string[]): Floor {
  return wallIds.reduce((floor, id) => removeWall(floor, id), f)
}

/** The walls whose both ends lie in the box [x0, y0, x1, y1]. */
export function wallsInBox(f: Floor, box: [number, number, number, number]): string[] {
  const [x0, y0, x1, y1] = box
  const inside = (p: XY) => p[0] >= x0 && p[0] <= x1 && p[1] >= y0 && p[1] <= y1
  return Object.keys(f.walls).filter(id => inside(f.nodes[f.walls[id].a]) && inside(f.nodes[f.walls[id].b]))
}
