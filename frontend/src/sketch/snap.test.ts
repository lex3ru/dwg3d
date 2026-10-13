import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { addChain, addOpening, addWall, emptyFloor, outlines, WALL_DEFAULTS } from '../plan/index.ts'
import { atLength, facesFloor, openingSpot, readTyped, snap, typedPoint } from './snap.ts'
import { clearances, openingShape } from './symbols.ts'
import { fitView, gridSteps, toPlan, toScreen, zoomAt } from './view.ts'

const P = WALL_DEFAULTS.partition
const box = addChain(emptyFloor(), [[0, 0], [4, 0], [4, 3], [0, 3]], P, true).floor
const tol = 0.1

describe('snapping', () => {
  test('a corner near the cursor wins', () => {
    const s = snap(box, [3.95, 3.04], { tol })
    assert.equal(s.kind, 'node')
    assert.deepEqual(s.p, [4, 3])
  })

  test('near a wall the point lands on its centre line', () => {
    const s = snap(box, [2.03, 0.06], { tol })
    assert.equal(s.kind, 'wall')
    assert.deepEqual(s.p, [2.03, 0])
  })

  test('drawing on from a point goes straight when nearly straight', () => {
    const s = snap(box, [2.5, 1.53], { tol, from: [1, 1.5] })
    assert.equal(s.kind, 'straight')
    assert.deepEqual(s.p, [2.5, 1.5])
  })

  test('going straight stops at the wall it reaches', () => {
    const s = snap(box, [3.96, 1.52], { tol, from: [1, 1.5] })
    assert.equal(s.kind, 'cross')
    assert.deepEqual(s.p, [4, 1.5])
  })

  test('going straight stops in line with a corner', () => {
    const f = addWall(box, [6, 0], [6, 1], P).floor
    const s = snap(f, [5.95, 5.02], { tol, from: [5, 5] })
    assert.equal(s.kind, 'align')
    assert.deepEqual(s.p, [6, 5])
    assert.deepEqual(s.guides[0][0], [6, 1])
  })

  test('off every wall the point lines up with corners and shows why', () => {
    const s = snap(box, [6.03, 3.05], { tol })
    assert.equal(s.kind, 'align')
    assert.deepEqual(s.p, [6.03, 3])
    assert.equal(s.guides.length, 1)
  })

  test('elsewhere the point is on the centimetre grid', () => {
    const s = snap(box, [8.123, 7.456], { tol })
    assert.equal(s.kind, 'free')
    assert.deepEqual(s.p, [8.12, 7.46])
  })

  test('Alt held: no snapping', () => {
    assert.equal(snap(box, [3.97, 3.01], { tol, free: true }).kind, 'free')
  })

  test('a dragged corner does not snap to itself or its own walls', () => {
    const corner = Object.keys(box.nodes).find(n => box.nodes[n][0] === 4 && box.nodes[n][1] === 3)!
    const s = snap(box, [4.02, 2.5], { tol, skip: [corner] })
    assert.notEqual(s.kind, 'wall')
  })

  test('a typed length is laid off towards the cursor', () => {
    assert.deepEqual(atLength([0, 0], [3, 4], 10), [6, 8])
    assert.equal(atLength([0, 0], [0, 0], 1), null)
  })
})

describe('view', () => {
  const size: [number, number] = [800, 600]

  test('screen and plan points convert both ways, Y up on the plan', () => {
    const v = { cx: 2, cy: 1, scale: 100 }
    assert.deepEqual(toScreen(v, size, [2, 1]), [400, 300])
    assert.deepEqual(toScreen(v, size, [3, 2]), [500, 200])
    assert.deepEqual(toPlan(v, size, [500, 200]), [3, 2])
  })

  test('zooming keeps the point under the cursor in place', () => {
    const v = { cx: 0, cy: 0, scale: 50 }
    const at: [number, number] = [650, 120]
    const before = toPlan(v, size, at)
    const after = toPlan(zoomAt(v, size, at, 2.5), size, at)
    assert.ok(Math.abs(before[0] - after[0]) < 1e-9 && Math.abs(before[1] - after[1]) < 1e-9)
  })

  test('fitting shows the whole plan', () => {
    const v = fitView([0, 0, 20, 10], size)
    const [x0, y1] = toPlan(v, size, [0, 0]), [x1, y0] = toPlan(v, size, size)
    assert.ok(x0 < 0 && y0 < 0 && x1 > 20 && y1 > 10)
  })

  test('grid lines stay at least 12 px apart', () => {
    for (const scale of [3, 20, 50, 130, 400, 2000]) assert.ok(gridSteps(scale).minor * scale >= 12)
  })
})

describe('placing openings', () => {
  const bottom = Object.keys(box.walls).find(id => box.nodes[box.walls[id].a][1] === 0 && box.nodes[box.walls[id].b][1] === 0)!

  test('the opening is centred under the cursor on the wall it is over', () => {
    const s = openingSpot(box, [1.234, 0.02], 0.9, tol)!
    assert.equal(s.wall, bottom)
    assert.ok(Math.abs(s.at - 1.23) < 1e-9)
    assert.equal(s.side, 'left')    // above the wall running east: its left side
  })

  test('its edge is a whole number of centimetres from the corner', () => {
    const r = addWall(emptyFloor(), [0, 0], [4, 0], WALL_DEFAULTS.bearing)
    const s = openingSpot(r.floor, [1.2345, 0], 0.9, tol)!
    const edge = (s.at - 0.45) * 100
    assert.ok(Math.abs(edge - Math.round(edge)) < 1e-6, String(edge))
  })

  test('near the middle of the wall it goes to the middle', () => {
    assert.equal(openingSpot(box, [2.06, -0.03], 0.9, tol)!.at, 2)
  })

  test('next to a corner it is pushed clear of the corner', () => {
    assert.equal(openingSpot(box, [0.1, 0], 0.9, tol)!.at, 0.05 + 0.45)
  })

  test('away from walls there is no place', () => {
    assert.equal(openingSpot(box, [2, 1.5], 0.9, tol), null)
  })

  test('it slides clear of an opening already there', () => {
    const f = addOpening(box, bottom, 2, 'door')!.floor
    const s = openingSpot(f, [2.1, 0], 0.9, tol)!
    assert.ok(Math.abs(s.at - 2) >= 0.9)
  })
})

describe('opening symbols', () => {
  const r = addWall(emptyFloor(), [0, 0], [4, 0], P)
  const door = addOpening(r.floor, r.walls[0], 2, 'door', { side: 'left', hinge: 'a' })!

  test('a door opens to its side with the leaf at its hinge', () => {
    const o = door.floor.openings[door.id]
    const sh = openingShape(door.floor, o)
    // hinge at the start of the gap (x 1.55) on the left face (y 0.05); the open leaf goes up by the width
    assert.match(sh.lines, /M1\.55 0\.05L1\.55 0\.95/)
    // the swing ends where the leaf closes, at the far jamb
    assert.match(sh.swing, /2\.45 0\.05$/)
  })

  test('the other side and hinge mirror it', () => {
    const o = { ...door.floor.openings[door.id], side: 'right' as const, hinge: 'b' as const }
    const sh = openingShape(door.floor, o)
    assert.match(sh.lines, /M2\.45 -0\.05L2\.45 -0\.95/)
  })

  test('the distances to the ends are measured from the faces', () => {
    assert.deepEqual(clearances({ ...door.floor.openings[door.id] }, 0, 4).map(v => Math.round(v * 100) / 100), [1.55, 1.55])
  })
})

describe('snapping to faces', () => {
  const faces = facesFloor(box, outlines(box))

  test('a corner of the inside of a room is a point to snap to', () => {
    const s = snap(faces, [0.07, 0.04], { tol })
    assert.equal(s.kind, 'node')
    assert.ok(Math.abs(s.p[0] - 0.05) < 1e-9 && Math.abs(s.p[1] - 0.05) < 1e-9)
  })

  test('near a wall the point lands on its face, not its axis', () => {
    const s = snap(faces, [2, 0.08], { tol: 0.05 })
    assert.equal(s.kind, 'wall')
    assert.ok(Math.abs(s.p[1] - 0.05) < 1e-9)
  })

  test('the line drawn so far is snapped to as well', () => {
    const s = snap(facesFloor(box, outlines(box), [[1, 1]]), [1.03, 1.02], { tol })
    assert.deepEqual(s.p, [1, 1])
  })
})

describe('typing a wall', () => {
  const near2 = (p: [number, number] | null, q: [number, number]) => assert.ok(p && Math.abs(p[0] - q[0]) < 1e-9 && Math.abs(p[1] - q[1]) < 1e-9, String(p))

  test('a length, a length and an angle, an angle alone', () => {
    assert.deepEqual(readTyped('300'), { length: 3, angle: null })
    assert.deepEqual(readTyped('300<45'), { length: 3, angle: 45 })
    assert.deepEqual(readTyped('<90'), { length: null, angle: 90 })
    assert.deepEqual(readTyped('<'), { length: null, angle: null })
  })

  test('a length goes towards the cursor; an angle sets the way, counter-clockwise from the right', () => {
    near2(typedPoint([0, 0], [10, 0], '300'), [3, 0])
    near2(typedPoint([0, 0], [10, 0], '200<90'), [0, 2])
    near2(typedPoint([1, 1], [0, 0], '100<180'), [0, 1])
    // an angle alone: as far along it as the cursor is
    near2(typedPoint([0, 0], [3, 4], '<0'), [3, 0])
    assert.equal(typedPoint([0, 0], [3, 4], '<180'), null)          // the cursor is behind: nowhere to go
  })
})
