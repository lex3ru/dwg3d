import { useEffect, useRef, useState } from 'react'
import type { FloorMeta, Layer, RowOp, ShapeObject, XY } from '../api'
import type { Computed, RouteProps, RouteStop, Rules } from '../viewer/routing'

/** A click on the plan while the editor waits for one. */
export interface PlanClick { floor: string; at: XY; room: { id?: number; name: string } | null }

/** Something being drawn: a route's first stops, a zone's outline, a cable's line. */
export type ShapeDraft =
  | { what: 'route'; id: string; flow: string; name: string; stops: RouteStop[] }
  | { what: 'zone'; zone: string; name: string; floor: string; pts: XY[] }
  | { what: 'cable'; cable: string; name: string; reserve: number; floor: string; pts: XY[] }

const newId = () => Math.random().toString(36).slice(2, 10)
export const polyLength = (pts: XY[]) => {
  let n = 0
  for (let i = 1; i < pts.length; i++) n += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
  return n
}
export const polyArea = (pts: XY[]) => {
  let a = 0
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) a += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1])
  return Math.abs(a / 2)
}
export const routeProps = (s: ShapeObject) => (s.props ?? {}) as unknown as RouteProps

/**
 * Drawing and changing routes, zones and cable lines of the layer being
 * edited: the drafts, which clicks on the plan go where, saving (a route's way
 * is computed first), and recomputing routes made on an older build.
 */
export function useShapeEditor(p: {
  active: boolean
  layer: Layer | null
  rules: Rules | null
  routes: ShapeObject[]               // all routes of the drawing (stale ones are recomputed)
  activeFloor: FloorMeta | null
  build: number
  editable: boolean
  save: (ops: RowOp[]) => Promise<boolean>
  compute: (stops: RouteStop[]) => Promise<Computed>
  onSelect: (id: string | null) => void
  onDraft: (d: { floor: string; pts: XY[]; closed: boolean } | null) => void
  pickRef: React.MutableRefObject<((c: PlanClick) => void) | null>
  onPicking: (on: boolean) => void
}) {
  const [draft, setDraft] = useState<ShapeDraft | null>(null)
  const [adding, setAdding] = useState<string | null>(null)     // a saved route taking more stops
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const recomputing = useRef(false)
  const { onDraft, onPicking, pickRef } = p

  const run = async (what: string, ops: RowOp[]) => {
    setBusy(what)
    setErr(null)
    const ok = await p.save(ops)
    setBusy(null)
    return ok
  }
  /** Compute the way through the stops and save the route (create or update). */
  const saveRoute = async (id: string, props: RouteProps, existing: ShapeObject | null) => {
    let full: RouteProps = { ...props, path: null, problem: undefined }
    if (props.stops.length >= 2) {
      setBusy('Расчёт пути…')
      const c = await p.compute(props.stops)
      full = { ...props, path: c.path, length: c.length, time: c.time, floors_changed: c.floors_changed, build: p.build,
        ...(c.problem ? { problem: c.problem } : { problem: undefined }) }
    }
    const clean = JSON.parse(JSON.stringify(full)) as Record<string, unknown>
    const op: RowOp = existing
      ? { op: 'update', id, version: existing.version, props: clean }
      : { op: 'create', id, geom: 'route', layer: p.layer?.id, props: clean }
    return run('Сохранение…', [op])
  }
  const update = (s: ShapeObject, props: Record<string, unknown>) => run('Сохранение…', [{ op: 'update', id: s.id, version: s.version, props }])
  const remove = (s: ShapeObject) => run('Удаление…', [{ op: 'delete', id: s.id, version: s.version }])

  // recompute routes made on another build (the plan changed), when allowed to
  useEffect(() => {
    if (!p.active || !p.editable || recomputing.current) return
    const stale = p.routes.filter((r) => { const x = routeProps(r); return x.stops?.length >= 2 && (x.build !== p.build || !x.path) })
    if (!stale.length) return
    recomputing.current = true
    ;(async () => {
      for (const r of stale) await saveRoute(r.id, routeProps(r), r)
      recomputing.current = false
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.active, p.build, p.editable, p.routes.length])

  const addStop = async (st: RouteStop) => {
    if (draft?.what === 'route') {
      const stops = [...draft.stops, st]
      if (stops.length < 2) return setDraft({ ...draft, stops })
      const d = draft
      setDraft(null)
      setAdding(d.id)
      if (await saveRoute(d.id, { flow: d.flow, name: d.name.trim(), stops }, null)) p.onSelect(d.id)
      return
    }
    const r = p.routes.find((x) => x.id === adding)
    if (r) await saveRoute(r.id, { ...routeProps(r), stops: [...routeProps(r).stops, st] }, r)
  }
  const finish = async () => {
    if (!draft || draft.what === 'route') { setDraft(null); setAdding(null); return }
    const need = draft.what === 'cable' ? 2 : 3
    if (draft.pts.length < need) return
    const id = newId()
    const ok = await run('Сохранение…', [draft.what === 'cable'
      ? { op: 'create', id, geom: 'polyline', layer: p.layer?.id, floor: draft.floor, points: draft.pts,
        props: { cable: draft.cable, name: draft.name.trim(), reserve: draft.reserve } }
      : { op: 'create', id, geom: 'polygon', layer: p.layer?.id, floor: draft.floor, points: draft.pts,
        props: { zone: draft.zone, name: draft.name.trim() } }])
    setDraft(null)
    if (ok) p.onSelect(id)
  }
  const cancel = () => { setDraft(null); setAdding(null); setErr(null) }

  const needFloor = () => { if (!p.activeFloor) setErr('Выберите этаж в дереве или на ленте этажей'); return p.activeFloor }
  const startRoute = () => {
    p.onSelect(null)
    setDraft({ what: 'route', id: newId(), flow: Object.keys(p.rules?.flows ?? {})[0] ?? 'patients', name: '', stops: [] })
  }
  const startZone = () => {
    const f = needFloor()
    if (!f) return
    p.onSelect(null)
    setDraft({ what: 'zone', zone: Object.keys(p.rules?.zone_kinds ?? {})[0] ?? 'clean', name: '', floor: f.id, pts: [] })
  }
  const startCable = () => {
    const f = needFloor()
    if (!f) return
    p.onSelect(null)
    setDraft({ what: 'cable', cable: Object.keys(p.rules?.cables ?? {})[0] ?? 'utp', name: '', reserve: 10, floor: f.id, pts: [] })
  }

  // ---- clicks on the plan
  const picking = !!adding || !!draft
  useEffect(() => {
    onPicking(picking)
    pickRef.current = !picking ? null : (c: PlanClick) => {
      if (draft && draft.what !== 'route') {
        if (draft.pts.length && c.floor !== draft.floor) return setErr(draft.what === 'zone' ? 'Зона обводится на одном этаже' : 'Трасса рисуется на одном этаже')
        const first = draft.pts[0], last = draft.pts[draft.pts.length - 1]
        if (draft.what === 'zone' && draft.pts.length >= 3 && Math.hypot(c.at[0] - first[0], c.at[1] - first[1]) < 0.5) return void finish()
        if (draft.what === 'cable' && draft.pts.length >= 2 && Math.hypot(c.at[0] - last[0], c.at[1] - last[1]) < 0.3) return void finish()
        setDraft({ ...draft, floor: c.floor, pts: [...draft.pts, c.at] })
        return
      }
      addStop({ floor: c.floor, at: c.at, room: c.room?.id ?? null, label: c.room?.name || '' })
    }
    return () => { pickRef.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picking, adding, draft, p.routes])
  useEffect(() => { onDraft(draft && draft.what !== 'route' ? { floor: draft.floor, pts: draft.pts, closed: false } : null) }, [draft, onDraft])
  useEffect(() => { if (!p.active) cancel() }, [p.active])
  useEffect(() => () => { onPicking(false); onDraft(null) }, [onPicking, onDraft])
  // Esc / Enter while drawing
  useEffect(() => {
    if (!picking) return
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t?.tagName === 'INPUT' || t?.tagName === 'TEXTAREA' || t?.tagName === 'SELECT') return
      if (e.key === 'Escape') { e.stopImmediatePropagation(); cancel() }
      if (e.key === 'Enter' && draft && draft.what !== 'route') finish()
    }
    window.addEventListener('keydown', on, true)
    return () => window.removeEventListener('keydown', on, true)
  })

  const hint = busy ?? err ?? (draft?.what === 'route'
    ? `Щёлкните на плане остановки маршрута (${draft.stops.length} из минимум 2) или выберите помещения справа · Esc — отмена`
    : draft?.what === 'zone'
      ? `Обведите зону: щёлкайте углы (${draft.pts.length}); замкнуть — щелчок по первой точке или Enter · Esc — отмена`
      : draft?.what === 'cable'
        ? `Трасса: щёлкайте точки (${draft.pts.length}, ${polyLength(draft.pts).toFixed(1)} м); закончить — повторный щелчок или Enter · Esc — отмена`
        : adding ? 'Щёлкните на плане следующую остановку · Esc — закончить' : null)

  return { draft, setDraft, adding, setAdding, busy, err, hint, picking, saveRoute, update, remove, addStop, finish, cancel, startRoute, startZone, startCable }
}

export type ShapeEditor = ReturnType<typeof useShapeEditor>
