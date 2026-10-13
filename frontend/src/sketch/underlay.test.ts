import assert from 'node:assert/strict'
import { test } from 'node:test'
import { calibrate, levelUnderlay, moveUnderlay, onUnderlay, pixelAt, placeUnderlay, rotateUnderlay, underlayTransform } from './underlay.ts'

const near = (a: number, b: number, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} ≠ ${b}`)

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

test('turned a quarter about its middle, the picture keeps its middle and stands on end', () => {
  const u = { ...placeUnderlay('x.png', 100, 50, null), at: [0, 0] as [number, number], scale: 0.1 }
  const r = rotateUnderlay(u, 90)
  const mid = pixelAt(r, [50, 25])
  near(mid[0], 5); near(mid[1], 2.5)
  // its top-left pixel was at (0, 5), 5 m left of and 2.5 m above the middle: turned, it is 2.5 m left and 5 m below
  const tl = pixelAt(r, [0, 0])
  near(tl[0], 2.5); near(tl[1], -2.5)
  assert.ok(onUnderlay(r, [5, 4.9]) && !onUnderlay(r, [9, 2.5]))
})

test('the SVG transform lays a turned picture as pixelAt does', () => {
  const u = rotateUnderlay({ ...placeUnderlay('x.png', 200, 100, null), at: [1, 2] as [number, number], scale: 0.05 }, 30)
  const [a, b, c, d, e, f] = underlayTransform(u).slice(7, -1).split(' ').map(Number)
  for (const px of [[0, 0], [200, 0], [37, 81]] as [number, number][]) {
    const p = pixelAt(u, px)
    near(a * px[0] + c * px[1] + e, p[0], 1e-6)                    // the transform is written to 1e-9
    near(b * px[0] + d * px[1] + f, p[1], 1e-6)
  }
})

test('levelled by two points, a slanted line on the picture runs straight across', () => {
  const u = rotateUnderlay({ ...placeUnderlay('x.png', 100, 100, null), at: [0, 0] as [number, number], scale: 0.1 }, 7)
  const a = pixelAt(u, [10, 50]), b = pixelAt(u, [90, 50])          // a horizontal line of the picture, now slanted
  const l = levelUnderlay(u, a, b)
  const a2 = pixelAt(l, [10, 50]), b2 = pixelAt(l, [90, 50])
  near(a2[0], a[0]); near(a2[1], a[1])                              // turned about the first point
  near(b2[1], a2[1])
  near(l.rotation, 0)
  // a line nearer upright is made upright
  const c = pixelAt(u, [50, 10]), d = pixelAt(u, [50, 90])
  const v = levelUnderlay(u, c, d)
  near(pixelAt(v, [50, 10])[0], pixelAt(v, [50, 90])[0])
})

test('calibration keeps the turn', () => {
  const u = rotateUnderlay({ ...placeUnderlay('x.png', 1000, 800, null), at: [1, 2] as [number, number], scale: 0.01 }, 45)
  const a = pixelAt(u, [100, 400]), b = pixelAt(u, [400, 400])
  const c = calibrate(u, a, b, 4.5)
  const a2 = pixelAt(c, [100, 400]), b2 = pixelAt(c, [400, 400])
  near(a2[0], a[0]); near(a2[1], a[1])
  near(Math.hypot(b2[0] - a2[0], b2[1] - a2[1]), 4.5)
  near(c.rotation, 45)
})
