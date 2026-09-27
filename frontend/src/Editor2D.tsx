import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getPlan, type FloorEdits, type FloorMeta, type Job, type OpeningKind, type PlanData, type XY } from './api'

type EditTool = 'select' | 'wall' | 'erase' | 'opening'
type Ring = [number, number][]
type EditKey = keyof FloorEdits
type SnapKind = 'vertex' | 'edge' | 'inter' | 'ortho' | 'free'
type Snap = { p: XY; kind: SnapKind; dir?: XY }
type Opening = PlanData['openings'][number]

const KIND_LABEL: Record<string, string> = {
  door: 'Дверь', window: 'Окно', vitrage: 'Витраж', passage: 'Проход без перемычки', wall: 'Заделать стеной', none: 'Убрать',
}
const KIND_COLOR: Record<string, string> = {
  door: '#e8590c', window: '#1c7ed6', vitrage: '#15aabf', passage: '#ae3ec9', wall: '#343a40',
}
const TOOLS: { id: EditTool; label: string; key: string; code: string }[] = [
  { id: 'select', label: 'Выбор', key: 'V', code: 'KeyV' },
  { id: 'wall', label: 'Стена', key: 'W', code: 'KeyW' },
  { id: 'erase', label: 'Стереть', key: 'E', code: 'KeyE' },
  { id: 'opening', label: 'Проём', key: 'O', code: 'KeyO' },
]
const SNAP_PX = 10          // snap radius in screen pixels
const DRAG_PX = 4           // movement that turns a click into a pan

const emptyEdits = (): FloorEdits => ({ add_walls: [], erase_walls: [], add_openings: [], openings: [], rooms: [] })

function ringPath(rings: Ring[]): string {
  return rings.map((r) => 'M' + r.map(([x, y]) => `${x} ${y}`).join('L') + 'Z').join('')
}

function segRect(a: XY, b: XY, w: number): string {
  const dx = b[0] - a[0], dy = b[1] - a[1]
  const L = Math.hypot(dx, dy) || 1
  const nx = (-dy / L) * w / 2, ny = (dx / L) * w / 2
  return `M${a[0] + nx} ${a[1] + ny}L${b[0] + nx} ${b[1] + ny}L${b[0] - nx} ${b[1] - ny}L${a[0] - nx} ${a[1] - ny}Z`
}

/** Axis-aligned box from two corners, stored as an erase segment + width. */
function boxToErase(p: XY, q: XY) {
  const x0 = Math.min(p[0], q[0]), x1 = Math.max(p[0], q[0])
  const y0 = Math.min(p[1], q[1]), y1 = Math.max(p[1], q[1])
  const ym = (y0 + y1) / 2
  return { a: [x0, ym] as XY, b: [x1, ym] as XY, width: Math.round((y1 - y0) * 1000) / 1000 }
}

const dist = (p: XY, q: XY) => Math.hypot(p[0] - q[0], p[1] - q[1])
const near = (p: XY, q: XY, tol = 0.05) => dist(p, q) < tol
const r2 = (v: number) => Math.round(v * 100) / 100
const len = (a: XY, b: XY) => dist(a, b).toFixed(2)

function projectOnSeg(p: XY, a: XY, b: XY): XY {
  const dx = b[0] - a[0], dy = b[1] - a[1]
  const L2 = dx * dx + dy * dy || 1
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
  return [a[0] + t * dx, a[1] + t * dy]
}

/** Intersection of the infinite line (o, d) with segment ab, or null. */
function lineSeg(o: XY, d: XY, a: XY, b: XY): XY | null {
  const ex = b[0] - a[0], ey = b[1] - a[1]
  const den = d[0] * ey - d[1] * ex
  if (Math.abs(den) < 1e-9) return null
  const t = ((a[0] - o[0]) * ey - (a[1] - o[1]) * ex) / den
  const u = ((a[0] - o[0]) * d[1] - (a[1] - o[1]) * d[0]) / den
  if (u < -1e-6 || u > 1 + 1e-6) return null
  return [o[0] + d[0] * t, o[1] + d[1] * t]
}

/** Even-odd point-in-polygon over all rings (holes included). */
function inside(p: XY, rings: Ring[]): boolean {
  let c = false
  for (const r of rings) {
    for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
      const [xi, yi] = r[i], [xj, yj] = r[j]
      if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) c = !c
    }
  }
  return c
}

function niceScale(metersPer100px: number): number {
  const steps = [0.5, 1, 2, 5, 10, 20, 50, 100]
  return steps.find((s) => s >= metersPer100px * 0.6) ?? 100
}

export default function Editor2D({ job, floor, busy, onApply, onClose }: {
  job: Job
  floor: FloorMeta
  busy: boolean
  onApply: (floorId: string, edits: FloorEdits) => void
  onClose: () => void
}) {
  const [plan, setPlan] = useState<PlanData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const initial = useMemo<FloorEdits>(() => {
    const e = ((job.config?.edits ?? {}) as Record<string, Partial<FloorEdits>>)[floor.id] ?? {}
    return { ...emptyEdits(), ...e }
  }, [job.config, floor.id])
  const [edits, setEdits] = useState<FloorEdits>(initial)
  const [history, setHistory] = useState<FloorEdits[]>([])
  const [tool, setTool] = useState<EditTool>('select')
  const [thickness, setThickness] = useState(0.2)
  const [newKind, setNewKind] = useState<OpeningKind>('door')
  const [start, setStart] = useState<XY | null>(null)
  const [startDir, setStartDir] = useState<XY | null>(null)   // wall face direction for openings
  const [cursor, setCursor] = useState<Snap | null>(null)
  const [popup, setPopup] = useState<{ o: Opening; screen: [number, number] } | null>(null)
  const [renaming, setRenaming] = useState<{ at: XY; name: string; screen: [number, number] } | null>(null)
  const [vb, setVb] = useState<[number, number, number, number] | null>(null)   // viewBox (y flipped)
  const [size, setSize] = useState<[number, number]>([1, 1])
  const [hl, setHl] = useState<string | null>(null)          // highlighted edit "key:index"
  const [confirmClose, setConfirmClose] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const noticeTimer = useRef<number | undefined>(undefined)
  const flash = (msg: string) => {
    setNotice(msg)
    window.clearTimeout(noticeTimer.current)
    noticeTimer.current = window.setTimeout(() => setNotice(null), 2500)
  }
  const svgRef = useRef<SVGSVGElement>(null)
  const gRef = useRef<SVGGElement>(null)
  const ptr = useRef<{ sx: number; sy: number; button: number; vb: [number, number, number, number]; panning: boolean } | null>(null)
  const fitted = useRef(false)

  // the applied edits change after a rebuild -> start from them again
  useEffect(() => { setEdits(initial); setHistory([]) }, [initial])

  const fit = useCallback((p: PlanData) => {
    const [x0, y0, x1, y1] = p.bounds
    const m = Math.max(x1 - x0, y1 - y0) * 0.06
    setVb([x0 - m, -y1 - m, x1 - x0 + 2 * m, y1 - y0 + 2 * m])
  }, [])

  useEffect(() => {
    let alive = true
    getPlan(job.id, floor.plan, job.build).then((p) => {
      if (!alive) return
      setPlan(p)
      if (!fitted.current) { fit(p); fitted.current = true }
    }).catch((e) => alive && setErr(String(e.message ?? e)))
    return () => { alive = false }
  }, [job.id, job.build, floor.plan, fit])

  useEffect(() => {
    const el = svgRef.current?.parentElement
    if (!el) return
    const ro = new ResizeObserver(() => setSize([el.clientWidth || 1, el.clientHeight || 1]))
    ro.observe(el)
    return () => ro.disconnect()
  }, [plan])

  // meters per screen pixel (viewBox is fitted with "meet")
  const mpp = vb ? Math.max(vb[2] / size[0], vb[3] / size[1]) : 0.05

  // ------------------------------------------------------------ snapping
  const snapData = useMemo(() => {
    const verts: XY[] = []
    const segs: [XY, XY][] = []
    if (!plan) return { verts, segs }
    // wall faces continue across openings, so opening outlines snap too
    for (const group of [plan.walls, plan.partitions, plan.columns, plan.openings.map((o) => o.poly)]) {
      for (const poly of group) {
        for (const ring of poly) {
          for (let i = 0; i < ring.length - 1; i++) {
            verts.push(ring[i] as XY)
            segs.push([ring[i] as XY, ring[i + 1] as XY])
          }
        }
      }
    }
    return { verts, segs }
  }, [plan])

  const wallRings = useMemo(() => (plan ? [...plan.walls, ...plan.partitions, ...plan.columns].flat() as Ring[] : []), [plan])

  /** Rectangle of a new opening a->b drawn on a wall face: through the wall thickness. */
  const openingRect = useCallback((a: XY, b: XY): string | null => {
    const L = dist(a, b)
    if (L < 0.02) return null
    const u: XY = [(b[0] - a[0]) / L, (b[1] - a[1]) / L]
    const n: XY = [-u[1], u[0]]
    const m: XY = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
    const side = inside([m[0] + n[0] * 0.03, m[1] + n[1] * 0.03], wallRings) ? 1 : -1
    const dir: XY = [n[0] * side, n[1] * side]
    let depth = 0.9
    for (const [p, q] of snapData.segs) {
      const x = lineSeg(m, dir, p, q)
      if (!x) continue
      const t = (x[0] - m[0]) * dir[0] + (x[1] - m[1]) * dir[1]
      if (t > 0.02 && t < depth) depth = t
    }
    if (depth >= 0.9) depth = 0.2
    const o: XY = [dir[0] * depth, dir[1] * depth]
    return `M${a[0]} ${a[1]}L${b[0]} ${b[1]}L${b[0] + o[0]} ${b[1] + o[1]}L${a[0] + o[0]} ${a[1] + o[1]}Z`
  }, [wallRings, snapData])

  const snap = useCallback((raw: XY, free: boolean, from: XY | null): Snap => {
    const tol = SNAP_PX * mpp
    const R = (p: XY): XY => [r2(p[0]), r2(p[1])]
    const nearestEdge = (q: XY, maxD: number): { p: XY; dir: XY } | null => {
      let best: { p: XY; dir: XY } | null = null
      let bd = maxD
      for (const [a, b] of snapData.segs) {
        const pp = projectOnSeg(q, a, b)
        const d = dist(pp, q)
        if (d < bd) {
          const L = dist(a, b) || 1
          bd = d
          best = { p: pp, dir: [(b[0] - a[0]) / L, (b[1] - a[1]) / L] }
        }
      }
      return best
    }
    if (free) return { p: R(raw), kind: 'free' }

    // opening, second point: slide along the wall face picked by the first click
    if (tool === 'opening' && from && startDir) {
      const t = (raw[0] - from[0]) * startDir[0] + (raw[1] - from[1]) * startDir[1]
      return { p: R([from[0] + startDir[0] * t, from[1] + startDir[1] * t]), kind: 'edge', dir: startDir }
    }
    // opening, first point: must be on a wall face
    if (tool === 'opening') {
      const e = nearestEdge(raw, tol * 1.5)
      return e ? { p: R(e.p), kind: 'edge', dir: e.dir } : { p: R(raw), kind: 'free' }
    }

    // drawing from a point: orthogonal lock wins, then snap along the locked line
    if (from) {
      const dx = raw[0] - from[0], dy = raw[1] - from[1]
      const ang = Math.abs(Math.atan2(dy, dx) * 180 / Math.PI) % 90
      if (ang < 7 || ang > 83) {
        const horiz = Math.abs(dx) > Math.abs(dy)
        const d: XY = horiz ? [Math.sign(dx) || 1, 0] : [0, Math.sign(dy) || 1]
        const onLine: XY = horiz ? [raw[0], from[1]] : [from[0], raw[1]]
        let best: XY | null = null
        let bd = tol
        for (const v of snapData.verts) {           // corners lying on the locked line
          if ((horiz ? Math.abs(v[1] - from[1]) : Math.abs(v[0] - from[0])) > tol * 0.3) continue
          const dd = dist(v, onLine)
          if (dd < bd) { bd = dd; best = v }
        }
        if (best) return { p: R(horiz ? [best[0], from[1]] : [from[0], best[1]]), kind: 'vertex' }
        for (const [a, b] of snapData.segs) {       // crossings of the locked line with wall faces
          const x = lineSeg(from, d, a, b)
          if (!x) continue
          const dd = dist(x, onLine)
          if (dd < bd) { bd = dd; best = x }
        }
        if (best) return { p: R(best), kind: 'inter' }
        return { p: R(onLine), kind: 'ortho' }
      }
    }
    let best: XY | null = null
    let bd = tol
    for (const v of [...snapData.verts, ...edits.add_walls.flatMap((x) => [x.a, x.b])]) {
      const d = dist(v, raw)
      if (d < bd) { bd = d; best = v }
    }
    if (best) return { p: R(best), kind: 'vertex' }
    const e = nearestEdge(raw, tol * 0.8)
    if (e) return { p: R(e.p), kind: 'edge', dir: e.dir }
    return { p: R(raw), kind: 'free' }
  }, [snapData, mpp, edits.add_walls, tool, startDir])

  // ------------------------------------------------------------ edits
  const commit = (fn: (e: FloorEdits) => FloorEdits) => {
    setHistory((h) => [...h.slice(-99), edits])
    setEdits(fn(edits))
  }
  const undo = useCallback(() => {
    if (!history.length) return
    setEdits(history[history.length - 1])
    setHistory(history.slice(0, -1))
  }, [history])
  const removeEdit = (key: EditKey, i: number) => {
    commit((ed) => ({ ...ed, [key]: (ed[key] as unknown[]).filter((_, j) => j !== i) }))
    setHl(null)
  }

  const applied = useMemo(() => {
    const s = new Set<string>()
    for (const [k, list] of Object.entries(initial)) for (const it of list as unknown[]) s.add(k + JSON.stringify(it))
    return s
  }, [initial])
  const isApplied = (key: EditKey, it: unknown) => applied.has(key + JSON.stringify(it))

  const dirty = JSON.stringify(edits) !== JSON.stringify(initial)
  const pendingCount = (Object.keys(edits) as EditKey[])
    .reduce((n, k) => n + (edits[k] as unknown[]).filter((it) => !isApplied(k, it)).length, 0)
    + (Object.keys(initial) as EditKey[])
      .reduce((n, k) => n + (initial[k] as unknown[]).filter((it) => !(edits[k] as unknown[]).some((x) => JSON.stringify(x) === JSON.stringify(it))).length, 0)

  // ------------------------------------------------------------ keyboard
  const cancelDrawing = useCallback(() => { setStart(null); setStartDir(null) }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT' || (e.target as HTMLElement)?.tagName === 'SELECT') {
        if (e.key === 'Escape') setRenaming(null)
        return
      }
      if (e.key === 'Escape') {
        if (start) cancelDrawing()
        else { setPopup(null); setRenaming(null); setConfirmClose(false) }
      } else if ((e.ctrlKey || e.metaKey) && e.code === 'KeyZ') {
        e.preventDefault()
        if (start) cancelDrawing()
        else undo()
      } else if (!e.ctrlKey && !e.metaKey && !e.altKey) {
        const t = TOOLS.find((x) => x.code === e.code)
        if (t) { setTool(t.id); setStart(null); setStartDir(null); setPopup(null) }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [start, undo, cancelDrawing])

  // ------------------------------------------------------------ pointer
  const toPlan = (clientX: number, clientY: number): XY | null => {
    const m = gRef.current?.getScreenCTM()
    if (!m) return null
    const p = new DOMPoint(clientX, clientY).matrixTransform(m.inverse())
    return [p.x, p.y]
  }

  const onWheel = (e: React.WheelEvent) => {
    if (!vb) return
    const p = toPlan(e.clientX, e.clientY)
    if (!p) return
    const k = Math.exp(Math.sign(e.deltaY) * 0.15)
    const [x, y, w, h] = vb
    const px = p[0], py = -p[1]
    setVb([px - (px - x) * k, py - (py - y) * k, w * k, h * k])
  }

  const zoom = (k: number) => {
    if (!vb) return
    const [x, y, w, h] = vb
    setVb([x + w / 2 - (w * k) / 2, y + h / 2 - (h * k) / 2, w * k, h * k])
  }

  const onPointerDown = (e: React.PointerEvent) => {
    if (!vb || busy) return
    ptr.current = { sx: e.clientX, sy: e.clientY, button: e.button, vb, panning: false }
    svgRef.current?.setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const raw = toPlan(e.clientX, e.clientY)
    if (raw) setCursor(snap(raw, e.shiftKey, start))
    const d = ptr.current
    if (!d) return
    if (!d.panning && Math.hypot(e.clientX - d.sx, e.clientY - d.sy) > DRAG_PX) d.panning = true
    if (d.panning) {
      const dx = (e.clientX - d.sx) * mpp, dy = (e.clientY - d.sy) * mpp
      setVb([d.vb[0] - dx, d.vb[1] - dy, d.vb[2], d.vb[3]])
    }
  }

  const onPointerUp = (e: React.PointerEvent) => {
    const d = ptr.current
    ptr.current = null
    if (!d || d.panning || busy) return
    if (d.button === 2) {           // right click: finish / cancel the current line
      setStart(null)
      setStartDir(null)
      return
    }
    if (d.button !== 0) return
    const raw = toPlan(e.clientX, e.clientY)
    if (!raw) return
    setPopup(null)
    setRenaming(null)

    if (tool === 'select') {
      const el = document.elementFromPoint(e.clientX, e.clientY)
      const oid = el?.getAttribute('data-oid')
      const rid = el?.getAttribute('data-room')
      const o = oid ? plan?.openings.find((x) => x.id === oid) : undefined
      if (o) { setPopup({ o, screen: [e.clientX, e.clientY] }); return }
      const rm = rid != null ? plan?.rooms[Number(rid)] : undefined
      if (rm) {
        const pending = edits.rooms.find((x) => near(x.at, rm.label))
        setRenaming({ at: rm.label, name: pending?.name ?? rm.name, screen: [e.clientX, e.clientY] })
      }
      return
    }

    const sn = snap(raw, e.shiftKey, start)
    const q = sn.p
    if (!start) {
      if (tool === 'opening') {
        if (!sn.dir) { flash('Проём ставится на грань стены — подведите курсор к стене'); return }
        setStartDir(sn.dir)
      }
      setStart(q)
      return
    }
    if (near(start, q, 0.03)) return
    const a = start
    if (tool === 'wall') {
      commit((ed) => ({ ...ed, add_walls: [...ed.add_walls, { a, b: q, thickness }] }))
      setStart(q)                  // continue the wall chain from here
    } else if (tool === 'erase') {
      const box = boxToErase(a, q)
      if (box.width < 0.02 || dist(box.a, box.b) < 0.02) return
      commit((ed) => ({ ...ed, erase_walls: [...ed.erase_walls, box] }))
      setStart(null)
    } else {
      commit((ed) => ({ ...ed, add_openings: [...ed.add_openings, { a, b: q, kind: newKind }] }))
      setStart(null)
      setStartDir(null)
    }
  }

  // ------------------------------------------------------------ openings / rooms
  const pendingKind = (o: Opening) => edits.openings.find((x) => near(x.at, o.center, 0.3))?.kind
  const manualIdx = (o: Opening) => edits.add_openings.findIndex((x) => {
    const c: XY = [(x.a[0] + x.b[0]) / 2, (x.a[1] + x.b[1]) / 2]
    return dist(c, o.center) < Math.max(0.3, o.width / 2)
  })
  const setOpeningKind = (o: Opening, kind: string) => {
    commit((ed) => {
      const rest = ed.openings.filter((x) => !near(x.at, o.center, 0.3))
      return { ...ed, openings: kind === o.kind ? rest : [...rest, { at: o.center, kind: kind as FloorEdits['openings'][number]['kind'] }] }
    })
    setPopup(null)
  }
  const renameRoom = (at: XY, name: string) => {
    commit((ed) => ({ ...ed, rooms: [...ed.rooms.filter((r) => !near(r.at, at)), { at, name }] }))
    setRenaming(null)
  }

  const centerOn = (p: XY) => {
    if (!vb) return
    setVb([p[0] - vb[2] / 2, -p[1] - vb[3] / 2, vb[2], vb[3]])
  }

  const requestClose = () => (dirty ? setConfirmClose(true) : onClose())
  const apply = () => { setConfirmClose(false); setStart(null); onApply(floor.id, edits) }

  // ------------------------------------------------------------ status line
  const status = (() => {
    const shift = ' · Shift — без привязок'
    if (busy) return 'Модель перестраивается…'
    switch (tool) {
      case 'select': return 'Кликните проём, чтобы сменить тип, или помещение, чтобы переименовать'
      case 'wall': return start
        ? `Кликните конец стены (цепочка продолжится) · ПКМ или Esc — закончить${shift}`
        : `Кликните начало стены${shift}`
      case 'erase': return start
        ? 'Кликните второй угол области — стены внутри будут удалены · Esc — отмена'
        : 'Кликните первый угол области стирания'
      case 'opening': return start
        ? `Ведите вдоль стены и кликните конец проёма (${KIND_LABEL[newKind].toLowerCase()}) · Esc — отмена`
        : 'Кликните на грани стены — начало проёма'
    }
  })()

  const erasePreview = start && cursor && tool === 'erase' ? boxToErase(start, cursor.p) : null
  const pendingErase = edits.erase_walls.filter((w) => !isApplied('erase_walls', w))
  const clipRects = [...pendingErase, ...(erasePreview ? [erasePreview] : [])]
  const markR = mpp * 5
  const scaleM = niceScale(mpp * 100)

  type Row = { key: EditKey; i: number; label: string; at: XY; item: unknown }
  const rows: Row[] = [
    ...edits.add_walls.map((w, i) => ({ key: 'add_walls' as EditKey, i, item: w, at: w.a, label: `Стена ${len(w.a, w.b)} м × ${w.thickness}` })),
    ...edits.erase_walls.map((w, i) => ({ key: 'erase_walls' as EditKey, i, item: w, at: w.a, label: `Стереть ${len(w.a, w.b)} × ${w.width.toFixed(2)} м` })),
    ...edits.add_openings.map((o, i) => ({ key: 'add_openings' as EditKey, i, item: o, at: o.a, label: `${KIND_LABEL[o.kind]} ${len(o.a, o.b)} м` })),
    ...edits.openings.map((o, i) => ({ key: 'openings' as EditKey, i, item: o, at: o.at, label: `Проём → ${KIND_LABEL[o.kind].toLowerCase()}` })),
    ...edits.rooms.map((r, i) => ({ key: 'rooms' as EditKey, i, item: r, at: r.at, label: `Помещение «${r.name}»` })),
  ]
  const hlOf = (key: EditKey, i: number) => hl === `${key}:${i}`

  return (
    <div className="editor">
      <div className="editor-bar">
        <b className="editor-title">2D: {floor.name}</b>
        <div className="seg small-seg">
          {TOOLS.map((t) => (
            <button key={t.id} className={tool === t.id ? 'on' : ''} title={`${t.label} (${t.key})`}
              onClick={() => { setTool(t.id); setStart(null); setStartDir(null); setPopup(null) }}>
              {t.label} <kbd>{t.key}</kbd>
            </button>
          ))}
        </div>
        {tool === 'wall' && (
          <label className="opt">толщина
            <select value={thickness} onChange={(e) => setThickness(Number(e.target.value))}>
              {[0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5].map((t) => <option key={t} value={t}>{t} м</option>)}
            </select>
          </label>
        )}
        {tool === 'opening' && (
          <label className="opt">тип
            <select value={newKind} onChange={(e) => setNewKind(e.target.value as OpeningKind)}>
              {(['door', 'window', 'vitrage', 'passage'] as const).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select>
          </label>
        )}
        <span className="spacer" />
        <button className="small" disabled={!history.length || busy} onClick={undo} title="Отменить последнюю правку (Ctrl+Z)">↶ Отменить</button>
        <button className="ghost" onClick={requestClose}>Закрыть</button>
        <button className="primary" disabled={!dirty || busy} onClick={apply}>
          {busy ? 'Перестраивается…' : `Применить${pendingCount ? ` (${pendingCount})` : ''}`}
        </button>
      </div>
      {confirmClose && (
        <div className="confirm-bar">
          Есть неприменённые правки ({pendingCount}).
          <button className="primary small" onClick={apply}>Применить</button>
          <button className="small" onClick={() => { setConfirmClose(false); onClose() }}>Закрыть без применения</button>
          <button className="ghost small" onClick={() => setConfirmClose(false)}>Остаться</button>
        </div>
      )}
      <div className="editor-body">
        <div className="editor-canvas">
          {err && <div className="center-msg error">{err}</div>}
          {!plan && !err && <div className="center-msg">Загрузка плана…</div>}
          {plan && vb && (
            <svg ref={svgRef} viewBox={vb.join(' ')} preserveAspectRatio="xMidYMid meet"
              className={`plan-svg tool-${tool}`}
              onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
              onPointerLeave={() => setCursor(null)} onContextMenu={(e) => e.preventDefault()}>
              <defs>
                <clipPath id="erase-clip">
                  {clipRects.map((w, i) => <path key={i} d={segRect(w.a, w.b, w.width)} />)}
                </clipPath>
              </defs>
              <g ref={gRef} transform="scale(1,-1)">
                <path d={ringPath(plan.footprint.flat())} className="p-footprint" />
                {plan.rooms.map((r, i) => <path key={i} d={ringPath(r.poly)} className="p-room" data-room={i} />)}
                <path d={plan.lines.map((l) => 'M' + l.map(([x, y]) => `${x} ${y}`).join('L')).join('')} className="p-lines" />
                <path d={ringPath(plan.walls.flat())} className="p-wall" />
                <path d={ringPath(plan.partitions.flat())} className="p-partition" />
                <path d={ringPath(plan.columns.flat())} className="p-column" />
                {plan.stairs.map((s, i) => <path key={i} d={ringPath(s)} className="p-stair" />)}
                {/* walls that the pending erase areas will remove */}
                {clipRects.length > 0 && (
                  <g clipPath="url(#erase-clip)" className="p-erased">
                    <path d={ringPath([...plan.walls.flat(), ...plan.partitions.flat(), ...plan.columns.flat()])} />
                  </g>
                )}
                {plan.openings.map((o) => {
                  const pk = pendingKind(o)
                  const kind = pk ?? o.kind
                  return (
                    <g key={o.id}>
                      <path d={ringPath(o.poly)} fill={KIND_COLOR[kind] ?? '#868e96'}
                        className={`p-opening${pk ? ' changed' : ''}${popup?.o.id === o.id ? ' active' : ''}`}
                        data-oid={o.id} />
                      {o.leaves.map(([h, t], j) => <line key={j} x1={h[0]} y1={h[1]} x2={t[0]} y2={t[1]} className="p-leaf" />)}
                    </g>
                  )
                })}
                {/* edits */}
                {edits.add_walls.map((w, i) => (
                  <path key={'aw' + i} d={segRect(w.a, w.b, w.thickness)}
                    className={`e-add${isApplied('add_walls', w) ? ' applied' : ''}${hlOf('add_walls', i) ? ' hl' : ''}`} />
                ))}
                {edits.erase_walls.map((w, i) => (
                  <path key={'ew' + i} d={segRect(w.a, w.b, w.width)}
                    className={`e-erase${isApplied('erase_walls', w) ? ' applied' : ''}${hlOf('erase_walls', i) ? ' hl' : ''}`} />
                ))}
                {edits.add_openings.map((o, i) => isApplied('add_openings', o)
                  ? <line key={'ao' + i} x1={o.a[0]} y1={o.a[1]} x2={o.b[0]} y2={o.b[1]} stroke={KIND_COLOR[o.kind]}
                    className={`e-open applied${hlOf('add_openings', i) ? ' hl' : ''}`} />
                  : <path key={'ao' + i} d={openingRect(o.a, o.b) ?? ''} fill={KIND_COLOR[o.kind]}
                    className={`e-open-rect${hlOf('add_openings', i) ? ' hl' : ''}`} />)}
                {edits.openings.map((o, i) => hlOf('openings', i) && (
                  <circle key={'ok' + i} cx={o.at[0]} cy={o.at[1]} r={markR * 3} className="e-mark hl" />
                ))}
                {edits.rooms.map((r, i) => hlOf('rooms', i) && (
                  <circle key={'rn' + i} cx={r.at[0]} cy={r.at[1]} r={markR * 3} className="e-mark hl" />
                ))}
                {/* drawing preview */}
                {start && cursor && tool === 'wall' && <path d={segRect(start, cursor.p, thickness)} className="e-add preview" />}
                {erasePreview && <path d={segRect(erasePreview.a, erasePreview.b, erasePreview.width)} className="e-erase preview" />}
                {start && cursor && tool === 'opening' && (() => {
                  const r = openingRect(start, cursor.p)
                  return r ? <path d={r} fill={KIND_COLOR[newKind]} className="e-open-rect preview" /> : null
                })()}
                {start && <circle cx={start[0]} cy={start[1]} r={markR} className="start-mark" />}
                {cursor && tool !== 'select' && !busy && (
                  cursor.kind === 'vertex'
                    ? <rect x={cursor.p[0] - markR} y={cursor.p[1] - markR} width={markR * 2} height={markR * 2} className="snap-mark vertex" />
                    : cursor.kind === 'inter'
                      ? <g className="snap-mark inter">
                        <line x1={cursor.p[0] - markR} y1={cursor.p[1] - markR} x2={cursor.p[0] + markR} y2={cursor.p[1] + markR} />
                        <line x1={cursor.p[0] - markR} y1={cursor.p[1] + markR} x2={cursor.p[0] + markR} y2={cursor.p[1] - markR} />
                      </g>
                    : cursor.kind === 'edge'
                      ? <path d={`M${cursor.p[0] - markR} ${cursor.p[1]}L${cursor.p[0]} ${cursor.p[1] + markR}L${cursor.p[0] + markR} ${cursor.p[1]}L${cursor.p[0]} ${cursor.p[1] - markR}Z`} className="snap-mark edge" />
                      : <g className="snap-mark free">
                        <line x1={cursor.p[0] - markR * 1.6} y1={cursor.p[1]} x2={cursor.p[0] + markR * 1.6} y2={cursor.p[1]} />
                        <line x1={cursor.p[0]} y1={cursor.p[1] - markR * 1.6} x2={cursor.p[0]} y2={cursor.p[1] + markR * 1.6} />
                      </g>
                )}
              </g>
              {/* texts are not flipped */}
              {plan.rooms.map((r, i) => {
                const pend = edits.rooms.find((x) => near(x.at, r.label))
                const name = pend?.name ?? r.name
                return name ? (
                  <text key={i} x={r.label[0]} y={-r.label[1]} fontSize={mpp * 12} strokeWidth={mpp * 3}
                    className={`p-label${pend && !isApplied('rooms', pend) ? ' e-label' : ''}`}>{name}</text>
                ) : null
              })}
              {start && cursor && tool !== 'select' && (
                <text x={cursor.p[0] + mpp * 12} y={-cursor.p[1] - mpp * 12} fontSize={mpp * 13} strokeWidth={mpp * 4} className="len-label">
                  {tool === 'erase' && erasePreview
                    ? `${len(erasePreview.a, erasePreview.b)} × ${erasePreview.width.toFixed(2)} м`
                    : `${len(start, cursor.p)} м`}
                </text>
              )}
            </svg>
          )}
          <div className={`status-line${start ? ' active' : ''}${notice ? ' warn' : ''}`}>{notice ?? status}</div>
          <div className="zoom-btns">
            <button onClick={() => zoom(1 / 1.4)} title="Приблизить">+</button>
            <button onClick={() => zoom(1.4)} title="Отдалить">−</button>
            <button onClick={() => plan && fit(plan)} title="Показать весь этаж">⤢</button>
          </div>
          {vb && (
            <div className="scale-bar">
              <div style={{ width: scaleM / mpp }} />
              <span>{scaleM} м</span>
            </div>
          )}
          {cursor && <div className="coords">{cursor.p[0].toFixed(2)}, {cursor.p[1].toFixed(2)} м
            {cursor.kind === 'vertex' ? ' · угол' : cursor.kind === 'edge' ? ' · грань' : cursor.kind === 'inter' ? ' · пересечение с гранью' : cursor.kind === 'ortho' ? ' · ортогонально' : ''}</div>}
          {busy && <div className="busy-overlay"><div className="progress-card">Модель перестраивается с учётом правок…</div></div>}
          {renaming && (
            <form className="popup rename" style={{ left: renaming.screen[0], top: Math.min(renaming.screen[1], window.innerHeight - 80) }}
              onSubmit={(e) => { e.preventDefault(); renameRoom(renaming.at, renaming.name.trim()) }}>
              <input autoFocus value={renaming.name} placeholder="Название помещения"
                onChange={(e) => setRenaming({ ...renaming, name: e.target.value })} />
              <button type="submit" className="primary">OK</button>
            </form>
          )}
          {popup && (() => {
            const o = popup.o
            const cur = pendingKind(o) ?? o.kind
            const mi = manualIdx(o)
            return (
              <div className="popup" style={{ left: popup.screen[0], top: Math.min(popup.screen[1], window.innerHeight - 260) }}>
                <div className="popup-title">{KIND_LABEL[o.kind]} · {o.width.toFixed(2)} м</div>
                {(['door', 'window', 'vitrage', 'passage', 'wall'] as const).map((k) => (
                  <button key={k} className={cur === k ? 'on' : ''} onClick={() => setOpeningKind(o, k)}>
                    <i style={{ background: KIND_COLOR[k] }} />{KIND_LABEL[k]}{cur === k ? ' ✓' : ''}
                  </button>
                ))}
                {mi >= 0 && (
                  <button className="danger" onClick={() => { removeEdit('add_openings', mi); setPopup(null) }}>
                    Удалить добавленный проём
                  </button>
                )}
              </div>
            )
          })()}
        </div>
        <aside className="editor-side">
          <div className="legend">
            <span><i style={{ background: '#343a40' }} />стены</span>
            <span><i style={{ background: '#868e96' }} />перегородки</span>
            {(['door', 'window', 'vitrage', 'passage'] as const).map((k) => (
              <span key={k}><i style={{ background: KIND_COLOR[k] }} />{KIND_LABEL[k].split(' ')[0].toLowerCase()}</span>
            ))}
            <span><i style={{ background: '#ffd43b' }} />лестницы</span>
          </div>
          <h4>Правки этажа</h4>
          {!rows.length && (
            <p className="hint">Пока нет. Выберите инструмент сверху или кликните проём/помещение.</p>
          )}
          <ul className="edit-list">
            {rows.map(({ key, i, item, at, label }) => (
              <li key={key + i} className={hlOf(key, i) ? 'hl' : ''}
                onMouseEnter={() => setHl(`${key}:${i}`)} onMouseLeave={() => setHl(null)}
                onClick={() => centerOn(at)} title="Показать на плане">
                <span className={`tag ${isApplied(key, item) ? (busy ? 'busy' : 'done') : 'new'}`}>
                  {isApplied(key, item) ? (busy ? 'применяется…' : 'применено') : 'новое'}
                </span>
                <span className="txt">{label}</span>
                <button title="Удалить правку" onClick={(e) => { e.stopPropagation(); removeEdit(key, i) }}>×</button>
              </li>
            ))}
          </ul>
          <p className="hint small-hint">
            Перетаскивание — панорама, колесо — масштаб. Привязка к углам (■) и граням (◆) стен,
            ортогональность от начальной точки. Ctrl+Z — отмена.
            Удалённая из списка «применённая» правка откатится при следующем «Применить».
          </p>
        </aside>
      </div>
    </div>
  )
}
