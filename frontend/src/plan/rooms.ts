/**
 * Rooms: the closed faces of the wall graph, bounded by the wall faces that
 * look into them.
 *
 * Every wall is two half-edges, a→b and b→a. Walking from a half-edge to the
 * next one clockwise at its end node goes round a face keeping it on the left:
 * faces with a positive area (counter-clockwise) are rooms, the others are the
 * outside of a group of connected walls. A group standing inside a room
 * (a column of walls, a free wall) is a hole in that room.
 *
 * A room takes its name from the label (`floor.rooms`) whose point lies in it.
 */
import { columnRing } from './elements.ts'
import { draft } from './graph.ts'
import { newId, type Floor, type RoomLabel } from './model.ts'
import { outlines, type WallOutline } from './outline.ts'
import { angle, dist, dot, EPS, inRing, signedArea, sub, type XY } from './vec.ts'

export interface Room {
  /** the label's id when the room has one, otherwise made from its walls (changes as they are edited) */
  key: string
  label: (RoomLabel & { id: string }) | null
  /** the inner outline, counter-clockwise */
  contour: XY[]
  holes: XY[][]
  /** m², the holes taken out */
  area: number
  /** the centre-line outline */
  axis: XY[]
  walls: string[]
  /** a point well inside, for the name and the area */
  labelAt: XY
  /** more than one label lies in the room: all but the first are ignored */
  extraLabels: string[]
}

interface Half { wall: string; from: string; to: string; fwd: boolean; dir: number }

interface Face {
  halves: Half[]
  axis: XY[]
  contour: XY[]
  area: number
  /** how far the wall faces run along the walk, summed: below zero the walls fill the face and turn its outline inside out */
  run: number
}

function faces(f: Floor, lines: Record<string, WallOutline>): Face[] {
  const out: Record<string, Half[]> = {}
  for (const [id, w] of Object.entries(f.walls)) {
    const a = f.nodes[w.a], b = f.nodes[w.b]
    ;(out[w.a] ??= []).push({ wall: id, from: w.a, to: w.b, fwd: true, dir: angle(sub(b, a)) })
    ;(out[w.b] ??= []).push({ wall: id, from: w.b, to: w.a, fwd: false, dir: angle(sub(a, b)) })
  }
  for (const list of Object.values(out)) list.sort((x, y) => x.dir - y.dir)
  const next = (h: Half): Half => {
    const list = out[h.to]
    const i = list.findIndex(x => x.wall === h.wall && x.to === h.from)
    return list[(i - 1 + list.length) % list.length]
  }
  const seen = new Set<Half>()
  const result: Face[] = []
  for (const list of Object.values(out))
    for (const start of list) {
      if (seen.has(start)) continue
      const halves: Half[] = []
      for (let h = start; !seen.has(h); h = next(h)) { seen.add(h); halves.push(h) }
      const axis = halves.map(h => f.nodes[h.from])
      const contour: XY[] = []
      let run = 0
      for (const h of halves) {
        const o = lines[h.wall]
        // the wall face on the left of the walk
        const [p0, p1] = h.fwd ? [o.aPlus, o.bPlus] : [o.bMinus, o.aMinus]
        run += dot(sub(p1, p0), sub(f.nodes[h.to], f.nodes[h.from])) / dist(f.nodes[h.to], f.nodes[h.from])
        for (const p of [p0, p1])
          if (!contour.length || dist(contour[contour.length - 1], p) > EPS) contour.push(p)
      }
      if (contour.length > 1 && dist(contour[0], contour[contour.length - 1]) <= EPS) contour.pop()
      result.push({ halves, axis, contour, area: signedArea(axis), run })
    }
  return result
}

/**
 * A point well inside the ring and outside the holes: the middle of the widest
 * horizontal run; of runs about as wide, the one nearest the middle height.
 */
function insidePoint(contour: XY[], holes: XY[][]): XY {
  const ys = contour.map(p => p[1])
  const y0 = Math.min(...ys), y1 = Math.max(...ys), ym = (y0 + y1) / 2
  let best: XY = contour[0], bestW = -1
  for (let k = 1; k < 16; k++) {
    const y = y0 + ((y1 - y0) * k) / 16
    const xs: number[] = []
    for (const ring of [contour, ...holes])
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i], [xj, yj] = ring[j]
        if (yi > y !== yj > y) xs.push(xi + ((y - yi) * (xj - xi)) / (yj - yi))
      }
    xs.sort((a, b) => a - b)
    for (let i = 0; i + 1 < xs.length; i += 2) {
      const w = xs[i + 1] - xs[i]
      if (w > bestW * 1.05 || (w >= bestW * 0.95 && Math.abs(y - ym) < Math.abs(best[1] - ym))) {
        bestW = Math.max(w, bestW)
        best = [(xs[i] + xs[i + 1]) / 2, y]
      }
    }
  }
  return best
}

export function findRooms(f: Floor, lines: Record<string, WallOutline> = outlines(f)): Room[] {
  const all = faces(f, lines)
  // a face the walls fill entirely (the inside of a thick box) has its outline inside out: no room
  const inner = all.filter(x => x.area > EPS && x.run > EPS && signedArea(x.contour) > EPS)
  const outer = all.filter(x => x.area <= EPS && x.contour.length >= 3)
  const holes = new Map<Face, XY[][]>(inner.map(r => [r, []]))
  for (const o of outer) {
    // the smallest room around this group of walls
    const p = o.contour[0]
    const around = inner.filter(r => !r.halves.some(h => o.halves.some(g => g.wall === h.wall)) && inRing(p, r.contour))
      .sort((x, y) => x.area - y.area)[0]
    if (around) holes.get(around)!.push(o.contour)
  }
  // a column standing in a room is a hole in it, as a free-standing wall is
  for (const c of Object.values(f.columns ?? {})) {
    const ring = columnRing(c)
    const around = inner.filter(r => inRing(c.at, r.contour) && !holes.get(r)!.some(h => inRing(c.at, h)))
      .sort((x, y) => x.area - y.area)[0]
    if (around) holes.get(around)!.push(ring)
  }
  const labels = Object.entries(f.rooms).sort(([x], [y]) => (x < y ? -1 : 1))
  return inner.map(face => {
    const hs = holes.get(face)!
    const contour = face.contour
    const area = Math.abs(signedArea(contour)) - hs.reduce((s, h) => s + Math.abs(signedArea(h)), 0)
    const inside = labels.filter(([, l]) => inRing(l.at, contour) && !hs.some(h => inRing(l.at, h)))
    const walls = [...new Set(face.halves.map(h => h.wall))]
    const label = inside.length ? { id: inside[0][0], ...inside[0][1] } : null
    return {
      key: label ? label.id : `auto:${[...walls].sort()[0]}`,
      label, contour, holes: hs, area, axis: face.axis, walls,
      labelAt: insidePoint(contour, hs),
      extraLabels: inside.slice(1).map(([id]) => id),
    }
  })
}

/** Names the room: changes its label, or puts a new one at a point inside it. */
export function labelRoom(f: Floor, room: Room, patch: Partial<Omit<RoomLabel, 'at'>>): { floor: Floor; id: string } {
  const d = draft(f)
  if (room.label) {
    d.rooms[room.label.id] = { ...d.rooms[room.label.id], ...patch }
    return { floor: d, id: room.label.id }
  }
  const id = newId(d.rooms)
  d.rooms[id] = { at: room.labelAt, name: '', number: '', type: null, ...patch }
  return { floor: d, id }
}

/** Labels that lie in no room (their room was taken apart): the editor offers to drop them. */
export function strayLabels(f: Floor, rooms: Room[]): string[] {
  const used = new Set(rooms.flatMap(r => (r.label ? [r.label.id, ...r.extraLabels] : r.extraLabels)))
  return Object.keys(f.rooms).filter(id => !used.has(id))
}
