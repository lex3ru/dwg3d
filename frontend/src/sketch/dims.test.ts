import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addChain, addOpening, emptyFloor, outlines, WALL_DEFAULTS } from '../plan/index.ts'
import { extents, faceChain } from './dims.ts'

const P = WALL_DEFAULTS.partition       // 10 cm
const box = addChain(emptyFloor(), [[0, 0], [4, 0], [4, 3], [0, 3]], P, true).floor
const bottom = Object.keys(box.walls).find(id => box.nodes[box.walls[id].a][1] === 0 && box.nodes[box.walls[id].b][1] === 0)!
const r2 = (v: number) => Math.round(v * 1000) / 1000

test('a wall without openings has no chain, only its length', () => {
  assert.deepEqual(faceChain(box, bottom, outlines(box)[bottom], 'plus'), [])
})

test('corner to door, the door, door to window, the window, window to corner — on each face', () => {
  let f = addOpening(box, bottom, 1, 'door', { width: 0.9 })!.floor
  f = addOpening(f, bottom, 3, 'window', { width: 1.2 })!.floor
  const o = outlines(f)[bottom]
  const inside = faceChain(f, bottom, o, 'plus').map(s => [r2(s.from), r2(s.to), s.opening])
  // the inner face runs from 0.05 to 3.95
  assert.deepEqual(inside, [[0.05, 0.55, false], [0.55, 1.45, true], [1.45, 2.4, false], [2.4, 3.6, true], [3.6, 3.95, false]])
  // the outer face from −0.05 to 4.05: the same openings, longer ends
  const outside = faceChain(f, bottom, o, 'minus')
  assert.equal(r2(outside[0].from), -0.05)
  assert.equal(r2(outside.at(-1)!.to), 4.05)
  const total = outside.reduce((s, x) => s + x.to - x.from, 0)
  assert.equal(r2(total), 4.1)
})

test("the floor's extents are the outsides of its walls", () => {
  assert.deepEqual(extents(outlines(box))!.map(r2), [-0.05, -0.05, 4.05, 3.05])
  assert.equal(extents({}), null)
})
