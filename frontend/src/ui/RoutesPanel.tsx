import { useEffect, useMemo, useRef, useState } from 'react'
import type { FloorMeta, Layer, RowOp, ShapeObject, V3, XY } from '../api'
import { fmtTime, type Computed, type Conflict, type RouteProps, type RouteStop, type Rules, type ZoneProps } from '../viewer/routing'
import { plural } from './format'
import { Icon } from './icons'

/** A click on the plan while the panel waits for one. */
export interface PlanClick { floor: string; at: XY; room: { id?: number; name: string } | null }

interface Props {
  build: number
  floors: FloorMeta[]
  activeFloor: FloorMeta | null
  layers: Layer[]
  rules: Rules
  /** routes and zones of the drawing (only of visible layers) */
  shapes: ShapeObject[]
  conflicts: Conflict[]
  editable: boolean
  selected: string | null
  onSelect: (id: string | null) => void
  /** the outline or stops being picked, drawn by the viewer */
  onDraft: (d: { floor: string; pts: XY[]; closed: boolean } | null) => void
  /** the panel's handler of plan clicks (set while it waits for one) */
  pickRef: React.MutableRefObject<((c: PlanClick) => void) | null>
  onPicking: (on: boolean) => void
  save: (ops: RowOp[]) => Promise<boolean>
  compute: (stops: RouteStop[]) => Promise<Computed>
  createLayer: (kind: 'routes' | 'zones') => Promise<void>
  flyTo: (floor: string, at: XY) => void
  /** glTF -> plan coordinates (room label positions) */
  planOf: (v: V3) => XY
  onClose: () => void
}

const newId = () => Math.random().toString(36).slice(2, 10)
const floorName = (floors: FloorMeta[], id: string) => floors.find((f) => f.id === id)?.name ?? '?'

function area(pts: XY[]) {
  let a = 0
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) a += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1])
  return Math.abs(a / 2)
}

/** Functional layers: routes of people through rooms and floors, zones, and their checks. */
export default function RoutesPanel(p: Props) {
  const routeLayers = p.layers.filter((l) => l.kind === 'routes')
  const zoneLayers = p.layers.filter((l) => l.kind === 'zones')
  const routes = p.shapes.filter((s) => s.geom === 'route')
  const zones = p.shapes.filter((s) => s.geom === 'polygon' && zoneLayers.some((l) => l.id === s.layer))
  const [routeLayer, setRouteLayer] = useState<string>('')
  const [zoneLayer, setZoneLayer] = useState<string>('')
  const rl = routeLayers.find((l) => l.id === routeLayer) ?? routeLayers[0]
  const zl = zoneLayers.find((l) => l.id === zoneLayer) ?? zoneLayers[0]
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // a new route: its stops so far (saved once it has two)
  const [draftRoute, setDraftRoute] = useState<{ id: string; flow: string; name: string; stops: RouteStop[] } | null>(null)
  const [adding, setAdding] = useState<string | null>(null)        // route id waiting for stops by clicks
  const [newRoute, setNewRoute] = useState<{ flow: string; name: string } | null>(null)
  const [newZone, setNewZone] = useState<{ zone: string; name: string } | null>(null)
  const [zoneDraft, setZoneDraft] = useState<{ floor: string; pts: XY[] } | null>(null)
  const recomputing = useRef(false)
  const { onDraft, onPicking, pickRef } = p

  const roomsList = useMemo(() => p.floors.flatMap((f) => f.rooms.filter((r) => r.id && (r.name || r.type))
    .map((r) => ({ f, r }))), [p.floors])

  // ---- saving
  const run = async (what: string, ops: RowOp[]) => {
    setBusy(what)
    setErr(null)
    const ok = await p.save(ops)
    setBusy(null)
    return ok
  }
  const routeProps = (s: ShapeObject) => (s.props ?? {}) as unknown as RouteProps
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
      : { op: 'create', id, geom: 'route', layer: rl?.id, props: clean }
    return run('Сохранение…', [op])
  }

  // recompute routes made on another build (the plan changed), when allowed to
  useEffect(() => {
    if (!p.editable || recomputing.current) return
    const stale = routes.filter((r) => { const x = routeProps(r); return x.stops?.length >= 2 && (x.build !== p.build || !x.path) })
    if (!stale.length) return
    recomputing.current = true
    ;(async () => {
      for (const r of stale) await saveRoute(r.id, routeProps(r), r)
      recomputing.current = false
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.build, p.editable, routes.length])

  // ---- clicks on the plan
  useEffect(() => {
    const waiting = !!adding || !!zoneDraft
    onPicking(waiting)
    pickRef.current = !waiting ? null : (c: PlanClick) => {
      if (zoneDraft) {
        if (zoneDraft.pts.length && c.floor !== zoneDraft.floor) return setErr('Зона обводится на одном этаже')
        const first = zoneDraft.pts[0]
        if (zoneDraft.pts.length >= 3 && Math.hypot(c.at[0] - first[0], c.at[1] - first[1]) < 0.5) return finishZone()
        setZoneDraft({ floor: c.floor, pts: [...zoneDraft.pts, c.at] })
        return
      }
      const stop: RouteStop = { floor: c.floor, at: c.at, room: c.room?.id ?? null, label: c.room?.name || '' }
      addStop(stop)
    }
    return () => { pickRef.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adding, zoneDraft, draftRoute, routes])
  useEffect(() => { onDraft(zoneDraft ? { ...zoneDraft, closed: false } : null) }, [zoneDraft, onDraft])
  useEffect(() => () => { onPicking(false); onDraft(null) }, [onPicking, onDraft])

  const addStop = async (st: RouteStop) => {
    if (!adding) return
    if (draftRoute && draftRoute.id === adding) {
      const stops = [...draftRoute.stops, st]
      if (stops.length < 2) return setDraftRoute({ ...draftRoute, stops })
      setDraftRoute(null)
      if (await saveRoute(adding, { flow: draftRoute.flow, name: draftRoute.name, stops }, null)) p.onSelect(adding)
      return
    }
    const r = routes.find((x) => x.id === adding)
    if (r) await saveRoute(r.id, { ...routeProps(r), stops: [...routeProps(r).stops, st] }, r)
  }
  const finishZone = async () => {
    if (!zoneDraft || zoneDraft.pts.length < 3 || !newZone) return
    const id = newId()
    const ok = await run('Сохранение…', [{ op: 'create', id, geom: 'polygon', layer: zl?.id, floor: zoneDraft.floor,
      points: zoneDraft.pts, props: { zone: newZone.zone, name: newZone.name.trim() } }])
    setZoneDraft(null)
    setNewZone(null)
    if (ok) p.onSelect(id)
  }
  // Esc / Enter while picking
  useEffect(() => {
    if (!adding && !zoneDraft) return
    const on = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setAdding(null); setDraftRoute(null); setZoneDraft(null); setNewZone(null) }
      if (e.key === 'Enter' && zoneDraft) finishZone()
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  })

  const flowOpts = Object.entries(p.rules.flows)
  const zoneOpts = Object.entries(p.rules.zone_kinds)
  const conflictsOf = (id: string) => p.conflicts.filter((c) => c.a === id || c.b === id)

  return (
    <aside className="furniture-panel routes-panel menu-root">
      <header>
        <div><b>Маршруты и зоны</b><small>{routes.length} {plural(routes.length, 'маршрут', 'маршрута', 'маршрутов')} · {zones.length} {plural(zones.length, 'зона', 'зоны', 'зон')}</small></div>
        <div className="fp-head-actions">
          <button className="icon" onClick={p.onClose} aria-label="Закрыть"><Icon name="close" size={16} /></button>
        </div>
      </header>
      <div className="rp-body">
        {busy && <p className="fp-banner">{busy}</p>}
        {err && <p className="fp-banner err">{err}</p>}
        {(adding || zoneDraft) && (
          <p className="fp-banner pick">
            {zoneDraft ? `Обведите зону: щёлкайте углы на плане (${zoneDraft.pts.length}); замкнуть — щелчок по первой точке или Enter · Esc — отмена`
              : 'Щёлкните на плане точку остановки (можно на другом этаже) или выберите помещение ниже · Esc — закончить'}
            {zoneDraft && zoneDraft.pts.length >= 3 && <button className="small primary" onClick={finishZone}>Готово</button>}
            {adding && <button className="small" onClick={() => { setAdding(null); setDraftRoute(null) }}>Готово</button>}
          </p>
        )}

        {/* ---- routes */}
        <section className="rp-sec">
          <div className="rp-head">
            <b>Маршруты людей</b>
            {p.editable && rl && !newRoute && !adding && (
              <button className="small" onClick={() => setNewRoute({ flow: 'patients', name: '' })}><Icon name="plus" size={13} /> Маршрут</button>
            )}
          </div>
          {!routeLayers.length && (
            <p className="hint">Маршрут — путь человека через помещения и этажи: вход → регистратура → кабинет → выход.
              Длина и время считаются по плану, с лестницами и лифтами.
              {p.editable && <> <button className="link" onClick={() => p.createLayer('routes')}>Создать слой маршрутов</button></>}</p>
          )}
          {routeLayers.length > 1 && p.editable && (
            <label className="fp-layer">Новые маршруты — в слой
              <select value={rl?.id ?? ''} onChange={(e) => setRouteLayer(e.target.value)}>
                {routeLayers.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
          )}
          {newRoute && (
            <form className="rp-form" onSubmit={(e) => {
              e.preventDefault()
              const id = newId()
              setDraftRoute({ id, flow: newRoute.flow, name: newRoute.name.trim(), stops: [] })
              setAdding(id)
              setNewRoute(null)
            }}>
              <input autoFocus placeholder="Название (например, «Первичный приём»)" value={newRoute.name} maxLength={200}
                onChange={(e) => setNewRoute({ ...newRoute, name: e.target.value })} />
              <select value={newRoute.flow} onChange={(e) => setNewRoute({ ...newRoute, flow: e.target.value })}>
                {flowOpts.map(([k, f]) => <option key={k} value={k}>{f.name}</option>)}
              </select>
              <div className="row-actions">
                <button type="button" className="small" onClick={() => setNewRoute(null)}>Отмена</button>
                <button className="small primary">Указать остановки</button>
              </div>
            </form>
          )}
          {draftRoute && (
            <div className="rp-item on">
              <i className="dot" style={{ background: p.rules.flows[draftRoute.flow]?.color }} />
              <div className="grow"><b>{draftRoute.name || 'Новый маршрут'}</b>
                <small>остановок: {draftRoute.stops.length} — нужно хотя бы две</small></div>
            </div>
          )}
          {routes.map((r) => {
            const x = routeProps(r)
            const on = p.selected === r.id
            const cf = conflictsOf(r.id)
            return (
              <div key={r.id} className={`rp-item${on ? ' on' : ''}`}>
                <button className="rp-main" onClick={() => {
                  p.onSelect(on ? null : r.id)
                  if (!on && x.stops?.[0]) p.flyTo(x.stops[0].floor, x.stops[0].at)
                }}>
                  <i className="dot" style={{ background: p.rules.flows[x.flow]?.color ?? '#868e96' }} />
                  <span className="grow">
                    <b>{x.name || p.rules.flows[x.flow]?.name || 'Маршрут'}</b>
                    <small>{p.rules.flows[x.flow]?.name}{x.path ? ` · ${x.length?.toFixed(0)} м · ${fmtTime(x.time ?? 0)}${x.floors_changed ? ` · этажей: ${x.floors_changed}` : ''}` : ''}</small>
                    {x.problem && <small className="err">⚠ {x.problem}</small>}
                    {cf.length > 0 && <small className="warn">⚠ конфликтов: {cf.length}</small>}
                  </span>
                </button>
                {on && (
                  <RouteDetails r={r} x={x} floors={p.floors} rules={p.rules} editable={p.editable} roomsList={roomsList}
                    adding={adding === r.id} onAdd={() => setAdding(adding === r.id ? null : r.id)}
                    onChange={(props) => saveRoute(r.id, props, r)}
                    onRecompute={() => saveRoute(r.id, x, r)}
                    onDelete={() => { if (confirm(`Удалить маршрут «${x.name || 'без названия'}»?`)) run('Удаление…', [{ op: 'delete', id: r.id, version: r.version }]) }}
                    onStop={(st) => addStopDirect(r, st)} flyTo={p.flyTo} planOf={p.planOf} />
                )}
              </div>
            )
          })}
          {draftRoute && adding === draftRoute.id && (
            <RoomPicker roomsList={roomsList} planOf={p.planOf} onPick={(st) => addStop(st)} />
          )}
        </section>

        {/* ---- zones */}
        <section className="rp-sec">
          <div className="rp-head">
            <b>Зоны</b>
            {p.editable && zl && !newZone && !zoneDraft && (
              <button className="small" onClick={() => setNewZone({ zone: 'clean', name: '' })}><Icon name="plus" size={13} /> Зона</button>
            )}
          </div>
          {zoneLayers.length > 1 && p.editable && (
            <label className="fp-layer">Новые зоны — в слой
              <select value={zl?.id ?? ''} onChange={(e) => setZoneLayer(e.target.value)}>
                {zoneLayers.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
          )}
          {!zoneLayers.length && (
            <p className="hint">Зоны — области этажа: чистая, грязная, стерильная, с ограниченным доступом. Маршруты проверяются: грязный поток не должен заходить в чистую зону и т. п.
              {p.editable && <> <button className="link" onClick={() => p.createLayer('zones')}>Создать слой зон</button></>}</p>
          )}
          {newZone && !zoneDraft && (
            <form className="rp-form" onSubmit={(e) => {
              e.preventDefault()
              if (!p.activeFloor) return setErr('Выберите этаж на лестнице слева')
              setZoneDraft({ floor: p.activeFloor.id, pts: [] })
            }}>
              <input autoFocus placeholder="Название (например, «Стерилизационная»)" value={newZone.name} maxLength={200}
                onChange={(e) => setNewZone({ ...newZone, name: e.target.value })} />
              <select value={newZone.zone} onChange={(e) => setNewZone({ ...newZone, zone: e.target.value })}>
                {zoneOpts.map(([k, z]) => <option key={k} value={k}>{z.name}</option>)}
              </select>
              <div className="row-actions">
                <button type="button" className="small" onClick={() => setNewZone(null)}>Отмена</button>
                <button className="small primary">Обвести на плане</button>
              </div>
            </form>
          )}
          {zones.map((z) => {
            const x = (z.props ?? {}) as unknown as ZoneProps
            const on = p.selected === z.id
            const zk = p.rules.zone_kinds[x.zone]
            return (
              <div key={z.id} className={`rp-item${on ? ' on' : ''}`}>
                <button className="rp-main" onClick={() => { p.onSelect(on ? null : z.id); if (!on) p.flyTo(z.floor, z.at) }}>
                  <i className="dot square" style={{ background: zk?.color ?? '#868e96' }} />
                  <span className="grow">
                    <b>{x.name || zk?.name || 'Зона'}</b>
                    <small>{zk?.name} · {floorName(p.floors, z.floor)} · {area(z.points ?? []).toFixed(1)} м²</small>
                  </span>
                </button>
                {on && p.editable && (
                  <div className="rp-details">
                    <select value={x.zone} onChange={(e) => run('Сохранение…', [{ op: 'update', id: z.id, version: z.version, props: { ...x, zone: e.target.value } }])}>
                      {zoneOpts.map(([k, zz]) => <option key={k} value={k}>{zz.name}</option>)}
                    </select>
                    <button className="small danger" onClick={() => { if (confirm('Удалить зону?')) run('Удаление…', [{ op: 'delete', id: z.id, version: z.version }]) }}>Удалить</button>
                  </div>
                )}
              </div>
            )
          })}
        </section>

        {/* ---- checks */}
        {(routes.length > 0 || zones.length > 0) && (
          <section className="rp-sec">
            <div className="rp-head"><b>Проверки</b></div>
            {!p.conflicts.length && <p className="hint ok">✓ Потоки не пересекаются, запретные зоны не нарушены.</p>}
            {p.conflicts.map((c, i) => (
              <button key={i} className="rp-conflict" onClick={() => { p.onSelect(c.a); p.flyTo(c.floor, c.at) }}>
                ⚠ {c.text} <small>{floorName(p.floors, c.floor)}</small>
              </button>
            ))}
            <p className="hint">Правила: {p.rules.flow_conflicts.map(([a, b]) => `${p.rules.flows[a]?.name.toLowerCase()} × ${p.rules.flows[b]?.name.toLowerCase()}`).join('; ')}.</p>
          </section>
        )}
      </div>
    </aside>
  )

  async function addStopDirect(r: ShapeObject, st: RouteStop) {
    await saveRoute(r.id, { ...routeProps(r), stops: [...routeProps(r).stops, st] }, r)
  }
}

function RoomPicker({ roomsList, planOf, onPick }: {
  roomsList: { f: FloorMeta; r: FloorMeta['rooms'][number] }[]; planOf: (v: V3) => XY; onPick: (st: RouteStop) => void
}) {
  return (
    <label className="fp-layer">…или помещение
      <select value="" onChange={(e) => {
        const hit = roomsList.find((x) => String(x.r.id) === e.target.value)
        if (!hit) return
        onPick({ floor: hit.f.id, at: planOf(hit.r.label_pos), room: hit.r.id ?? null, label: hit.r.name || hit.r.type || 'помещение' })
      }}>
        <option value="">— выбрать —</option>
        {roomsList.map(({ f, r }) => <option key={`${f.id}-${r.id}`} value={String(r.id)}>{f.name} · {r.name || r.type} · {r.area.toFixed(0)} м²</option>)}
      </select>
    </label>
  )
}

function RouteDetails(p: {
  r: ShapeObject; x: RouteProps; floors: FloorMeta[]; rules: Rules; editable: boolean
  roomsList: { f: FloorMeta; r: FloorMeta['rooms'][number] }[]
  adding: boolean; onAdd: () => void; onChange: (props: RouteProps) => void; onRecompute: () => void; onDelete: () => void
  onStop: (st: RouteStop) => void; flyTo: (floor: string, at: XY) => void; planOf: (v: V3) => XY
}) {
  const [name, setName] = useState(p.x.name)
  const stops = p.x.stops ?? []
  const move = (i: number, d: number) => {
    const s = [...stops]
    ;[s[i], s[i + d]] = [s[i + d], s[i]]
    p.onChange({ ...p.x, stops: s })
  }
  return (
    <div className="rp-details">
      {p.editable && (
        <div className="inline">
          <input value={name} maxLength={200} placeholder="Название" onChange={(e) => setName(e.target.value)}
            onBlur={() => name !== p.x.name && p.onChange({ ...p.x, name })} />
          <select value={p.x.flow} onChange={(e) => p.onChange({ ...p.x, flow: e.target.value })}>
            {Object.entries(p.rules.flows).map(([k, f]) => <option key={k} value={k}>{f.name}</option>)}
          </select>
        </div>
      )}
      <ol className="rp-stops">
        {stops.map((st, i) => (
          <li key={i}>
            <button className="link" onClick={() => p.flyTo(st.floor, st.at)}>{st.label || `Точка ${i + 1}`}</button>
            <small>{floorName(p.floors, st.floor)}</small>
            {p.editable && (
              <span className="rp-stop-actions">
                <button className="icon" disabled={i === 0} onClick={() => move(i, -1)} title="Выше">↑</button>
                <button className="icon" disabled={i === stops.length - 1} onClick={() => move(i, 1)} title="Ниже">↓</button>
                <button className="icon" disabled={stops.length <= 2} onClick={() => p.onChange({ ...p.x, stops: stops.filter((_, k) => k !== i) })} title="Убрать">×</button>
              </span>
            )}
          </li>
        ))}
      </ol>
      {p.editable && (
        <>
          <div className="row-actions">
            <button className={`small${p.adding ? ' primary' : ''}`} onClick={p.onAdd}>{p.adding ? 'Закончить' : '+ Остановка на плане'}</button>
            <button className="small" onClick={p.onRecompute} title="Пересчитать путь по текущему плану и мебели">Пересчитать</button>
            <button className="small danger" onClick={p.onDelete}>Удалить</button>
          </div>
          <RoomPicker roomsList={p.roomsList} planOf={p.planOf} onPick={p.onStop} />
        </>
      )}
    </div>
  )
}
