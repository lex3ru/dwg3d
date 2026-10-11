import assert from 'node:assert/strict'
import { test } from 'node:test'
import { field, fitScale } from './print.ts'

test('the field left for the plan on a sheet', () => {
  assert.deepEqual(field('A4'), [187, 190])
  assert.deepEqual(field('A3'), [310, 277])
})

test('a floor is drawn at the largest usual scale it fits at', () => {
  assert.equal(fitScale([8, 6], 'A4'), 50)            // 160 × 120 mm at 1:50
  assert.equal(fitScale([12, 9], 'A4'), 100)          // 240 mm at 1:50 would not fit
  assert.equal(fitScale([12, 9], 'A3'), 50)
  assert.equal(fitScale([3, 2], 'A4'), 20)
  assert.equal(fitScale([400, 300], 'A4'), null)
})
