import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Conflict, Saver, type SaverState } from './saver.ts'

/** A server that stores values by version and answers when told to. */
function server() {
  const stored: { value: string; version: number }[] = []
  const waiting: (() => void)[] = []
  let version = 1
  const send = (value: string, base: number) => new Promise<number>((resolve, reject) => {
    waiting.push(() => {
      if (base !== version) { reject(new Conflict('conflict')); return }
      version += 1
      stored.push({ value, version })
      resolve(version)
    })
  })
  const answer = async () => { while (waiting.length) { waiting.shift()!(); await new Promise(r => setTimeout(r, 0)) } }
  return { stored, send, answer, bump: () => { version += 1 } }
}

function make() {
  const s = server()
  const states: SaverState[] = []
  const saver = new Saver<string>(s.send, st => states.push(st))
  saver.reset('a', 1)
  return { s, saver, states }
}

test('a save with nothing to send does not stop later saves', async () => {
  const { s, saver } = make()
  await saver.save()                       // nothing changed: «Собрать» right after loading
  saver.change('b')
  const p = saver.save()
  await s.answer()
  await p
  assert.deepEqual(s.stored, [{ value: 'b', version: 2 }])
})

test('changes made while saving are saved right after, the newest only', async () => {
  const { s, saver, states } = make()
  saver.change('b')
  const p = saver.save()
  saver.change('c')
  saver.change('d')
  assert.equal(saver.save(), p)            // the save already running
  await s.answer()
  await p
  assert.deepEqual(s.stored.map(x => x.value), ['b', 'd'])
  assert.equal(states.at(-1), 'saved')
  assert.equal(saver.dirty, false)
})

test('someone else saving meanwhile stops saving until the plan is loaded again', async () => {
  const { s, saver, states } = make()
  s.bump()
  saver.change('b')
  const p = saver.save()
  await s.answer()
  await assert.rejects(p, Conflict)
  assert.equal(states.at(-1), 'conflict')
  assert.equal(saver.change('c'), false)
  assert.equal(saver.dirty, true)
  saver.reset('theirs', 2)
  assert.equal(saver.change('mine'), true)
})

test('a failure is reported and the next save tries again', async () => {
  let fail = true
  const states: SaverState[] = []
  const saver = new Saver<string>(async (_v, version) => { if (fail) throw new Error('away'); return version + 1 }, st => states.push(st))
  saver.reset('a', 1)
  saver.change('b')
  await assert.rejects(saver.save(), /away/)
  assert.equal(states.at(-1), 'failed')
  fail = false
  await saver.save()
  assert.equal(states.at(-1), 'saved')
  assert.equal(saver.dirty, false)
})

test('undone back to what is saved: nothing is sent, and it says saved', async () => {
  const { s, saver, states } = make()
  saver.change('b')
  saver.change('a')
  await saver.save()
  assert.deepEqual(s.stored, [])
  assert.equal(states.at(-1), 'saved')
})
