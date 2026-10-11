import assert from 'node:assert/strict'
import { test } from 'node:test'
import { calibrate, moveUnderlay, onUnderlay, pixelAt, placeUnderlay, underlayTransform } from './underlay.ts'

const near = (a: number, b: number) => assert.ok(Math.abs(a - b) < 1e-9, `${a} ≠ ${b}`)

test('on an empty plan a picture lies 20 m wide around the origin', () => {
  const u = placeUnderlay('x.png', 2000, 1000, null)
  near(u.width * u.scale, 20)
  near(u.at[0], -10)
  near(u.at[1], -5)
})

test('over drawn walls a picture covers them', () => {
  const u = placeUnderlay('x.png', 1000, 500, [0, 0, 10, 4])
  near(u.width * u.scale, 11.5)
  near(u.at[0] + (u.width * u.scale) / 2, 5)
})

test('pixels go right and down from the top-left corner', () => {
  const u = { ...placeUnderlay('x.png', 100, 50, null), at: [0, 0] as [number, number], scale: 0.1 }
  assert.deepEqual(pixelAt(u, [0, 0]), [0, 5])
  assert.deepEqual(pixelAt(u, [100, 50]), [10, 0])
  // the SVG transform does the same: (u, v) → (at.x + s·u, at.y + H·s − s·v)
  assert.equal(underlayTransform(u), 'matrix(0.1 0 0 -0.1 0 5)')
})

test('two points and their distance set the scale; the first point stays put', () => {
  const u = { ...placeUnderlay('x.png', 1000, 800, null), at: [1, 2] as [number, number], scale: 0.01 }
  // a wall that measures 300 px on the picture is 4.5 m long
  const a = pixelAt(u, [100, 400]), b = pixelAt(u, [400, 400])
  const c = calibrate(u, a, b, 4.5)
  near(c.scale, 0.015)
  const a2 = pixelAt(c, [100, 400]), b2 = pixelAt(c, [400, 400])
  near(a2[0], a[0]); near(a2[1], a[1])
  near(Math.hypot(b2[0] - a2[0], b2[1] - a2[1]), 4.5)
})

test('calibration with no distance changes nothing', () => {
  const u = placeUnderlay('x.png', 100, 100, null)
  assert.equal(calibrate(u, [1, 1], [1, 1], 3), u)
  assert.equal(calibrate(u, [0, 0], [1, 1], 0), u)
})

test('moving and finding the picture', () => {
  const u = moveUnderlay({ ...placeUnderlay('x.png', 100, 100, null), at: [0, 0] as [number, number], scale: 0.1 }, [2, 3])
  assert.deepEqual(u.at, [2, 3])
  assert.ok(onUnderlay(u, [7, 8]))
  assert.ok(!onUnderlay(u, [1, 8]))
})
