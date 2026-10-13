import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fitView, focusView, FOCUS_SCALE, MIN_SCALE } from './view.ts'

const size: [number, number] = [800, 600]

test('going to a box that fits the screen keeps the scale and centres on it', () => {
  const v = focusView({ cx: 0, cy: 0, scale: 100 }, [10, 10, 12, 11], size)
  assert.deepEqual(v, { cx: 11, cy: 10.5, scale: 100 })
})

test('going to a box from far out comes closer, to the scale of a door being seen', () => {
  const v = focusView({ cx: 0, cy: 0, scale: MIN_SCALE }, [10, 10, 10.9, 10.1], size)
  assert.equal(v.scale, FOCUS_SCALE)
})

test('going to a box larger than the screen moves out until it fits', () => {
  const box: [number, number, number, number] = [0, 0, 40, 10]
  const v = focusView({ cx: 0, cy: 0, scale: 100 }, box, size)
  assert.equal(v.scale, fitView(box, size).scale)
  assert.ok(v.scale < 100)
})
