import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import {
  downloadDrawing, getJob, getPlan, putView, rebuildJob, uploadFile,
  type FloorEdits, type FloorMeta, type Job, type PlanData, type RoomMeta, type V3, type ViewSettings,
} from './api'
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
import Toolbar, { type RouteState } from './ui/Toolbar'
import { TILE_ATTRIBUTION } from './viewer/tiles'
import { buildGrid, findPath, type Grid } from './viewer/route'
import { SceneCtx, entrancePose, htmlLayer } from './viewer/scene'
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
  const ctx = useMemo(() => new SceneCtx(), [])
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  useEffect(() => { if (import.meta.env.DEV) (window as any).__dwg3d = ctx }, [ctx])

  const r = shown?.result
  const floors = useMemo(() => [...(r?.floors ?? [])].sort((a, b) => a.elevation! - b.elevation!), [r])
  const activeFloor = floors.find((f) => f.id === floor) ?? null
  const entranceFloor = useMemo(() => floors.find((f) => f.id === r?.entrances?.[0]?.floor)
    ?? floors.find((f) => f.elevation! >= -0.5) ?? floors[0] ?? null, [floors, r])

  // job settings stored on the server
  useEffect(() => { setView(shown?.view ?? {}) }, [shown?.id, shown?.view])
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
  const loadGrid = async (f: FloorMeta): Promise<Grid | null> => {
    if (!grids.current.has(f.id)) {
      const plan: PlanData = await getPlan(shown!.id, f.plan, shown!.build)
      grids.current.set(f.id, buildGrid(plan))
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

  // ---- markers & comments (stored on the server)
  const savePins = async (kind: 'markers' | 'comments', list: ViewSettings['markers']) => {
    if (!shown) return
    setView((v) => ({ ...v, [kind]: list }))
    try {
      setView(await putView(shown.id, { [kind]: list }))
    } catch (e) {
      alert((e as Error).message)
    }
  }
  const commitPending = () => {
    if (!pending) return
    const text = pendingText.trim()
    const list = [...(view[pending.kind] ?? []), {
      id: Math.random().toString(36).slice(2, 10), floor: pending.floor, pos: pending.pos, text,
      label: pending.kind === 'markers' ? text.slice(0, 8) : '', created: Date.now() / 1000,
    }]
    savePins(pending.kind, list)
    setPending(null)
    setPendingText('')
    setTool('none')
  }
  const deletePin = (kind: 'markers' | 'comments', id: string) => {
    savePins(kind, (view[kind] ?? []).filter((p) => p.id !== id))
    setOpenPin(null)
  }

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
                onPin={setOpenPin} onDeletePin={deletePin} onQuality={setQuality} onDetailInfo={setDetailInfo} />
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
              furnitureCount={detailInfo?.furniture ?? null} />
            <NavPanel nav={nav} speeds={speeds} onSpeeds={setSpeeds} />
            {buildingOpen && job && shown && (
              <BuildingPanel job={job} shown={shown} active={floor} running={running} editCount={editCount} saving={saving}
                saveErr={saveErr} onFloor={selectFloor} onEditor={() => setEditor(true)} onSave={saveDrawing}
                onClose={() => setBuildingOpen(false)} />
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
                  : tool === 'marker' ? 'Щёлкните место для метки' : 'Щёлкните место для комментария'}
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
            onSaved={(v) => { setView(v); setPreview(null) }} onClose={() => { setPreview(null); setSettings(null) }} />
        )}
      </div>
    </MenuCtx.Provider>
  )
}
