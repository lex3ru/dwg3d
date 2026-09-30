import { Suspense, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import {
  batchRows, downloadDrawing, getJob, getPlan, rebuildJob, uploadFile,
  type FloorEdits, type FloorMeta, type Job, type Pin, type PlacedItem, type PlanData, type RoomMeta,
  type RowOp, type V3, type ViewSettings,
} from './api'
import type { CatalogItem } from './furniture/catalog'
import { catalogItem } from './furniture/catalog'
import { conflictText, furnitureOps } from './furniture/sync'
import { canEdit, READ_ONLY } from './session'
import { axes, cameraCoverage, checkFloor, footprint, indexPlan, itemElev, itemSize, roomCoverage, type PlanIndex, type Pose } from './furniture/geom'
import Editor2D from './Editor2D'
import Settings from './Settings'
import {
  formatHash, loadPrefs, parseHash, savePrefs,
  type Display, type MeasureMode, type NavMode, type Projection, type Speeds, type Tool,
} from './state'
import { Legend, SideControls, TopRight } from './ui/Controls'
import DisplayMenu from './ui/DisplayMenu'
import FloorRail from './ui/FloorRail'
import { MenuCtx, useOutsideClose } from './ui/menuCtx'
import NavPanel from './ui/NavPanel'
import { BuildingPanel, HelpButton, HelpOverlay, RoomCard } from './ui/Panels'
import SiteSettings from './ui/SiteSettings'
import TopBar from './ui/TopBar'
import FurniturePanel from './ui/FurniturePanel'
import Toolbar, { type RouteState } from './ui/Toolbar'
import { TILE_ATTRIBUTION } from './viewer/tiles'
import { buildGrid, findPath, type Grid } from './viewer/route'
import { SceneCtx, entrancePose, htmlLayer } from './viewer/scene'
import type { Placing } from './viewer/Furniture'
import Viewer, { type Cuts, type DetailInfo, type Pick, type RoomHit, type RouteView } from './viewer/Viewer'

const STAGES: Record<string, string> = {
  queued: 'В очереди', start: 'Запуск', convert: 'Конвертация DWG → DXF', read: 'Чтение чертежа',
  analyze: 'Поиск этажей', geometry: 'Построение геометрии', mesh: 'Построение 3D',
  export: 'Экспорт', done: 'Готово', error: 'Ошибка',
}

function useJobPolling(jobId: string | null, nonce: number) {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!jobId) return
    let stop = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const j = await getJob(jobId)
        if (stop) return
        setJob(j)
        setError(null)
        if (j.status === 'queued' || j.status === 'running') timer = window.setTimeout(tick, 600)
      } catch (e) {
        if (!stop) {
          setError(String((e as Error).message))
          timer = window.setTimeout(tick, 2000)
        }
      }
    }
    tick()
    return () => { stop = true; window.clearTimeout(timer) }
  }, [jobId, nonce])
  return { job, setJob, error }
}

function Upload({ onJob, onCancel }: { onJob: (id: string) => void; onCancel?: () => void }) {
  const [drag, setDrag] = useState(false)
  if (!canEdit()) {
    return (
      <div className="upload-screen">
        <div className="dropzone">
          <h1>Поэтажные планы → 3D</h1>
          <p>Загружать чертежи может роль «редактор». Откройте здание по ссылке или попросите администратора дать доступ.</p>
        </div>
        {onCancel && <button className="ghost" onClick={onCancel}>← Вернуться к зданию</button>}
      </div>
    )
  }
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const send = async (f: File | undefined) => {
    if (!f) return
    setBusy(true)
    setErr(null)
    try {
      onJob((await uploadFile(f)).id)
    } catch (e) {
      setErr((e as Error).message)
      setBusy(false)
    }
  }
  return (
    <div className="upload-screen">
      <div className={`dropzone ${drag ? 'drag' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files[0]) }}
        onClick={() => input.current?.click()}>
        <div className="dz-icon">⬆</div>
        <h1>Поэтажные планы → 3D</h1>
        <p>Перетащите файл <b>.dwg</b> или <b>.dxf</b> сюда или нажмите, чтобы выбрать</p>
        <p className="hint">Стены, окна, двери, лестницы и этажи распознаются автоматически; их можно поправить после построения.</p>
        {busy && <p>Загрузка…</p>}
        {err && <p className="error">{err}</p>}
        <input ref={input} type="file" accept=".dwg,.dxf" hidden onChange={(e) => send(e.target.files?.[0])} />
      </div>
      {onCancel && <button className="ghost" onClick={onCancel}>← Вернуться к зданию</button>}
    </div>
  )
}

function Progress({ job }: { job: Job }) {
  return (
    <div className="progress-card">
      <div className="progress-title">{job.filename}</div>
      <div className="bar"><div style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
      <div className="progress-msg">
        <span>{STAGES[job.stage] ?? job.stage}</span>
        <span>{job.message && job.message !== STAGES[job.stage] ? job.message : ''}</span>
        <span>{Math.round(job.progress * 100)}%</span>
      </div>
    </div>
  )
}

const NO_ROUTE: RouteState = { floor: null, step: 'from', fromLabel: '', toLabel: '', length: null, error: null }
const introKey = (id: string) => `dwg3d.intro.${id}`
const seenIntro = (id: string | null) => {
  try { return !id || !!sessionStorage.getItem(introKey(id)) } catch { return true }
}

export default function App() {
  const initial = useMemo(() => parseHash(), [])
  const [jobId, setJobId] = useState<string | null>(() => initial?.job ?? new URLSearchParams(location.search).get('job'))
  const [uploading, setUploading] = useState(false)
  const [pollNonce, setPollNonce] = useState(0)
  const { job, setJob, error } = useJobPolling(jobId, pollNonce)
  const [shown, setShown] = useState<Job | null>(null)
  useEffect(() => { if (job?.status === 'done') setShown(job) }, [job])

  // ---- preferences (localStorage) and view state (URL hash)
  const prefs = useMemo(() => loadPrefs(), [])
  const [display, setDisplay] = useState<Display>(() => ({
    ...prefs.display,
    ...(initial?.explode != null ? { explode: initial.explode } : {}),
    ...(initial?.onlyActive != null ? { onlyActive: initial.onlyActive } : {}),
    ...(initial?.xray != null ? { xray: initial.xray } : {}),
  }))
  const [speeds, setSpeeds] = useState<Speeds>(prefs.speeds)
  useEffect(() => savePrefs(display, speeds), [display, speeds])
  const patchDisplay = useCallback((p: Partial<Display>) => setDisplay((d) => ({ ...d, ...p })), [])
  const [floor, setFloor] = useState<string | null>(initial?.floor ?? null)
  const [proj, setProj] = useState<Projection>(initial?.proj ?? '3d')
  const [nav, setNav] = useState<NavMode>('orbit')
  const [tool, setTool] = useState<Tool>('none')
  const [measureMode, setMeasureMode] = useState<MeasureMode>('length')
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  useOutsideClose(setOpenMenu)
  const [help, setHelp] = useState(false)
  const [buildingOpen, setBuildingOpen] = useState(false)
  const [settings, setSettings] = useState<'floors' | 'site' | null>(null)
  const [editor, setEditor] = useState(false)
  const [selRoom, setSelRoom] = useState<RoomHit | null>(null)
  const [cuts, setCuts] = useState<Cuts>({ h: { on: false, y: 0 }, v: { on: false, x: 0 } })
  const [view, setView] = useState<ViewSettings>({})
  const [preview, setPreview] = useState<ViewSettings | null>(null)
  const [route, setRoute] = useState<RouteState>(NO_ROUTE)
  const [routeView, setRouteView] = useState<RouteView | null>(null)
  const routeEnds = useRef<{ from: [number, number] | null; to: [number, number] | null }>({ from: null, to: null })
  const grids = useRef(new Map<string, Grid | null>())
  const [openPin, setOpenPin] = useState<string | null>(null)
  const [pending, setPending] = useState<{ kind: 'markers' | 'comments'; pos: V3; floor: string } | null>(null)
  const [pendingText, setPendingText] = useState('')
  const [walkStart, setWalkStart] = useState<{ pos: THREE.Vector3; look: THREE.Vector3 } | null>(null)
  const [walkMsg, setWalkMsg] = useState('')
  const floorBeforeWalk = useRef<string | null>(null)
  const [quality, setQuality] = useState<'high' | 'eco' | 'real'>('high')
  const [detailInfo, setDetailInfo] = useState<DetailInfo | null>(null)
  const [saving, setSaving] = useState<'dxf' | 'dwg' | null>(null)
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [intro, setIntro] = useState(() => !initial?.floor && !seenIntro(jobId))
  // furniture placement
  const [furnSel, setFurnSel] = useState<string | null>(null)
  const [placing, setPlacing] = useState<Placing | null>(null)
  const [showZones, setShowZones] = useState(false)
  const [planIdx, setPlanIdx] = useState<{ floor: string; idx: PlanIndex } | null>(null)
  const plans = useRef(new Map<string, PlanData>())
  const furnHistory = useRef<PlacedItem[][]>([])
  const dragSnap = useRef<PlacedItem[] | null>(null)
  const furnTimer = useRef<number | undefined>(undefined)
  /** Placed items as the server last confirmed them: the base of each diff and the versions to send */
  const furnSaved = useRef(new Map<string, PlacedItem>())
  /** Saves run one after another: each diff starts from what the previous one confirmed */
  const furnQueue = useRef<Promise<void>>(Promise.resolve())
  const [, setUndoTick] = useState(0)
  const ctx = useMemo(() => new SceneCtx(), [])
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  useEffect(() => { if (import.meta.env.DEV) (window as any).__dwg3d = ctx }, [ctx])

  const r = shown?.result
  const floors = useMemo(() => [...(r?.floors ?? [])].sort((a, b) => a.elevation! - b.elevation!), [r])
  const activeFloor = floors.find((f) => f.id === floor) ?? null
  const entranceFloor = useMemo(() => floors.find((f) => f.id === r?.entrances?.[0]?.floor)
    ?? floors.find((f) => f.elevation! >= -0.5) ?? floors[0] ?? null, [floors, r])

  // job settings stored on the server
  const adoptView = useCallback((v: ViewSettings) => {
    furnSaved.current = new Map((v.furniture ?? []).map((it) => [it.id, it]))
    setView(v)
  }, [])
  useEffect(() => { adoptView(shown?.view ?? {}) }, [shown?.id, shown?.view, adoptView])
  const shownView = preview ?? view

  // drop a floor id that this build does not have
  useEffect(() => {
    if (r && shown?.id === jobId && floor && !r.floors.some((f) => f.id === floor)) setFloor(null)
  }, [r, floor, shown?.id, jobId])

  // default section positions
  useEffect(() => {
    if (!r) return
    setCuts((c) => ({
      h: { ...c.h, y: c.h.y || r.height_range[1] },
      v: { ...c.v, x: c.v.x || ((r.extent?.x[0] ?? 0) + (r.extent?.x[1] ?? 0)) / 2 },
    }))
  }, [r])

  // ---- URL hash <-> state
  useEffect(() => {
    if (!jobId) return
    const h = formatHash({ job: jobId, floor, proj, explode: display.explode, onlyActive: display.onlyActive, xray: display.xray })
    if (h === location.hash) return
    const prev = parseHash()
    const push = prev != null && (prev.job !== jobId || prev.floor !== floor || prev.proj !== proj)
    history[push ? 'pushState' : 'replaceState'](null, '', location.pathname + h)
  }, [jobId, floor, proj, display.explode, display.onlyActive, display.xray])
  useEffect(() => {
    const onPop = () => {
      const hv = parseHash()
      if (!hv) return
      setJobId((cur) => {
        if (cur !== hv.job) setShown(null)
        return hv.job
      })
      setFloor(hv.floor)
      setProj(hv.proj)
      setDisplay((d) => ({ ...d, explode: !!hv.explode, onlyActive: !!hv.onlyActive, xray: !!hv.xray }))
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const openJob = useCallback((id: string) => {
    setJobId(id)
    setShown(null)
    setFloor(null)
    setSelRoom(null)
    setRoute(NO_ROUTE)
    setRouteView(null)
    setNav('orbit')
    setTool('none')
    setUploading(false)
    setDetailInfo(null)
    grids.current.clear()
    plans.current.clear()
    furnHistory.current = []
    setFurnSel(null)
    setPlacing(null)
    setPlanIdx(null)
    setIntro(!seenIntro(id))
  }, [])
  const introDone = useCallback(() => {
    try { if (jobId) sessionStorage.setItem(introKey(jobId), '1') } catch { /* private mode */ }
    setIntro(false)
  }, [jobId])

  // ---- floors, projection, navigation
  const exitWalk = useCallback(() => {
    setNav('orbit')
    setFloor(floorBeforeWalk.current)
  }, [])
  const selectFloor = (id: string | null) => {
    if (nav === 'walk') setNav('orbit')
    setFloor(id ?? (proj === '2d' ? entranceFloor?.id ?? null : null))
    setSelRoom(null)
  }
  const switchProj = (p: Projection) => {
    if (p === proj) return
    if (p === '2d') {
      if (nav !== 'orbit') setNav('orbit')
      if (!floor) setFloor(entranceFloor?.id ?? null)
    }
    setProj(p)
  }
  const startWalk = () => {
    if (!r) return
    const eye = speeds.eye
    const main = r.entrances?.find((e) => e.main) ?? r.entrances?.[0]
    floorBeforeWalk.current = floor
    setProj('3d')
    setTool('none')
    setSelRoom(null)
    if (main) {
      setWalkStart(entrancePose(main, eye))
      setWalkMsg('Вы у главного входа. Щёлкните по сцене, чтобы осматриваться мышью; WASD — идти, Esc — выйти')
    } else {
      const f = activeFloor ?? entranceFloor
      const room = f ? [...f.rooms].sort((a, b) => b.area - a.area)[0] : null
      const p = room ? new THREE.Vector3(...room.label_pos) : new THREE.Vector3()
      p.y = (f?.elevation ?? 0) + eye
      setWalkStart({ pos: p, look: p.clone().add(new THREE.Vector3(1, 0, 0)) })
      setWalkMsg('Вход не найден — вы в самом большом помещении этажа. Щёлкните по сцене, чтобы осматриваться мышью; WASD — идти, Esc — выйти')
    }
    setNav('walk')
  }
  const changeNav = (n: NavMode) => {
    if (n === nav) return
    if (n === 'walk') return startWalk()
    if (nav === 'walk') setFloor(floorBeforeWalk.current)
    if (n === 'fly') { setProj('3d'); setTool('none') }
    setNav(n)
  }
  const onWalkFloor = useCallback((id: string) => setFloor(id), [])

  // ---- rooms
  const focusRoom = (f: FloorMeta, room: RoomMeta) => {
    if (nav !== 'orbit') changeNav('orbit')
    setFloor(f.id)
    const p = new THREE.Vector3(...room.label_pos)
    setSelRoom({ room, floor: f, point: p })
    setTimeout(() => ctx.api?.flyToPoint(p.clone().setY(p.y + (ctx.offset.get(f.id) ?? 0)), Math.max(8, Math.sqrt(room.area) * 2.2)), 60)
  }

  // ---- route (one floor)
  const cx = r?.center?.[0] ?? 0, cy = r?.center?.[1] ?? 0
  const toPlan = (v: V3 | THREE.Vector3): [number, number] => {
    const [x, , z] = Array.isArray(v) ? v : [v.x, v.y, v.z]
    return [x + cx, -z + cy]
  }
  const planToGltf = (p: [number, number], elev: number): V3 => [p[0] - cx, elev + 0.06, -(p[1] - cy)]
  const loadPlan = async (f: FloorMeta): Promise<PlanData> => {
    let plan = plans.current.get(f.id)
    if (!plan) {
      plan = await getPlan(shown!.id, f.plan, shown!.build)
      plans.current.set(f.id, plan)
    }
    return plan
  }
  const loadGrid = async (f: FloorMeta): Promise<Grid | null> => {
    if (!grids.current.has(f.id)) {
      const plan = await loadPlan(f)
      // furniture standing on the floor blocks the way (wall-hung items do not)
      const extra = (view.furniture ?? []).filter((it) => it.floor === f.id && itemElev(it) < 1 && catalogItem(it.item).kind !== 'zone')
        .map((it) => { const [w, d] = itemSize(it); const q = footprint(it.at, it.angle, w, d); return [...q, q[0]] })
      grids.current.set(f.id, buildGrid(plan, extra))
    }
    return grids.current.get(f.id) ?? null
  }
  const setRouteEnd = async (end: 'from' | 'to', f: FloorMeta, p: [number, number], label: string) => {
    let ends = routeEnds.current
    let st = route
    if (st.floor && st.floor !== f.id) {
      if (end === 'to' && ends.from) {
        setRoute({ ...st, error: 'Маршрут строится в пределах одного этажа: выберите конец на этаже начала' })
        return
      }
      ends = { from: null, to: null }
      st = { ...NO_ROUTE }
    }
    ends = { ...ends, [end]: p }
    routeEnds.current = ends
    const next: RouteState = {
      ...st, floor: f.id, [end === 'from' ? 'fromLabel' : 'toLabel']: label, error: null, length: null,
      step: ends.from && ends.to ? 'done' : ends.from ? 'to' : 'from',
    }
    setRoute(next)
    setFloor(f.id)
    const elev = f.elevation!
    setRouteView({ floor: f.id, pts: [], from: ends.from ? planToGltf(ends.from, elev) : null, to: ends.to ? planToGltf(ends.to, elev) : null, length: 0 })
    if (!ends.from || !ends.to) return
    const grid = await loadGrid(f)
    const path = grid ? findPath(grid, ends.from, ends.to) : null
    if (!path) {
      setRoute({ ...next, error: 'Путь не найден: точки разделены стенами без проёмов' })
      return
    }
    setRoute({ ...next, length: path.length })
    setRouteView({
      floor: f.id, pts: path.pts.map((q) => planToGltf(q, elev)), from: planToGltf(ends.from, elev),
      to: planToGltf(ends.to, elev), length: path.length,
    })
  }
  const routeRoom = (end: 'from' | 'to', f: FloorMeta, room: RoomMeta) =>
    setRouteEnd(end, f, toPlan(room.label_pos), room.name || room.type || 'помещение')
  const clearRoute = () => {
    routeEnds.current = { from: null, to: null }
    setRoute(NO_ROUTE)
    setRouteView(null)
  }

  // ---- markers & comments (stored on the server, one row each)
  const savePin = async (kind: 'markers' | 'comments', op: RowOp, local: Pin[]) => {
    if (!shown) return
    if (!canEdit()) {
      alert(READ_ONLY)
      return
    }
    if (rebuilding) {
      alert('Идёт перестроение модели: метки и комментарии можно менять после него')
      return
    }
    setView((v) => ({ ...v, [kind]: local }))
    try {
      const res = await batchRows<Pin>(shown.id, 'pins', shown.build, [op])
      setView((v) => ({
        ...v,
        [kind]: (v[kind] ?? []).filter((p) => !res.deleted.includes(p.id))
          .map((p) => res.items.find((x) => x.id === p.id) ?? p),
      }))
    } catch (e) {
      alert(conflictText(e, (id) => (view[kind] ?? []).find((p) => p.id === id)?.text || 'Метка'))
      setPollNonce((n) => n + 1)            // reload the job: the server's view wins
    }
  }
  const commitPending = () => {
    if (!pending) return
    const text = pendingText.trim()
    const pin: Pin = {
      id: Math.random().toString(36).slice(2, 10), floor: pending.floor, pos: pending.pos, text,
      label: pending.kind === 'markers' ? text.slice(0, 8) : '', created: Date.now() / 1000,
    }
    savePin(pending.kind, { op: 'create', kind: pending.kind, ...pin }, [...(view[pending.kind] ?? []), pin])
    setPending(null)
    setPendingText('')
    setTool('none')
  }
  const deletePin = (kind: 'markers' | 'comments', id: string) => {
    const pin = (view[kind] ?? []).find((p) => p.id === id)
    if (pin) savePin(kind, { op: 'delete', id, version: pin.version }, (view[kind] ?? []).filter((p) => p.id !== id))
    setOpenPin(null)
  }

  // ---- furniture (stored on the server with the job view)
  const furniture = useMemo(() => view.furniture ?? [], [view.furniture])
  const rebuilding = job?.status === 'queued' || job?.status === 'running'
  // a new build re-keys floors on the server: local undo steps refer to the old one
  useEffect(() => {
    furnHistory.current = []
    window.clearTimeout(furnTimer.current)
  }, [shown?.build])
  const furnFloor = tool === 'furniture' ? activeFloor : null
  // the plan is also needed to draw the camera views of the active floor
  const hasCams = !!activeFloor && furniture.some((it) => it.floor === activeFloor.id && catalogItem(it.item).cam)
  const planFloor = furnFloor ?? (display.camViews && hasCams ? activeFloor : null)
  const floorItems = useMemo(() => furniture.filter((it) => it.floor === planFloor?.id), [furniture, planFloor])
  const furnPlan = planIdx && planIdx.floor === planFloor?.id ? planIdx.idx : null
  const issues = useMemo(() => (furnFloor ? checkFloor(floorItems, furnPlan) : new Map()), [floorItems, furnPlan, furnFloor])
  const coverage = useMemo(() => cameraCoverage(floorItems, furnPlan), [floorItems, furnPlan])
  // room shares are slower: let them lag behind while a camera is dragged
  const lazyCoverage = useDeferredValue(coverage)
  const roomCover = useMemo(() => (furnFloor ? roomCoverage(furnPlan, lazyCoverage) : []), [furnFloor, furnPlan, lazyCoverage])
  useEffect(() => { grids.current.clear() }, [furniture])
  useEffect(() => {
    if (!planFloor || !shown || planIdx?.floor === planFloor.id) return
    let alive = true
    loadPlan(planFloor).then((pl) => { if (alive) setPlanIdx({ floor: planFloor.id, idx: indexPlan(pl) }) }).catch(() => {})
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planFloor?.id, shown?.id, shown?.build])
  useEffect(() => { plans.current.clear(); setPlanIdx(null) }, [shown?.build])

  /** Send what changed since the server's last confirmed state (only the changed items). */
  const saveFurniture = async (id: string, build: number, list: PlacedItem[]) => {
    const ops = furnitureOps(furnSaved.current, list)
    if (!ops.length) return
    try {
      const res = await batchRows(id, 'placements', build, ops)
      for (const it of res.items) furnSaved.current.set(it.id, it)
      for (const d of res.deleted) furnSaved.current.delete(d)
    } catch (e) {
      const was = (i: string) => furnSaved.current.get(i) as unknown as Record<string, unknown> | undefined
      alert(`Расстановка не сохранена. ${conflictText(e, (i) => catalogItem(list.find((x) => x.id === i)?.item ?? furnSaved.current.get(i)?.item ?? '').name, was)}`)
      furnHistory.current = []
      window.clearTimeout(furnTimer.current)
      setPollNonce((n) => n + 1)          // reload the job: the server's state wins
    }
  }
  /** Replace the list: locally at once, on the server after a short pause. */
  const setFurniture = (list: PlacedItem[], record = true) => {
    if (!shown) return
    if (!canEdit()) {
      alert(READ_ONLY)
      return
    }
    if (rebuilding) {
      alert('Идёт перестроение модели: расстановку можно менять после него')
      return
    }
    if (record) {
      furnHistory.current = [...furnHistory.current.slice(-99), furniture]
      setUndoTick((n) => n + 1)
    }
    setView((v) => ({ ...v, furniture: list }))
    window.clearTimeout(furnTimer.current)
    const id = shown.id, build = shown.build
    furnTimer.current = window.setTimeout(() => {
      furnQueue.current = furnQueue.current.then(() => saveFurniture(id, build, list))
    }, 400)
  }
  /** Items whose floor was not found after a rebuild: put back on the current floor, or drop. */
  const unplaced = view.furniture_unplaced ?? []
  const resolveUnplaced = (ids: string[], toFloor: string | null) => {
    if (!shown) return
    const pick = unplaced.filter((u) => ids.includes(u.id))
    const ops: RowOp[] = pick.map((u) => (toFloor
      ? { op: 'update', id: u.id, version: u.version, floor: toFloor }
      : { op: 'delete', id: u.id, version: u.version }))
    const id = shown.id, build = shown.build
    furnQueue.current = furnQueue.current.then(async () => {
      try {
        const res = await batchRows(id, 'placements', build, ops)
        for (const it of res.items) furnSaved.current.set(it.id, it)
        setView((v) => ({
          ...v,
          furniture: [...(v.furniture ?? []), ...res.items],
          furniture_unplaced: (v.furniture_unplaced ?? []).filter((u) => !ids.includes(u.id)),
        }))
      } catch (e) {
        alert(conflictText(e, (i) => catalogItem(pick.find((x) => x.id === i)?.item ?? '').name))
        setPollNonce((n) => n + 1)
      }
    })
  }
  const undoFurniture = () => {
    const prev = furnHistory.current.pop()
    if (!prev) return
    setUndoTick((n) => n + 1)
    setFurniture(prev, false)
    if (furnSel && !prev.some((x) => x.id === furnSel)) setFurnSel(null)
  }
  const newId = () => Math.random().toString(36).slice(2, 10)
  const updateItem = (id: string, patch: Partial<PlacedItem>, record = true) =>
    setFurniture(furniture.map((it) => (it.id === id ? { ...it, ...patch } : it)), record)
  const rotateItem = (id: string, by: number) => {
    const it = furniture.find((x) => x.id === id)
    if (it) updateItem(id, { angle: (((it.angle + by) % 360) + 360) % 360 })
  }
  const placeItem = (c: CatalogItem, pose: Pose) => {
    if (!furnFloor) return
    const it: PlacedItem = { id: newId(), floor: furnFloor.id, item: c.id, at: pose.at, angle: pose.angle }
    setFurniture([...furniture, it])
    setFurnSel(it.id)
  }
  const duplicateItem = (id: string) => {
    const it = furniture.find((x) => x.id === id)
    if (!it) return
    const [w] = itemSize(it)
    const { u } = axes(it.angle)
    const copy = { ...it, id: newId(), at: [it.at[0] + u[0] * (w + 0.1), it.at[1] + u[1] * (w + 0.1)] as [number, number] }
    setFurniture([...furniture, copy])
    setFurnSel(copy.id)
  }
  const rowItems = (id: string, n: number, gap: number) => {
    const it = furniture.find((x) => x.id === id)
    if (!it) return
    const [w] = itemSize(it)
    const { u } = axes(it.angle)
    const add = Array.from({ length: n - 1 }, (_, k) => ({
      ...it, id: newId(), at: [it.at[0] + u[0] * (w + gap) * (k + 1), it.at[1] + u[1] * (w + gap) * (k + 1)] as [number, number],
    }))
    setFurniture([...furniture, ...add])
  }
  const deleteItem = (id: string) => {
    setFurniture(furniture.filter((x) => x.id !== id))
    if (furnSel === id) setFurnSel(null)
  }
  const moveItem = (id: string, pose: Pose, done: boolean) => {
    if (!canEdit()) return
    if (done) {
      if (dragSnap.current) {
        furnHistory.current = [...furnHistory.current.slice(-99), dragSnap.current]
        dragSnap.current = null
        setUndoTick((n) => n + 1)
      }
      setFurniture(furniture, false)
      return
    }
    dragSnap.current ??= furniture
    setView((v) => ({ ...v, furniture: (v.furniture ?? []).map((it) => (it.id === id ? { ...it, at: pose.at, angle: pose.angle } : it)) }))
  }
  const openFurniture = () => {
    if (tool === 'furniture') {
      setTool('none')
      return
    }
    if (nav === 'walk') exitWalk()
    else if (nav === 'fly') setNav('orbit')
    if (!floor) setFloor(entranceFloor?.id ?? null)
    setSelRoom(null)
    setBuildingOpen(false)
    setTool('furniture')
  }
  useEffect(() => {
    if (tool !== 'furniture') { setPlacing(null); setFurnSel(null) }
  }, [tool])
  useEffect(() => { setFurnSel(null); setPlacing(null) }, [floor])

  // keyboard while furnishing
  const keyRef = useRef<(e: KeyboardEvent) => void>(() => {})
  keyRef.current = (e: KeyboardEvent) => {
    const t = e.target as HTMLElement
    if (t?.tagName === 'INPUT' || t?.tagName === 'TEXTAREA' || t?.tagName === 'SELECT') return
    const sel = furniture.find((x) => x.id === furnSel)
    const turn = e.code === 'KeyR' ? (e.shiftKey ? -90 : 90) : e.code === 'KeyQ' ? 15 : e.code === 'KeyE' ? -15 : 0
    if ((e.ctrlKey || e.metaKey) && e.code === 'KeyZ') { e.preventDefault(); undoFurniture() }
    else if ((e.ctrlKey || e.metaKey) && e.code === 'KeyD') { e.preventDefault(); if (sel) duplicateItem(sel.id) }
    else if (e.ctrlKey || e.metaKey || e.altKey) return
    else if (e.key === 'Escape') {
      if (placing) setPlacing(null)
      else if (furnSel) setFurnSel(null)
      else setTool('none')
    } else if (turn) {
      if (placing) setPlacing({ ...placing, angle: (((placing.angle + turn) % 360) + 360) % 360 })
      else if (sel) rotateItem(sel.id, turn)
    } else if ((e.key === 'Delete' || e.key === 'Backspace') && sel) {
      e.preventDefault()
      deleteItem(sel.id)
    } else if (sel && e.key.startsWith('Arrow')) {
      e.preventDefault()
      const s = e.shiftKey ? 0.5 : 0.05
      const [dx, dy] = { ArrowLeft: [-s, 0], ArrowRight: [s, 0], ArrowUp: [0, s], ArrowDown: [0, -s] }[e.key] ?? [0, 0]
      updateItem(sel.id, { at: [Math.round((sel.at[0] + dx) * 100) / 100, Math.round((sel.at[1] + dy) * 100) / 100] })
    }
  }
  useEffect(() => {
    if (tool !== 'furniture') return
    const on = (e: KeyboardEvent) => keyRef.current(e)
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [tool])

  // ---- clicks in the scene
  const onPick = (pk: Pick) => {
    const f = floors.find((x) => x.id === pk.floor)
    if (tool === 'route') {
      if (!f) return
      const end = route.step === 'to' ? 'to' : 'from'
      setRouteEnd(end, f, toPlan(pk.local), pk.room?.room.name || (end === 'from' ? 'точка A' : 'точка B'))
    } else if (tool === 'marker' || tool === 'comment') {
      setPending({ kind: tool === 'marker' ? 'markers' : 'comments', pos: pk.local.toArray() as V3, floor: pk.floor ?? '' })
      setPendingText('')
    }
  }
  const onRoomClick = (h: RoomHit | null) => {
    setSelRoom(h)
    setOpenPin(null)
  }

  // ---- editor / rebuild / save
  const rebuild = async (override: Record<string, unknown>) => {
    setSettings(null)
    try {
      setJob(await rebuildJob(job!.id, override))
      setPollNonce((n) => n + 1)
    } catch (e) {
      alert((e as Error).message)
    }
  }
  const applyEdits = (floorId: string, edits: FloorEdits) => rebuild({ edits: { [floorId]: edits } })
  const editCount = Object.values((job?.config?.edits ?? {}) as Record<string, Record<string, unknown[]>>)
    .reduce((n, fe) => n + Object.values(fe ?? {}).reduce((k, l) => k + (Array.isArray(l) ? l.length : 0), 0), 0)
  const saveDrawing = async (fmt: 'dxf' | 'dwg') => {
    if (!job) return
    setSaving(fmt)
    setSaveErr(null)
    try { await downloadDrawing(job.id, fmt) } catch (e) { setSaveErr((e as Error).message) } finally { setSaving(null) }
  }
  const setToolSafe = (t: Tool) => {
    if ((t === 'marker' || t === 'comment') && !canEdit()) {
      alert(READ_ONLY)
      return
    }
    if (t !== 'none' && nav === 'walk') exitWalk()
    setTool(t)
  }

  const floorCut = activeFloor ? () => setCuts((c) => ({ ...c, h: { on: true, y: activeFloor.elevation! + 1.2 } })) : null

  if (!jobId || uploading) return <Upload onJob={openJob} onCancel={jobId ? () => setUploading(false) : undefined} />

  const running = !!job && (job.status === 'queued' || job.status === 'running')
  const name = shownView.name || (job?.filename ?? '').replace(/\.(dwg|dxf)$/i, '')

  return (
    <MenuCtx.Provider value={{ open: openMenu, setOpen: setOpenMenu }}>
      <div className={`app nav-${nav}`}>
        <main className="stage" onClick={() => {
          if (nav === 'walk' && !document.pointerLockElement) {
            // pointer lock may be refused (iframe policy, right after Esc): dragging then looks around
            try {
              const req = document.querySelector('canvas')?.requestPointerLock?.() as unknown as Promise<void> | undefined
              req?.catch?.(() => {})
            } catch { /* drag to look instead */ }
          }
        }}>
          {shown?.model_url && r ? (
            <Suspense fallback={<div className="center-msg">Загрузка модели…</div>}>
              <Viewer key={shown.model_url} jobId={shown.id} url={shown.model_url} result={r} display={display}
                floor={floor} proj={proj} nav={nav} speeds={speeds} tool={tool} measureMode={measureMode} cuts={cuts}
                view={shownView} selectedRoom={selRoom?.room.node ?? null} route={routeView} openPin={openPin}
                walkStart={walkStart} intro={intro} ctx={ctx} onIntroDone={introDone}
                onRoomClick={onRoomClick} onPick={onPick} onExitWalk={exitWalk} onWalkFloor={onWalkFloor}
                onPin={setOpenPin} onDeletePin={deletePin} onQuality={setQuality} onDetailInfo={setDetailInfo}
                furniture={{
                  items: furniture, editing: tool === 'furniture', active: furnFloor?.id ?? null, plan: furnPlan, issues,
                  selected: furnSel, placing, showZones, coverage, showViews: display.camViews, onSelect: (id) => { setFurnSel(id); setPlacing(null) },
                  onPlace: (pose) => { if (placing) placeItem(placing.item, pose); setPlacing(null) },
                  onPlacing: setPlacing, onMove: moveItem,
                }} />
            </Suspense>
          ) : running ? (
            <div className="center-msg"><Progress job={job!} /></div>
          ) : null}
          <div className="html-layer" ref={(el) => { htmlLayer.current = el }} />
        </main>

        {r && (
          <>
            <HelpButton onClick={() => setHelp(true)} />
            <TopBar jobId={jobId} name={name} result={r} onOpenJob={openJob} onNewFile={() => setUploading(true)}
              onRoom={focusRoom} />
            {running && shown && <div className="rebuild-progress"><Progress job={job!} /></div>}
            <TopRight
              measuring={tool === 'measure'} measureMode={measureMode}
              onMeasure={(on, mode) => {
                if (mode) setMeasureMode(mode)
                setToolSafe(on ? 'measure' : 'none')
              }}
              displayMenu={<DisplayMenu display={display} set={patchDisplay} resolvedQuality={quality} cuts={cuts} setCuts={setCuts}
                yRange={r.height_range} xRange={r.extent?.x ?? [-60, 60]} floorCut={floorCut} />}
              proj={proj} onProj={switchProj}
              map={display.map && !!shownView.site} mapAvailable={!!shownView.site}
              onMap={(v) => (shownView.site ? patchDisplay({ map: v }) : setSettings('site'))}
              onSettings={setSettings}
            />
            {nav !== 'walk' && <FloorRail floors={r.floors} active={floor} onSelect={selectFloor} />}
            <SideControls dayTime={display.dayTime} onDayTime={(d) => patchDisplay({ dayTime: d })}
              onZoom={(d) => ctx.api?.zoom(d)} onFit={() => ctx.api?.fit()}
              legend={<Legend result={r} on={display.roomColors} onToggleColors={(v) => patchDisplay({ roomColors: v })} />} />
            <Toolbar nav={nav} onNav={changeNav} tool={tool} onTool={setToolSafe}
              route={route} routeFloor={floors.find((f) => f.id === (route.floor ?? floor)) ?? entranceFloor}
              onRouteRoom={(end, node) => {
                const f = floors.find((x) => x.rooms.some((rm) => rm.node === node))
                const room = f?.rooms.find((rm) => rm.node === node)
                if (f && room) routeRoom(end, f, room)
              }}
              onClearRoute={clearRoute} buildingOpen={buildingOpen} onBuilding={() => setBuildingOpen(!buildingOpen)}
              display={display} set={patchDisplay} markers={view.markers ?? []} comments={view.comments ?? []}
              onFlyToPin={(pin) => {
                if (pin.floor) setFloor(pin.floor)
                setOpenPin(pin.id)
                setTimeout(() => ctx.api?.flyToPoint(new THREE.Vector3(...pin.pos).setY(pin.pos[1] + (ctx.offset.get(pin.floor) ?? 0)), 10), 60)
              }}
              furnitureCount={detailInfo?.furniture ?? null} placedCount={furniture.length} onFurniture={openFurniture} />
            <NavPanel nav={nav} speeds={speeds} onSpeeds={setSpeeds} />
            {buildingOpen && job && shown && (
              <BuildingPanel job={job} shown={shown} active={floor} running={running} editCount={editCount} saving={saving}
                saveErr={saveErr} onFloor={selectFloor} onEditor={() => (canEdit() ? setEditor(true) : alert(READ_ONLY))} onSave={saveDrawing}
                onClose={() => setBuildingOpen(false)} />
            )}
            {tool === 'furniture' && (
              <FurniturePanel floor={furnFloor} items={floorItems} plan={furnPlan} issues={issues} selected={furnSel}
                placing={placing?.item ?? null} showZones={showZones} canUndo={furnHistory.current.length > 0}
                onZones={setShowZones} roomCover={roomCover} camViews={display.camViews} onCamViews={(v) => patchDisplay({ camViews: v })} onPick={(c, drag) => { setFurnSel(null); setPlacing({ item: c, angle: placing?.angle ?? 0, drag }) }}
                onSelect={setFurnSel} onUpdate={updateItem} onRotate={rotateItem} onDuplicate={duplicateItem} onRow={rowItems}
                onDelete={deleteItem} onUndo={undoFurniture} onClose={() => setTool('none')}
                locked={rebuilding} readOnly={!canEdit()} unplaced={unplaced} onUnplaced={resolveUnplaced} />
            )}
            {selRoom && nav !== 'walk' && (
              <RoomCard room={selRoom.room} floor={selRoom.floor} result={r} onClose={() => setSelRoom(null)}
                onFly={() => focusRoom(selRoom.floor, selRoom.room)}
                onRoute={(end) => { setTool('route'); routeRoom(end, selRoom.floor, selRoom.room) }} />
            )}
            {tool !== 'none' && (
              <div className="tool-hint">
                {tool === 'measure' ? (measureMode === 'length' ? 'Рулетка: кликните две точки · Esc — сброс'
                  : 'Площадь: кликайте вершины · замкнуть — клик по первой точке, двойной клик или Enter · Backspace — убрать точку')
                  : tool === 'route' ? (route.step === 'to' ? 'Маршрут: щёлкните конечную точку' : 'Маршрут: щёлкните начальную точку на полу')
                  : tool === 'marker' ? 'Щёлкните место для метки'
                  : tool === 'furniture' ? (placing ? `${placing.item.name}: щёлкните на плане · R / Q / E — повернуть · Alt — без привязки к стене · Esc — отмена`
                    : 'Перетащите предмет из каталога на план · перетаскивание — двигать · R — поворот · Del — удалить · Ctrl+D — копия · Ctrl+Z — отмена')
                  : 'Щёлкните место для комментария'}
                <button className="link" onClick={() => setTool('none')}>готово</button>
              </div>
            )}
            {pending && (
              <div className="pin-editor menu-root">
                <b>{pending.kind === 'markers' ? 'Новая метка' : 'Новый комментарий'}</b>
                <textarea autoFocus value={pendingText} rows={pending.kind === 'markers' ? 1 : 3}
                  placeholder={pending.kind === 'markers' ? 'Подпись (например, «Вход B»)' : 'Текст комментария'}
                  onChange={(e) => setPendingText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commitPending() } }} />
                <div className="row">
                  <button onClick={() => setPending(null)}>Отмена</button>
                  <button className="primary" disabled={pending.kind === 'comments' && !pendingText.trim()} onClick={commitPending}>Сохранить</button>
                </div>
              </div>
            )}
            {nav === 'walk' && (
              <>
                <div className="walk-hint">{walkMsg}</div>
                <div className="crosshair-dot" />
              </>
            )}
            {display.map && shownView.site && proj === '3d' && <div className="attribution">{shownView.site.tiles ? shownView.site.attribution || 'Источник карты не указан' : TILE_ATTRIBUTION}</div>}
          </>
        )}
        {job?.status === 'error' && (
          <div className="error-card floating"><b>Ошибка обработки</b><p>{job.error}</p>
            <button className="small" onClick={() => setUploading(true)}>Загрузить другой файл</button></div>
        )}
        {error && <div className="error-card floating">{error}</div>}
        {help && <HelpOverlay onClose={() => setHelp(false)} />}
        {editor && job && shown && activeFloor && (
          <Editor2D key={activeFloor.id} job={job.status === 'done' ? job : { ...shown, config: job.config }}
            floor={activeFloor} busy={running} onApply={applyEdits} onClose={() => setEditor(false)} />
        )}
        {settings === 'floors' && job?.result && <Settings job={job} onRebuild={rebuild} onClose={() => setSettings(null)} />}
        {settings === 'site' && shown && (
          <SiteSettings jobId={shown.id} view={view} detailInfo={detailInfo} onPreview={setPreview}
            onSaved={(v) => { adoptView(v); setPreview(null) }} onClose={() => { setPreview(null); setSettings(null) }} />
        )}
      </div>
    </MenuCtx.Provider>
  )
}
