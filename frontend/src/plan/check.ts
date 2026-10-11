/**
 * Problems of a floor that the edits themselves do not rule out (a node moved
 * across a wall, a wall shortened under its door) or that come from outside.
 * The editor shows them; the build refuses a floor with errors.
 */
import { ends, JOIN_TOL } from './graph.ts'
import type { Floor } from './model.ts'
import { outlines, wallSides } from './outline.ts'
import { dist, lineHit, sub } from './vec.ts'

export interface Issue {
  level: 'error' | 'warning'
  code: 'short-wall' | 'twin-walls' | 'crossing' | 'opening-off-wall' | 'openings-overlap' | 'opening-too-tall'
  message: string
  ids: string[]
}

export function checkFloor(f: Floor): Issue[] {
  const issues: Issue[] = []
  const walls = Object.entries(f.walls)
  const pairs = new Map<string, string>()
  for (const [id, w] of walls) {
    if (dist(f.nodes[w.a], f.nodes[w.b]) <= JOIN_TOL)
      issues.push({ level: 'error', code: 'short-wall', message: 'Стена короче 5 мм', ids: [id] })
    const pair = w.a < w.b ? `${w.a}|${w.b}` : `${w.b}|${w.a}`
    const twin = pairs.get(pair)
    if (twin) issues.push({ level: 'error', code: 'twin-walls', message: 'Две стены между одними и теми же точками', ids: [twin, id] })
    else pairs.set(pair, id)
  }
  // walls crossing away from a node: the plan's rooms are not what is drawn
  for (let i = 0; i < walls.length; i++)
    for (let j = i + 1; j < walls.length; j++) {
      const [x, w] = walls[i], [y, v] = walls[j]
      if (w.a === v.a || w.a === v.b || w.b === v.a || w.b === v.b) continue
      const [a, b] = ends(f, w), [c, d] = ends(f, v)
      const hit = lineHit(a, sub(b, a), c, sub(d, c))
      if (!hit) continue
      const e1 = JOIN_TOL / dist(a, b), e2 = JOIN_TOL / dist(c, d)
      if (hit.s > -e1 && hit.s < 1 + e1 && hit.u > -e2 && hit.u < 1 + e2)
        issues.push({ level: 'error', code: 'crossing', message: 'Стены пересекаются не в узле', ids: [x, y] })
    }
  const lines = outlines(f)
  const byWall: Record<string, string[]> = {}
  for (const [id, o] of Object.entries(f.openings)) (byWall[o.wall] ??= []).push(id)
  for (const [wall, ids] of Object.entries(byWall)) {
    const s = wallSides(f, wall, lines[wall])
    const h = f.walls[wall].height ?? f.height
    const sorted = ids.map(id => [id, f.openings[id]] as const).sort((x, y) => x[1].at - y[1].at)
    for (const [id, o] of sorted) {
      if (o.at - o.width / 2 < s.from - 1e-6 || o.at + o.width / 2 > s.to + 1e-6)
        issues.push({ level: 'error', code: 'opening-off-wall', message: 'Проём выходит за стену', ids: [id] })
      if (o.sill + o.height > h + 1e-6)
        issues.push({ level: 'warning', code: 'opening-too-tall', message: 'Проём выше стены', ids: [id] })
    }
    for (let i = 1; i < sorted.length; i++) {
      const [p, o1] = sorted[i - 1], [q, o2] = sorted[i]
      if (o1.at + o1.width / 2 > o2.at - o2.width / 2 + 1e-6)
        issues.push({ level: 'error', code: 'openings-overlap', message: 'Проёмы налезают друг на друга', ids: [p, q] })
    }
  }
  return issues
}
