/** Walking route on one floor: the 2D plan is rasterised into a walkability
 * grid (inside the building outline, away from walls, columns and glazing,
 * through door openings and passages), A* finds the path, and the path is
 * straightened by line-of-sight shortcuts. Plan coordinates, meters. */
import type { PlanData } from '../api'

export interface Grid {
  x0: number
  y0: number
  res: number
  w: number
  h: number
  free: Uint8Array
}

type Ring = [number, number][]

/** `extra` — more obstacles (furniture footprints). */
export function buildGrid(plan: PlanData, extra: Ring[] = [], res = 0.15, clearance = 0.25): Grid | null {
  if (!plan.bounds) return null
  const [bx0, by0, bx1, by1] = plan.bounds
  const x0 = bx0 - 1, y0 = by0 - 1
  const w = Math.ceil((bx1 - bx0 + 2) / res), h = Math.ceil((by1 - by0 + 2) / res)
  if (w * h > 4e6) return buildGrid(plan, extra, res * 1.5, clearance)
  const cv = document.createElement('canvas')
  cv.width = w
  cv.height = h
  const g = cv.getContext('2d', { willReadFrequently: true })
  if (!g) return null
  const tx = (x: number) => (x - x0) / res
  const ty = (y: number) => (y - y0) / res
  const path = (rings: Ring[]) => {
    g.beginPath()
    for (const r of rings) {
      r.forEach(([x, y], i) => (i ? g.lineTo(tx(x), ty(y)) : g.moveTo(tx(x), ty(y))))
      g.closePath()
    }
  }
  g.fillStyle = '#000'
  g.fillRect(0, 0, w, h)
  g.fillStyle = '#fff'
  for (const poly of plan.footprint) { path(poly); g.fill('evenodd') }
  // obstacles, grown by the clearance
  g.fillStyle = '#000'
  g.strokeStyle = '#000'
  g.lineWidth = (2 * clearance) / res
  g.lineJoin = 'round'
  const blocked: Ring[][] = [...plan.walls, ...plan.partitions, ...plan.columns,
    ...plan.openings.filter((o) => o.kind === 'window' || o.kind === 'vitrage').map((o) => [o.poly as unknown as Ring])]
  for (const poly of [...blocked, ...extra.map((r) => [r])]) {
    path(poly)
    g.fill('evenodd')
    g.stroke()
  }
  for (const poly of plan.footprint) { path([poly[0]]); g.stroke() }   // keep off the outer face
  const img = g.getImageData(0, 0, w, h).data
  const free = new Uint8Array(w * h)
  for (let i = 0; i < w * h; i++) free[i] = img[i * 4] > 127 ? 1 : 0
  return { x0, y0, res, w, h, free }
}

const cell = (gr: Grid, x: number, y: number): [number, number] =>
  [Math.round((x - gr.x0) / gr.res), Math.round((y - gr.y0) / gr.res)]

function nearestFree(gr: Grid, cx: number, cy: number, maxR = 20): number | null {
  for (let r = 0; r <= maxR; r++) {
    let best: number | null = null, bd = Infinity
    for (let dy = -r; dy <= r; dy++) {
      for (let dx = -r; dx <= r; dx++) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue
        const x = cx + dx, y = cy + dy
        if (x < 0 || y < 0 || x >= gr.w || y >= gr.h || !gr.free[y * gr.w + x]) continue
        const d = dx * dx + dy * dy
        if (d < bd) { bd = d; best = y * gr.w + x }
      }
    }
    if (best != null) return best
  }
  return null
}

function lineFree(gr: Grid, a: number, b: number): boolean {
  let x0 = a % gr.w, y0 = (a / gr.w) | 0
  const x1 = b % gr.w, y1 = (b / gr.w) | 0
  const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0)
  const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1
  let err = dx + dy
  for (;;) {
    if (!gr.free[y0 * gr.w + x0]) return false
    if (x0 === x1 && y0 === y1) return true
    const e2 = 2 * err
    if (e2 >= dy) { err += dy; x0 += sx }
    if (e2 <= dx) { err += dx; y0 += sy }
  }
}

/** Shortest walkable path between two plan points, or null. */
export function findPath(gr: Grid, from: [number, number], to: [number, number]): { pts: [number, number][]; length: number } | null {
  const s = nearestFree(gr, ...cell(gr, ...from))
  const t = nearestFree(gr, ...cell(gr, ...to))
  if (s == null || t == null) return null
  const n = gr.w * gr.h
  const gScore = new Float32Array(n).fill(Infinity)
  const prev = new Int32Array(n).fill(-1)
  const closed = new Uint8Array(n)
  const tx = t % gr.w, ty = (t / gr.w) | 0
  const hfun = (i: number) => {
    const dx = Math.abs((i % gr.w) - tx), dy = Math.abs(((i / gr.w) | 0) - ty)
    return Math.max(dx, dy) + (Math.SQRT2 - 1) * Math.min(dx, dy)
  }
  // binary heap of [f, index]
  const heapF: number[] = [], heapI: number[] = []
  const push = (f: number, i: number) => {
    let k = heapF.length
    heapF.push(f); heapI.push(i)
    while (k > 0) {
      const p = (k - 1) >> 1
      if (heapF[p] <= heapF[k]) break
      ;[heapF[p], heapF[k]] = [heapF[k], heapF[p]]
      ;[heapI[p], heapI[k]] = [heapI[k], heapI[p]]
      k = p
    }
  }
  const pop = () => {
    const i = heapI[0]
    const lf = heapF.pop()!, li = heapI.pop()!
    if (heapF.length) {
      heapF[0] = lf; heapI[0] = li
      let k = 0
      for (;;) {
        const l = 2 * k + 1, r = l + 1
        let m = k
        if (l < heapF.length && heapF[l] < heapF[m]) m = l
        if (r < heapF.length && heapF[r] < heapF[m]) m = r
        if (m === k) break
        ;[heapF[m], heapF[k]] = [heapF[k], heapF[m]]
        ;[heapI[m], heapI[k]] = [heapI[k], heapI[m]]
        k = m
      }
    }
    return i
  }
  gScore[s] = 0
  push(hfun(s), s)
  const dirs = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [-1, -1, Math.SQRT2]]
  let found = false
  while (heapF.length) {
    const i = pop()
    if (closed[i]) continue
    if (i === t) { found = true; break }
    closed[i] = 1
    const x = i % gr.w, y = (i / gr.w) | 0
    for (const [dx, dy, c] of dirs) {
      const nx = x + dx, ny = y + dy
      if (nx < 0 || ny < 0 || nx >= gr.w || ny >= gr.h) continue
      const j = ny * gr.w + nx
      if (!gr.free[j] || closed[j]) continue
      if (dx && dy && (!gr.free[y * gr.w + nx] || !gr.free[ny * gr.w + x])) continue   // no corner cutting
      const ng = gScore[i] + c
      if (ng < gScore[j]) {
        gScore[j] = ng
        prev[j] = i
        push(ng + hfun(j), j)
      }
    }
  }
  if (!found) return null
  const cells: number[] = []
  for (let i = t; i !== -1; i = prev[i]) cells.push(i)
  cells.reverse()
  // string pulling: keep only the turns that line of sight needs
  const keep = [cells[0]]
  let anchor = 0
  for (let k = 2; k < cells.length; k++) {
    if (!lineFree(gr, cells[anchor], cells[k])) {
      keep.push(cells[k - 1])
      anchor = k - 1
    }
  }
  if (cells.length > 1) keep.push(cells[cells.length - 1])
  const pts = keep.map((i) => [gr.x0 + (i % gr.w) * gr.res, gr.y0 + ((i / gr.w) | 0) * gr.res] as [number, number])
  pts[0] = from
  pts[pts.length - 1] = to
  let length = 0
  for (let k = 1; k < pts.length; k++) length += Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
  return { pts, length }
}
