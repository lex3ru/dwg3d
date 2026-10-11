import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import {
  addOpening, addWall, allSides, ends, findRooms, moveNode, moveOpening, moveWall, offsetWall, openingRect, outlines, removeOpening, removeWall, wallsAt,
  type Floor, type Opening, type OpeningKind, type Room, type Wall, type XY,
} from '@/plan'
import { add, dist, dot, inRing, lerp, mul, perp, project, sub, unit } from '@/plan/vec'
import { areaText, cmText } from './format'
import { atLength, openingSpot, snap, type OpeningSpot, type Snap } from './snap'
import { clearances, openingShape } from './symbols'
import { moveUnderlay, onUnderlay, underlayTransform } from './underlay'
import { fitView, gridSteps, planTransform, toPlan, toScreen, zoomAt, type View } from './view'

/** underlay: drag the picture under the plan; calibrate: pick two points on it to set its scale */
export type Tool = 'select' | 'wall' | 'opening' | 'underlay' | 'calibrate'
export type Selection = { kind: 'wall'; id: string } | { kind: 'node'; id: string } | { kind: 'room'; key: string } | { kind: 'opening'; id: string }

const SNAP_PX = 10   // snap radius on screen
const HIT_PX = 6     // how near a click must be to a node or a thin wall
const DRAG_PX = 4    // movement that turns a click into a drag

/**
 * The plan drawing. It stays light in both themes, like paper: walls dark,
 * rooms pale. Scoped to <svg class="sketch">.
 */
const CSS = `
.sketch { background: #fcfcfb; touch-action: none; user-select: none; }
.sketch .grid-minor { stroke: #eef0f2; }
.sketch .grid-major { stroke: #dde1e5; }
.sketch .axis { stroke: #c5cbd1; }
.sketch .below { fill: #adb5bd; fill-opacity: .25; }
.sketch .room { fill: #fff3bf; fill-opacity: .55; fill-rule: evenodd; }
.sketch .room.sel { fill: #d0ebff; fill-opacity: .8; }
.sketch .wall { fill: #343a40; }
.sketch .wall.partition { fill: #868e96; }
.sketch .wall.sel { fill: #1c7ed6; }
.sketch .wall.bad { fill: #e03131; }
.sketch .preview { fill: #1c7ed6; fill-opacity: .45; }
.sketch .dim { font-size: 11px; fill: #495057; paint-order: stroke; stroke: #fcfcfb; stroke-width: 3px; stroke-linejoin: round; font-family: inherit; }
.sketch .room-name { font-size: 12px; font-weight: 600; fill: #343a40; paint-order: stroke; stroke: #fcfcfb; stroke-width: 3px; font-family: inherit; }
.sketch .room-area { font-size: 11px; fill: #c92a2a; paint-order: stroke; stroke: #fcfcfb; stroke-width: 3px; font-family: inherit; }
.sketch .len { font-size: 12px; font-weight: 600; fill: #1c7ed6; paint-order: stroke; stroke: #fcfcfb; stroke-width: 3px; font-family: inherit; }
.sketch .guide { stroke: #1c7ed6; stroke-width: 1; stroke-dasharray: 4 3; }
.sketch .node { fill: #fff; stroke: #1c7ed6; stroke-width: 1.5; }
.sketch .node.sel { fill: #1c7ed6; }
.sketch .gap { fill: #fcfcfb; }
.sketch .gap.sel { fill: #d0ebff; }
.sketch .gap.bad { fill: #ffc9c9; }
.sketch .gap.preview { fill: #d0ebff; fill-opacity: .9; }
.sketch .op-line { fill: none; stroke: #343a40; stroke-width: 1.2; vector-effect: non-scaling-stroke; }
.sketch .op-swing { fill: none; stroke: #868e96; stroke-width: 1; stroke-dasharray: 4 3; vector-effect: non-scaling-stroke; }
.sketch .op-preview .op-line, .sketch .op-preview .op-swing { stroke: #1c7ed6; }
.sketch .clear { font-size: 11px; font-weight: 600; fill: #2b8a3e; paint-order: stroke; stroke: #fcfcfb; stroke-width: 3px; font-family: inherit; }
.sketch .mark { fill: none; stroke-width: 2; }
.sketch .mark.node { stroke: #e8590c; }
.sketch .mark.wall, .sketch .mark.cross { stroke: #2b8a3e; }
.sketch .mark.align, .sketch .mark.straight, .sketch .mark.free { stroke: #1c7ed6; }
`


function polyPath(rings: XY[][]): string {
  return rings.map(r => 'M' + r.map(p => `${p[0]} ${p[1]}`).join('L') + 'Z').join('')
}

function segPoly(a: XY, b: XY, t: number): XY[] {
  const n = perp(unit(sub(b, a)))
  const h = t / 2
  return [[a[0] - n[0] * h, a[1] - n[1] * h], [b[0] - n[0] * h, b[1] - n[1] * h], [b[0] + n[0] * h, b[1] + n[1] * h], [a[0] + n[0] * h, a[1] + n[1] * h]]
}

function bounds(f: Floor): [number, number, number, number] | null {
  const ps = Object.values(f.nodes)
  if (!ps.length) return null
  const xs = ps.map(p => p[0]), ys = ps.map(p => p[1])
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
}

/** Text along a line on screen, kept upright. */
function along(a: XY, b: XY): number {
  let deg = (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI
  if (deg > 90) deg -= 180
  if (deg <= -90) deg += 180
  return deg
}

type Drag =
  | { kind: 'pan'; start: XY; view: View; moved: boolean }
  | { kind: 'opening'; id: string; base: Floor; start: XY; moved: boolean }
  | { kind: 'underlay'; base: Floor; start: XY; startPlan: XY; moved: boolean }
  | { kind: 'node'; id: string; base: Floor; start: XY; moved: boolean }
  | { kind: 'wall'; id: string; base: Floor; start: XY; startPlan: XY; moved: boolean }
  | { kind: 'draw'; start: XY; moved: boolean }
  | { kind: 'click'; start: XY; moved: boolean }

export function Canvas({ floor, below, tool, wallProps, openingProps, selection, onSelect, onCommit, fitSignal, bad, underlayUrl, onCalibrate }: {
  floor: Floor
  /** the floor below, drawn faintly underneath */
  below: Floor | null
  tool: Tool
  /** the wall a new one will be */
  wallProps: Omit<Wall, 'a' | 'b'>
  /** the opening a new one will be */
  openingProps: { kind: OpeningKind; width: number }
  selection: Selection | null
  onSelect: (s: Selection | null) => void
  onCommit: (f: Floor) => void
  /** changes when the plan must be fitted to the screen */
  fitSignal: number
  /** walls and openings with problems (crossing, an opening off its wall, …): drawn red */
  bad: Set<string>
  /** where the floor's picture is fetched from */
  underlayUrl: string | null
  /** two points picked on the picture with the «calibrate» tool */
  onCalibrate: (a: XY, b: XY) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [measured, setSize] = useState<XY | null>(null)
  const size = useMemo<XY>(() => measured ?? [800, 600], [measured])
  const [view, setView] = useState<View>({ cx: 0, cy: 0, scale: 50 })
  const [preview, setPreview] = useState<Floor | null>(null)
  const [cursor, setCursor] = useState<Snap | null>(null)
  // the wall being drawn: from its last point; `first` closes the chain
  const [chain, setChain] = useState<{ from: XY; first: XY } | null>(null)
  const [typed, setTyped] = useState('')
  // where a new opening would go
  const [spot, setSpot] = useState<OpeningSpot | null>(null)
  // the points picked for the picture's scale
  const [cal, setCal] = useState<XY[]>([])
  const [space, setSpace] = useState(false)
  const drag = useRef<Drag | null>(null)

  const shown = preview ?? floor
  const lines = useMemo(() => outlines(shown), [shown])
  const bearingLines = useMemo(() => outlines({ ...shown, walls: Object.fromEntries(Object.entries(shown.walls).filter(([, w]) => w.kind === 'bearing')) }), [shown])
  const sides = useMemo(() => allSides(shown, lines), [shown, lines])
  const rooms = useMemo(() => findRooms(shown, lines), [shown, lines])
  const belowLines = useMemo(() => (below ? outlines(below) : null), [below])
  const tol = SNAP_PX / view.scale

  const S = useCallback((p: XY) => toScreen(view, size, p), [view, size])

  // ---------------------------------------------------------------- size, fit, wheel
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize([el.clientWidth || 1, el.clientHeight || 1]))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  // fitted once the size is known, then whenever asked
  const [fitted, setFitted] = useState<number | null>(null)
  if (measured && fitted !== fitSignal) { setFitted(fitSignal); setView(fitView(bounds(floor), size)) }
  useEffect(() => {
    const el = svg.current
    if (!el) return
    const wheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      setView(v => zoomAt(v, [r.width, r.height], [e.clientX - r.left, e.clientY - r.top], Math.exp(-e.deltaY * 0.0015)))
    }
    el.addEventListener('wheel', wheel, { passive: false })
    return () => el.removeEventListener('wheel', wheel)
  }, [])

  // a tool change ends the wall being drawn
  const [lastTool, setLastTool] = useState(tool)
  if (tool !== lastTool) { setLastTool(tool); setChain(null); setTyped(''); setCursor(null); setSpot(null); setCal([]) }

  // ---------------------------------------------------------------- hits
  const hit = useCallback((p: XY): Selection | null => {
    const t = HIT_PX / view.scale
    let node: string | null = null, nd = t
    for (const [id, q] of Object.entries(floor.nodes)) { const d = dist(p, q); if (d <= nd) { node = id; nd = d } }
    if (node) return { kind: 'node', id: node }
    for (const id of Object.keys(floor.openings)) {
      const r = openingRect(floor, id)
      if (inRing(p, r) || project(p, lerp(r[0], r[3], 0.5), lerp(r[1], r[2], 0.5)).d <= t) return { kind: 'opening', id }
    }
    for (const [id, w] of Object.entries(floor.walls)) {
      const o = lines[id]
      if ((o && inRing(p, o.poly)) || project(p, ...ends(floor, w)).d <= Math.max(t, w.thickness / 2)) return { kind: 'wall', id }
    }
    const room = rooms.find(r => inRing(p, r.contour) && !r.holes.some(h => inRing(p, h)))
    return room ? { kind: 'room', key: room.key } : null
  }, [floor, lines, rooms, view.scale])

  // ---------------------------------------------------------------- drawing walls
  const place = useCallback((to: XY, keepGoing: boolean) => {
    if (!chain) return
    const r = addWall(floor, chain.from, to, wallProps)
    if (r.walls.length) onCommit(r.floor)
    const closed = dist(to, chain.first) <= 1e-6
    setChain(keepGoing && !closed ? { from: to, first: chain.first } : null)
    setTyped('')
  }, [chain, floor, wallProps, onCommit])

  const pointAt = (e: { clientX: number; clientY: number }): { screen: XY; plan: XY } => {
    const r = svg.current!.getBoundingClientRect()
    const screen: XY = [e.clientX - r.left, e.clientY - r.top]
    return { screen, plan: toPlan(view, size, screen) }
  }

  // fingers on the plan: two of them zoom and pan it, whatever the tool
  const touches = useRef(new Map<number, XY>())
  const pinch = useRef<{ d0: number; mid0: XY; view: View } | null>(null)
  const pinchStart = () => {
    const [p, q] = [...touches.current.values()]
    pinch.current = { d0: Math.max(dist(p, q), 1), mid0: [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2], view }
    // what the first finger began is not meant
    if (drag.current?.kind === 'draw') setChain(null)
    drag.current = null
    setPreview(null)
  }

  const down = (e: ReactPointerEvent<SVGSVGElement>) => {
    const { screen, plan } = pointAt(e)
    try { svg.current!.setPointerCapture(e.pointerId) } catch { /* a pointer the browser no longer tracks */ }
    if (e.pointerType === 'touch') {
      touches.current.set(e.pointerId, screen)
      if (touches.current.size === 2) { pinchStart(); return }
      if (touches.current.size > 2) return
    }
    if (e.button === 1 || e.button === 2 || space) {
      drag.current = { kind: 'pan', start: screen, view, moved: false }
      return
    }
    if (e.button !== 0) return
    if (tool === 'wall') {
      const s = snap(floor, plan, { tol, from: chain?.from, free: e.altKey })
      if (!chain) {
        setChain({ from: s.p, first: s.p })
        drag.current = { kind: 'draw', start: screen, moved: false }
      } else {
        drag.current = { kind: 'click', start: screen, moved: false }
      }
      return
    }
    if (tool === 'calibrate') {
      const pts = cal.length >= 2 ? [plan] : [...cal, plan]
      setCal(pts)
      if (pts.length === 2) onCalibrate(pts[0], pts[1])
      return
    }
    if (tool === 'underlay') {
      if (floor.underlay && onUnderlay(floor.underlay, plan)) drag.current = { kind: 'underlay', base: floor, start: screen, startPlan: plan, moved: false }
      else drag.current = { kind: 'pan', start: screen, view, moved: false }
      return
    }
    if (tool === 'opening') {
      const s = openingSpot(floor, plan, openingProps.width, tol, undefined, lines)
      const r = s && addOpening(floor, s.wall, s.at, openingProps.kind, { width: openingProps.width, side: s.side })
      if (r) { onCommit(r.floor); onSelect({ kind: 'opening', id: r.id }) }
      return
    }
    const h = hit(plan)
    if (h?.kind === 'opening') drag.current = { kind: 'opening', id: h.id, base: floor, start: screen, moved: false }
    else if (h?.kind === 'node') drag.current = { kind: 'node', id: h.id, base: floor, start: screen, moved: false }
    else if (h?.kind === 'wall') drag.current = { kind: 'wall', id: h.id, base: floor, start: screen, startPlan: plan, moved: false }
    else drag.current = { kind: 'pan', start: screen, view, moved: false }
    onSelect(h)
  }

  const move = (e: ReactPointerEvent<SVGSVGElement>) => {
    const { screen, plan } = pointAt(e)
    if (e.pointerType === 'touch' && touches.current.has(e.pointerId)) touches.current.set(e.pointerId, screen)
    if (pinch.current && touches.current.size >= 2) {
      const [p, q] = [...touches.current.values()]
      const { d0, mid0, view: v0 } = pinch.current
      const mid: XY = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2]
      const zoomed = zoomAt(v0, size, mid0, dist(p, q) / d0)
      setView({ ...zoomed, cx: zoomed.cx - (mid[0] - mid0[0]) / zoomed.scale, cy: zoomed.cy + (mid[1] - mid0[1]) / zoomed.scale })
      return
    }
    const d = drag.current
    if (d && !d.moved && dist(screen, d.start) > DRAG_PX) d.moved = true
    if (d?.kind === 'pan') {
      if (d.moved) setView({ ...d.view, cx: d.view.cx - (screen[0] - d.start[0]) / d.view.scale, cy: d.view.cy + (screen[1] - d.start[1]) / d.view.scale })
      return
    }
    if (d?.kind === 'node' && d.moved) {
      const s = snap(d.base, plan, { tol, skip: [d.id], free: e.altKey })
      setCursor(s)
      setPreview(moveNode(d.base, d.id, s.p))
      return
    }
    if (d?.kind === 'underlay' && d.moved && d.base.underlay) {
      setPreview({ ...d.base, underlay: moveUnderlay(d.base.underlay, sub(plan, d.startPlan)) })
      return
    }
    if (d?.kind === 'opening' && d.moved) {
      const s = openingSpot(d.base, plan, d.base.openings[d.id].width, tol, d.id)
      if (s) setPreview(moveOpening(d.base, d.id, s.at, s.wall))
      return
    }
    if (d?.kind === 'wall' && d.moved) {
      const w = d.base.walls[d.id]
      const [a, b] = ends(d.base, w)
      const n = perp(unit(sub(b, a)))
      const off = e.altKey ? dot(sub(plan, d.startPlan), n) : Math.round(dot(sub(plan, d.startPlan), n) * 100) / 100
      setPreview(offsetWall(d.base, d.id, off))
      return
    }
    if (tool === 'wall') setCursor(snap(floor, plan, { tol, from: chain?.from, free: e.altKey }))
    else setCursor(null)
    setSpot(tool === 'opening' ? openingSpot(floor, plan, openingProps.width, tol, undefined, lines) : null)
  }

  const up = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (e.pointerType === 'touch') {
      touches.current.delete(e.pointerId)
      if (pinch.current) {
        if (touches.current.size < 2) pinch.current = null
        drag.current = null
        return
      }
    }
    const d = drag.current
    drag.current = null
    if (!d) return
    const { plan } = pointAt(e)
    if (d.kind === 'node' && d.moved) {
      const s = snap(d.base, plan, { tol, skip: [d.id], free: e.altKey })
      const next = moveNode(d.base, d.id, s.p, true)
      setPreview(null)
      setCursor(null)
      onCommit(next)
      if (!(d.id in next.nodes)) onSelect(null)
      return
    }
    if ((d.kind === 'wall' || d.kind === 'opening' || d.kind === 'underlay') && d.moved) {
      if (preview) onCommit(preview)
      setPreview(null)
      return
    }
    if (d.kind === 'draw' && d.moved && chain) {
      // drawn by dragging, as in RemPlanner: one wall, then the next starts afresh
      const s = snap(floor, plan, { tol, from: chain.from, free: e.altKey })
      place(s.p, false)
      return
    }
    if (d.kind === 'click' && !d.moved) {
      const s = snap(floor, plan, { tol, from: chain?.from, free: e.altKey })
      place(s.p, true)
    }
  }

  // ---------------------------------------------------------------- keys
  useEffect(() => {
    const typing = (e: KeyboardEvent) => e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement
    const onDown = (e: KeyboardEvent) => {
      if (typing(e) || e.ctrlKey || e.metaKey) return
      if (e.code === 'Space') { setSpace(true); e.preventDefault(); return }
      if (chain && /^[0-9]$/.test(e.key)) { setTyped(t => (t + e.key).slice(0, 6)); e.preventDefault(); return }
      if (chain && e.key === 'Backspace' && typed) { setTyped(t => t.slice(0, -1)); e.preventDefault(); return }
      if (e.key === 'Enter' && chain) {
        const to = typed && cursor ? atLength(chain.from, cursor.p, Number(typed) / 100) : null
        if (to) place([Math.round(to[0] * 1000) / 1000, Math.round(to[1] * 1000) / 1000], true)
        else { setChain(null); setTyped('') }
        e.preventDefault()
        return
      }
      if (e.key === 'Escape') {
        if (typed) setTyped('')
        else if (chain) setChain(null)
        else onSelect(null)
        return
      }
      const arrow = ({ ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] } as Record<string, XY>)[e.key]
      if (arrow && selection && !chain) {
        // a centimetre a press, ten with Shift; an opening slides along its wall
        const step = e.shiftKey ? 0.1 : 0.01
        const d: XY = [arrow[0] * step, arrow[1] * step]
        if (selection.kind === 'node') onCommit(moveNode(floor, selection.id, add(floor.nodes[selection.id], d)))
        if (selection.kind === 'wall') onCommit(moveWall(floor, selection.id, d))
        if (selection.kind === 'opening') {
          const o = floor.openings[selection.id], w = floor.walls[o.wall]
          const dir = unit(sub(floor.nodes[w.b], floor.nodes[w.a]))
          onCommit(moveOpening(floor, selection.id, o.at + dot(d, dir)))        // the step as it falls along the wall
        }
        e.preventDefault()
        return
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && selection) {
        if (selection.kind === 'wall') onCommit(removeWall(floor, selection.id))
        if (selection.kind === 'opening') onCommit(removeOpening(floor, selection.id))
        if (selection.kind === 'node') onCommit(wallsAt(floor, selection.id).reduce((f, w) => removeWall(f, w), floor))
        if (selection.kind !== 'room') onSelect(null)
        e.preventDefault()
      }
    }
    const onUp = (e: KeyboardEvent) => { if (e.code === 'Space') setSpace(false) }
    addEventListener('keydown', onDown)
    addEventListener('keyup', onUp)
    return () => { removeEventListener('keydown', onDown); removeEventListener('keyup', onUp) }
  }, [chain, typed, cursor, selection, floor, place, onSelect, onCommit])

  // ---------------------------------------------------------------- what to draw
  const grid = useMemo(() => {
    const { minor, major } = gridSteps(view.scale)
    const [x0, y1] = toPlan(view, size, [0, 0]), [x1, y0] = toPlan(view, size, size)
    const out: { x1: number; y1: number; x2: number; y2: number; cls: string }[] = []
    const cls = (v: number) => (Math.abs(v) < minor / 2 ? 'axis' : Math.abs(v / major - Math.round(v / major)) < 1e-6 ? 'grid-major' : 'grid-minor')
    for (let x = Math.ceil(x0 / minor) * minor; x <= x1; x += minor) {
      const s = toScreen(view, size, [x, 0])[0]
      out.push({ x1: s, y1: 0, x2: s, y2: size[1], cls: cls(x) })
    }
    for (let y = Math.ceil(y0 / minor) * minor; y <= y1; y += minor) {
      const s = toScreen(view, size, [0, y])[1]
      out.push({ x1: 0, y1: s, x2: size[0], y2: s, cls: cls(y) })
    }
    return out
  }, [view, size])

  // the opening about to be placed, and the one whose distances to the corners are shown
  const ghost: Opening | null = tool === 'opening' && spot
    ? { wall: spot.wall, kind: openingProps.kind, at: spot.at, width: openingProps.width, height: 2, sill: 0, hinge: 'a', side: spot.side } : null
  const gauged: Opening | null = ghost ?? (selection?.kind === 'opening' ? shown.openings[selection.id] ?? null : null)
  const selectedRoom: Room | undefined = selection?.kind === 'room' ? rooms.find(r => r.key === selection.key) : undefined
  const drawing = tool === 'wall' && chain && cursor
  const to = drawing ? (typed ? atLength(chain.from, cursor.p, Number(typed) / 100) ?? cursor.p : cursor.p) : null
  const hint = tool === 'calibrate'
    ? cal.length === 1 ? 'Щёлкните второй конец отрезка, длина которого известна (размер на чертеже, стена)'
      : cal.length === 2 ? 'Введите длину отрезка справа, в панели «Подложка»; щелчок на картинке начнёт отрезок заново'
        : 'Щёлкните на картинке начало отрезка известной длины — например, размерную линию или стену'
    : tool === 'underlay'
    ? 'Перетащите картинку, чтобы совместить её с нарисованными стенами'
    : tool === 'opening'
    ? 'Наведите на стену и щёлкните: проём встанет под курсором, зелёным — расстояния до углов; открывание — в сторону курсора'
    : tool === 'wall'
    ? chain
      ? 'Щелчок — следующий угол, по первому углу — замкнуть; цифры — длина в см и Enter; Esc — закончить'
      : 'Щелчок — начать стену цепочкой, или протяните мышью одну стену; Alt — без привязок'
    : 'Щелчок выбирает стену, угол или помещение; перетаскивание двигает угол или стену; Delete — удалить; пробел или правая кнопка — сдвинуть план'

  return (
    <div ref={box} className="relative h-full w-full overflow-hidden">
      <style>{CSS}</style>
      <svg ref={svg} className="sketch absolute inset-0 h-full w-full" width={size[0]} height={size[1]}
        style={{ cursor: space ? 'grab' : tool === 'select' ? 'default' : 'crosshair' }}
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onPointerLeave={() => { if (!drag.current) { setCursor(null); setSpot(null) } }}
        onContextMenu={e => e.preventDefault()} onDoubleClick={() => { setChain(null); setTyped('') }}
        data-testid="sketch-canvas">
        <g>{grid.map((l, i) => <line key={i} {...l} className={l.cls} />)}</g>
        <g transform={planTransform(view, size)}>
          {shown.underlay && !shown.underlay.hidden && underlayUrl && (
            <image href={underlayUrl} width={shown.underlay.width} height={shown.underlay.height} preserveAspectRatio="none"
              transform={underlayTransform(shown.underlay)} opacity={shown.underlay.opacity} data-testid="sketch-underlay" />
          )}
          {belowLines && <g>{Object.values(belowLines).map((o, i) => <path key={i} className="below" d={polyPath([o.poly])} />)}</g>}
          {rooms.map(r => <path key={r.key} className={r === selectedRoom ? 'room sel' : 'room'} d={polyPath([r.contour, ...r.holes])} />)}
          {/* walls of a kind are one path: separate ones would show hairline seams where they meet */}
          {/* partitions under the bearing walls, which are joined among themselves only: whole where a partition meets them */}
          <path className="wall partition"
            d={polyPath(Object.entries(shown.walls).filter(([id, w]) => w.kind === 'partition' && lines[id]).map(([id]) => lines[id].poly))} />
          <path className="wall" d={polyPath(Object.values(bearingLines).map(o => o.poly))} />
          {Object.keys(shown.walls).filter(id => lines[id] && (bad.has(id) || (selection?.kind === 'wall' && selection.id === id))).map(id => (
            // the wall's own body, without the junction it shares with the walls it meets
            <path key={id} d={polyPath([[lines[id].aMinus, lines[id].bMinus, lines[id].bPlus, lines[id].aPlus]])}
              className={selection?.kind === 'wall' && selection.id === id ? 'wall sel' : 'wall bad'} />
          ))}
          {Object.entries(shown.openings).map(([id, o]) => (
            <OpeningMark key={id} floor={shown} o={o} overlap={0.6 / view.scale}
              cls={selection?.kind === 'opening' && selection.id === id ? 'sel' : bad.has(id) ? 'bad' : ''} />
          ))}
          {ghost && <OpeningMark floor={shown} o={ghost} overlap={0.6 / view.scale} cls="preview" />}
          {drawing && to && dist(chain.from, to) > 1e-6 && <path className="preview" d={polyPath([segPoly(chain.from, to, wallProps.thickness)])} />}
        </g>
        <g>
          {Object.entries(shown.walls).map(([id, w]) => {
            const s = sides[id], o = lines[id]
            if (!s || !o) return null
            const [a, b] = ends(shown, w).map(S)
            if (dist(a, b) < 60) return null
            const n = unit(perp(sub(b, a)))   // on screen: perp of a screen vector points to the plan's minus side
            const label = (p0: XY, p1: XY, value: number, sign: number) => {
              const m0 = S(p0), m1 = S(p1)
              const mid: XY = [(m0[0] + m1[0]) / 2 - n[0] * 9 * sign, (m0[1] + m1[1]) / 2 - n[1] * 9 * sign]
              return <text className="dim" x={mid[0]} y={mid[1]} textAnchor="middle" dominantBaseline="middle"
                transform={`rotate(${along(m0, m1)} ${mid[0]} ${mid[1]})`}>{cmText(value)}</text>
            }
            return (
              <g key={id}>
                {label(o.aPlus, o.bPlus, s.plus, 1)}
                {label(o.aMinus, o.bMinus, s.minus, -1)}
              </g>
            )
          })}
          {rooms.map(r => {
            const [x, y] = S(r.labelAt)
            const name = r.label?.name || (r.label?.number ? '' : 'Помещение')
            return (
              <g key={r.key} pointerEvents="none">
                <text className="room-name" x={x} y={y - 7} textAnchor="middle">{[r.label?.number, name].filter(Boolean).join(' ')}</text>
                <text className="room-area" x={x} y={y + 8} textAnchor="middle">{areaText(r.area)}</text>
              </g>
            )
          })}
          {gauged && (() => {
            const o = gauged
            const w = shown.walls[o.wall], sd = sides[o.wall]
            if (!w || !sd) return null
            const [a, b] = ends(shown, w)
            const l = dist(a, b), d = unit(sub(b, a)), n = perp(d)
            const [left, right] = clearances(o, sd.from, sd.to)
            const at = (x: number) => add(lerp(a, b, x / l), mul(n, w.thickness / 2 + 14 / view.scale))
            const label = (x: number, value: number) => {
              const [sx, sy] = S(at(x))
              return value > 0.005 && <text className="clear" x={sx} y={sy} textAnchor="middle" dominantBaseline="middle"
                transform={`rotate(${along(S(a), S(b))} ${sx} ${sy})`}>{cmText(value)}</text>
            }
            return <g>{label(sd.from + left / 2, left)}{label(o.at + o.width / 2 + right / 2, right)}</g>
          })()}
          {cal.length > 0 && (() => {
            const [a, b] = [S(cal[0]), cal[1] ? S(cal[1]) : null]
            return (
              <g pointerEvents="none">
                {b && <line className="guide" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />}
                {[a, b].filter(Boolean).map((p, i) => <circle key={i} className="mark node" cx={p![0]} cy={p![1]} r={6} />)}
              </g>
            )
          })()}
          {cursor?.guides.map(([p, q], i) => { const [a, b] = [S(p), S(q)]; return <line key={i} className="guide" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} /> })}
          {drawing && to && (() => {
            const [a, b] = [S(chain.from), S(to)]
            const mid: XY = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
            return <text className="len" x={mid[0]} y={mid[1] - 14} textAnchor="middle" transform={`rotate(${along(a, b)} ${mid[0]} ${mid[1]})`}>
              {typed ? `${typed} см ⏎` : `${cmText(dist(chain.from, to))} см`}
            </text>
          })()}
          {tool === 'select' && Object.entries(shown.nodes).map(([id, p]) => {
            const [x, y] = S(p)
            return <circle key={id} className={selection?.kind === 'node' && selection.id === id ? 'node sel' : 'node'} cx={x} cy={y} r={3.5} />
          })}
          {cursor && (() => {
            const [x, y] = S(cursor.p)
            return cursor.kind === 'node'
              ? <circle className="mark node" cx={x} cy={y} r={7} />
              : cursor.kind === 'wall' || cursor.kind === 'cross'
                ? <rect className={`mark ${cursor.kind}`} x={x - 5} y={y - 5} width={10} height={10} />
                : <path className={`mark ${cursor.kind}`} d={`M${x - 6} ${y}H${x + 6}M${x} ${y - 6}V${y + 6}`} />
          })()}
        </g>
      </svg>
      <div className="pointer-events-none absolute bottom-2 left-2 right-2 flex items-end justify-between gap-3 text-xs text-[#495057]">
        {/* about keys and the mouse: not for a phone */}
        <span className="rounded bg-white/80 px-2 py-1 shadow-sm max-md:hidden" data-testid="sketch-hint">{hint}</span>
        {cursor && <span className="shrink-0 rounded bg-white/80 px-2 py-1 tabular-nums shadow-sm">x {cmText(cursor.p[0])} · y {cmText(cursor.p[1])} см</span>}
      </div>
    </div>
  )
}

function OpeningMark({ floor, o, overlap, cls }: { floor: Floor; o: Opening; overlap: number; cls: string }) {
  if (!floor.walls[o.wall]) return null
  const sh = openingShape(floor, o, overlap)
  return (
    <g className={cls === 'preview' ? 'op-preview' : undefined}>
      <path className={`gap ${cls}`} d={sh.gap} />
      <path className="op-line" d={sh.lines} />
      {sh.swing && <path className="op-swing" d={sh.swing} />}
    </g>
  )
}
