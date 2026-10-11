import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { addChain, addWall, emptyFloor, WALL_DEFAULTS } from '../plan/index.ts'
import { atLength, snap } from './snap.ts'
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
