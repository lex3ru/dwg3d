import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { checkFloor } from './check.ts'
import { offsetPolyline, wallsFromFaces } from './faces.ts'
import { addChain, addWall, bearingOnly, moveNode, removeWall, setWallLength, splitWall, wallLength, wallsAt } from './graph.ts'
import { emptyFloor, emptySketch, parseSketch, WALL_DEFAULTS, type Floor } from './model.ts'
import { addOpening, fitOpening, moveOpening, openingRect, setOpening } from './openings.ts'
import { allSides, outlines } from './outline.ts'
import { findRooms, labelRoom, strayLabels } from './rooms.ts'
import type { XY } from './vec.ts'

const P = WALL_DEFAULTS.partition // 10 cm
const B = WALL_DEFAULTS.bearing // 25 cm
const near = (x: number, y: number, eps = 1e-6) => assert.ok(Math.abs(x - y) < eps, `${x} ≠ ${y}`)
const nearXY = (p: XY, q: XY) => { near(p[0], q[0]); near(p[1], q[1]) }
const count = (f: Floor) => [Object.keys(f.nodes).length, Object.keys(f.walls).length]
const box = (w: number, h: number, props = P, f = emptyFloor(), x = 0, y = 0) =>
  addChain(f, [[x, y], [x + w, y], [x + w, y + h], [x, y + h]], props, true).floor

describe('wall graph', () => {
  test('a closed chain is four walls on four nodes', () => {
    assert.deepEqual(count(box(4, 3)), [4, 4])
  })

  test('a wall ending on another cuts it there', () => {
    const f = addWall(box(4, 3), [2, 0], [2, 3], P).floor
    assert.deepEqual(count(f), [6, 7])
    const mid = Object.keys(f.nodes).find(n => f.nodes[n][0] === 2 && f.nodes[n][1] === 0)!
    assert.equal(wallsAt(f, mid).length, 3)
  })

  test('crossing walls get a node where they cross', () => {
    let f = addWall(emptyFloor(), [0, 0], [4, 0], P).floor
    const r = addWall(f, [2, -1], [2, 1], P)
    f = r.floor
    assert.equal(r.walls.length, 2)
    assert.deepEqual(count(f), [5, 4])
  })

  test('a wall drawn along an existing one is not doubled', () => {
    let f = addWall(emptyFloor(), [0, 0], [4, 0], P).floor
    const r = addWall(f, [2, 0], [6, 0], P)
    f = r.floor
    assert.equal(r.walls.length, 1)
    assert.deepEqual(count(f), [4, 3])
    assert.deepEqual(checkFloor(f), [])
  })

  test('ends closer than 5 mm join', () => {
    const f = addChain(emptyFloor(), [[0, 0], [4, 0], [4, 3], [0.003, 0.002]], P).floor
    assert.deepEqual(count(f), [3, 3])
    assert.equal(findRooms(f).length, 1)
  })

  test('removing a wall drops lonely nodes and joins walls left in line', () => {
    let f = addWall(box(4, 3), [2, 0], [2, 3], P).floor
    const divider = Object.keys(f.walls).find(id => {
      const w = f.walls[id]
      return f.nodes[w.a][0] === 2 && f.nodes[w.b][0] === 2
    })!
    f = removeWall(f, divider)
    assert.deepEqual(count(f), [4, 4])
  })

  test('walls of different thickness are not joined', () => {
    let f = addWall(emptyFloor(), [0, 0], [2, 0], P).floor
    f = addWall(f, [2, 0], [4, 0], B).floor
    f = addWall(f, [2, 0], [2, 2], P).floor
    const stub = Object.keys(f.walls).find(id => f.nodes[f.walls[id].b][1] === 2)!
    assert.deepEqual(count(removeWall(f, stub)), [3, 2])
  })

  test('a wall length is set by moving its far end', () => {
    const f0 = addWall(emptyFloor(), [0, 0], [3, 4], P)
    const f = setWallLength(f0.floor, f0.walls[0], 10)
    near(wallLength(f, f0.walls[0]), 10)
    nearXY(f.nodes[f.walls[f0.walls[0]].b], [6, 8])
  })

  test('a node dropped on another merges with it', () => {
    let f = addChain(emptyFloor(), [[0, 0], [4, 0], [4, 3], [0, 3.5]], P).floor
    const loose = Object.keys(f.nodes).find(n => f.nodes[n][1] === 3.5)!
    f = moveNode(f, loose, [0.001, 0], true)
    assert.deepEqual(count(f), [3, 3])
    assert.equal(findRooms(f).length, 1)
  })

  test('edits leave the floor they were given unchanged', () => {
    const f = box(4, 3)
    const before = JSON.stringify(f)
    addWall(f, [2, 0], [2, 3], P)
    removeWall(f, Object.keys(f.walls)[0])
    moveNode(f, Object.keys(f.nodes)[0], [9, 9])
    assert.equal(JSON.stringify(f), before)
  })
})

describe('drawing by faces', () => {
  const inner: XY[] = [[0, 0], [4, 0], [4, 3], [0, 3]]

  test('a room drawn by its inner faces is as big as drawn, the walls outside', () => {
    for (const pts of [inner, [...inner].reverse()]) {                  // either way round
      const axis = wallsFromFaces(pts, 0.2, true)
      const f = addChain(emptyFloor(), axis, { ...P, thickness: 0.2 }, true).floor
      const [room] = findRooms(f)
      near(room.area, 12)
      const xs = axis.map(p => p[0]).sort((a, b) => a - b)
      near(xs[0], -0.1); near(xs[3], 4.1)
    }
  })

  test('the inner faces measure what was drawn', () => {
    const f = addChain(emptyFloor(), wallsFromFaces(inner, 0.25, true), B, true).floor
    const inside = Object.values(allSides(f)).map(s => Math.min(s.plus, s.minus)).sort((a, b) => a - b)
    inside.forEach((v, i) => near(v, [3, 3, 4, 4][i]))
  })

  test('an open line has its walls on the side asked', () => {
    const right = wallsFromFaces([[0, 0], [4, 0], [4, 3]], 0.2, false, 'right')
    nearXY(right[0], [0, -0.1]); nearXY(right[1], [4.1, -0.1]); nearXY(right[2], [4.1, 3])
    const left = wallsFromFaces([[0, 0], [4, 0]], 0.2, false, 'left')
    nearXY(left[0], [0, 0.1])
  })

  test('points in line stay in line', () => {
    const o = offsetPolyline([[0, 0], [2, 0], [4, 0]], 1, false)
    nearXY(o[1], [2, 1])
  })
})

describe('the floor above', () => {
  test('starts with the bearing walls below, whole where partitions cut them', () => {
    let f = box(4, 3, B)
    f = addWall(f, [2, 0], [2, 3], P).floor                    // cuts the long bearing walls in two
    f = addOpening(f, Object.keys(f.walls)[0], 0.8, 'window')!.floor
    f = labelRoom(f, findRooms(f)[0], { name: 'Кухня' }).floor
    const up = bearingOnly(f)
    assert.deepEqual(count(up), [4, 4])
    assert.ok(Object.values(up.walls).every(w => w.kind === 'bearing'))
    assert.deepEqual(up.openings, {})
    assert.deepEqual(up.rooms, {})
    near(findRooms(up)[0].area, 3.75 * 2.75)
  })
})

describe('outlines', () => {
  test('a rectangle measures 4.1 outside and 3.9 inside', () => {
    const f = box(4, 3)
    const sides = Object.values(allSides(f))
    const long = sides.filter(s => Math.abs(s.center - 4) < 1e-9)
    assert.equal(long.length, 2)
    for (const s of long) {
      near(Math.max(s.plus, s.minus), 4.1)
      near(Math.min(s.plus, s.minus), 3.9)
    }
  })

  test('two walls at a corner share their corner points', () => {
    const f = addChain(emptyFloor(), [[0, 0], [4, 0], [4, 3]], P).floor
    const o = outlines(f)
    const [w1, w2] = Object.keys(f.walls).sort((x, y) => f.nodes[f.walls[x].a][1] - f.nodes[f.walls[y].a][1])
    // w1 runs east, w2 north: the inner corner is at (3.95, 0.05), the outer at (4.05, -0.05)
    nearXY(o[w1].bPlus, [3.95, 0.05])
    nearXY(o[w2].aPlus, [3.95, 0.05])
    nearXY(o[w1].bMinus, [4.05, -0.05])
    nearXY(o[w2].aMinus, [4.05, -0.05])
  })

  test('a wall alone ends square', () => {
    const r = addWall(emptyFloor(), [0, 0], [2, 0], B)
    const o = outlines(r.floor)[r.walls[0]]
    nearXY(o.aMinus, [0, -0.125])
    nearXY(o.bPlus, [2, 0.125])
  })

  test('walls in line of different thickness step', () => {
    let f = addWall(emptyFloor(), [0, 0], [2, 0], P).floor
    const r = addWall(f, [2, 0], [4, 0], B)
    f = r.floor
    const o = outlines(f)[r.walls[0]]
    nearXY(o.aPlus, [2, 0.125])
  })

  test('a very sharp corner is cut square instead of running out', () => {
    const f = addChain(emptyFloor(), [[0, 0], [4, 0], [0, 0.1]], B).floor
    for (const o of Object.values(outlines(f)))
      for (const p of o.poly) assert.ok(p[0] < 4.5, `corner runs out to ${p[0]}`)
  })
})

describe('rooms', () => {
  test('a closed box is one room measured inside the walls', () => {
    const rooms = findRooms(box(4, 3))
    assert.equal(rooms.length, 1)
    near(rooms[0].area, 3.9 * 2.9)
    assert.equal(rooms[0].walls.length, 4)
  })

  test('the area is inside the walls: centre lines 4.34 × 3.28 at 10 cm are 4.24 × 3.18', () => {
    near(findRooms(box(4.34, 3.28))[0].area, 4.24 * 3.18)
  })

  test('an open chain is no room', () => {
    assert.equal(findRooms(addChain(emptyFloor(), [[0, 0], [4, 0], [4, 3]], P).floor).length, 0)
  })

  test('a divider makes two rooms', () => {
    const rooms = findRooms(addWall(box(4, 3), [1.5, 0], [1.5, 3], P).floor).sort((x, y) => x.area - y.area)
    assert.equal(rooms.length, 2)
    near(rooms[0].area, 1.4 * 2.9)
    near(rooms[1].area, 2.4 * 2.9)
  })

  test('a wall sticking into a room takes its footprint out of the room', () => {
    const f = addWall(box(4, 3), [2, 0], [2, 1], P).floor
    const rooms = findRooms(f)
    assert.equal(rooms.length, 1)
    near(rooms[0].area, 3.9 * 2.9 - 0.1 * 0.95)
  })

  test('a free-standing wall inside a room is a hole in it', () => {
    const f = addWall(box(4, 3), [1, 1.5], [3, 1.5], P).floor
    const rooms = findRooms(f)
    assert.equal(rooms.length, 1)
    assert.equal(rooms[0].holes.length, 1)
    near(rooms[0].area, 3.9 * 2.9 - 2 * 0.1)
  })

  test('a box of walls inside a room: its inside is a room of its own, its walls a hole', () => {
    const f = box(1, 1, P, box(4, 3), 1.5, 1)
    const rooms = findRooms(f).sort((x, y) => x.area - y.area)
    assert.equal(rooms.length, 2)
    near(rooms[0].area, 0.9 * 0.9)
    near(rooms[1].area, 3.9 * 2.9 - 1.1 * 1.1)
  })

  test('a thick box with no space inside is no room', () => {
    const f = box(0.2, 0.2, B, box(4, 3), 1.5, 1)
    const rooms = findRooms(f)
    assert.equal(rooms.length, 1)
    near(rooms[0].area, 3.9 * 2.9 - 0.45 * 0.45)
  })

  test('the name stays with the room when its walls move', () => {
    let f = box(4, 3)
    const named = labelRoom(f, findRooms(f)[0], { name: 'Кухня', number: '101' })
    f = named.floor
    const corner = Object.keys(f.nodes).find(n => f.nodes[n][0] === 4 && f.nodes[n][1] === 3)!
    f = moveNode(f, corner, [5, 3.5])
    const [room] = findRooms(f)
    assert.equal(room.key, named.id)
    assert.equal(room.label?.name, 'Кухня')
  })

  test('a label left outside every room is reported', () => {
    let f = box(4, 3)
    f = labelRoom(f, findRooms(f)[0], { name: 'Кухня' }).floor
    f = removeWall(f, Object.keys(f.walls)[0])
    assert.equal(strayLabels(f, findRooms(f)).length, 1)
  })

  test('the label of a plain box is in its middle', () => {
    const [room] = findRooms(box(4, 3))
    assert.ok(Math.abs(room.labelAt[0] - 2) < 1e-9 && Math.abs(room.labelAt[1] - 1.5) < 0.2, String(room.labelAt))
  })

  test('the label point is inside an L-shaped room', () => {
    const f = addChain(emptyFloor(), [[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4]], P, true).floor
    const [room] = findRooms(f)
    const [x, y] = room.labelAt
    assert.ok((x > 0.05 && x < 3.95 && y > 0.05 && y < 0.95) || (x > 0.05 && x < 0.95 && y > 0.05 && y < 3.95))
  })
})

describe('openings', () => {
  const wall = () => addWall(emptyFloor(), [0, 0], [4, 0], P)

  test('a door goes where asked when it fits', () => {
    const { floor, walls } = wall()
    const r = addOpening(floor, walls[0], 1, 'door')!
    near(r.floor.openings[r.id].at, 1)
    near(r.floor.openings[r.id].width, 0.9)
  })

  test('a door is pushed back inside the wall faces', () => {
    let f = box(4, 3)
    const w = Object.keys(f.walls)[0]
    const r = addOpening(f, w, 0, 'door')!
    f = r.floor
    // the faces start 5 cm in from the corner node
    near(f.openings[r.id].at, 0.05 + 0.45)
  })

  test('openings do not overlap: the second slides clear of the first', () => {
    const { floor, walls } = wall()
    const a = addOpening(floor, walls[0], 2, 'door')!
    const b = addOpening(a.floor, walls[0], 2.3, 'window')!
    const o1 = b.floor.openings[a.id], o2 = b.floor.openings[b.id]
    assert.ok(o2.at - o2.width / 2 >= o1.at + o1.width / 2)
    assert.deepEqual(checkFloor(b.floor), [])
  })

  test('no room for an opening: nothing is added', () => {
    const r = addWall(emptyFloor(), [0, 0], [0.5, 0], P)
    assert.equal(addOpening(r.floor, r.walls[0], 0.25, 'door'), null)
    assert.equal(fitOpening(r.floor, r.walls[0], 0.25, 0.4), 0.25)
  })

  test('a width that no longer fits is refused', () => {
    const { floor, walls } = wall()
    const r = addOpening(floor, walls[0], 2, 'door')!
    assert.equal(setOpening(r.floor, r.id, { width: 5 }), r.floor)
    near(setOpening(r.floor, r.id, { width: 1.2 }).openings[r.id].width, 1.2)
  })

  test('sliding stops at the end of the wall', () => {
    const { floor, walls } = wall()
    const r = addOpening(floor, walls[0], 2, 'door')!
    near(moveOpening(r.floor, r.id, 10).openings[r.id].at, 4 - 0.45)
  })

  test('cutting a wall keeps each opening where it was', () => {
    const { floor, walls } = wall()
    let f = addOpening(floor, walls[0], 1, 'door')!.floor
    const r = addOpening(f, walls[0], 3, 'window')!
    f = splitWall(r.floor, walls[0], [2, 0]).floor
    const o = f.openings[r.id]
    assert.notEqual(o.wall, walls[0])
    near(o.at, 1)
    nearXY(openingRect(f, r.id)[0], [2.4, -0.05])
  })

  test('joining walls back keeps the openings where they were', () => {
    let f = addWall(box(4, 3), [2, 0], [2, 3], P).floor
    const bottomRight = Object.keys(f.walls).find(id => {
      const [a, b] = [f.nodes[f.walls[id].a], f.nodes[f.walls[id].b]]
      return a[1] === 0 && b[1] === 0 && Math.min(a[0], b[0]) === 2
    })!
    const r = addOpening(f, bottomRight, 1, 'door')!
    const where = openingRect(r.floor, r.id)
    const divider = Object.keys(r.floor.walls).find(id => {
      const w = r.floor.walls[id]
      return r.floor.nodes[w.a][0] === 2 && r.floor.nodes[w.b][0] === 2
    })!
    f = removeWall(r.floor, divider)
    const after = openingRect(f, r.id)
    for (let i = 0; i < 4; i++) {
      const j = after.findIndex(p => Math.hypot(p[0] - where[i][0], p[1] - where[i][1]) < 1e-9)
      assert.ok(j >= 0, 'opening moved')
    }
  })
})

describe('checks', () => {
  test('a node moved across a wall is reported as a crossing', () => {
    let f = addWall(box(4, 3), [2, 3], [2, 2], P).floor
    const tip = Object.keys(f.nodes).find(n => f.nodes[n][1] === 2)!
    f = moveNode(f, tip, [2, -1])
    assert.ok(checkFloor(f).some(i => i.code === 'crossing'))
  })

  test('shortening a wall under its door is reported', () => {
    const { floor, walls } = addWall(emptyFloor(), [0, 0], [4, 0], P)
    const r = addOpening(floor, walls[0], 3, 'door')!
    const f = setWallLength(r.floor, walls[0], 2)
    assert.deepEqual(checkFloor(f).map(i => i.code), ['opening-off-wall'])
  })
})

describe('reading a sketch', () => {
  test('what is written reads back the same', () => {
    const s = emptySketch()
    const f = box(4, 3)
    const r = addOpening(f, Object.keys(f.walls)[0], 2, 'door')!
    s.floors[0] = labelRoom(r.floor, findRooms(r.floor)[0], { name: 'Зал' }).floor
    const json = JSON.parse(JSON.stringify(s))
    assert.deepEqual(parseSketch(json), s)
  })

  test('broken references and wrong values are refused', () => {
    const s = JSON.parse(JSON.stringify({ ...emptySketch(), floors: [box(4, 3)] }))
    const f = s.floors[0]
    const w = Object.keys(f.walls)[0]
    assert.throws(() => parseSketch({ ...s, version: 2 }), /версия/)
    assert.throws(() => parseSketch({ ...s, floors: [{ ...f, walls: { ...f.walls, [w]: { ...f.walls[w], a: 'nope' } } }] }), /узел/)
    assert.throws(() => parseSketch({ ...s, floors: [{ ...f, walls: { ...f.walls, [w]: { ...f.walls[w], thickness: 0 } } }] }), /thickness/)
    assert.throws(() => parseSketch({ ...s, floors: [{ ...f, openings: { x: { wall: 'nope' } } }] }), /kind|wall/)
  })
})
