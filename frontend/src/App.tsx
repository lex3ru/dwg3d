import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import {
  createLayer, downloadDrawing, listLayers, rebuildJob,
  type FloorEdits, type FloorMeta, type Job, type RoomMeta, type V3, type ViewSettings,
} from './api'
import { canEdit, READ_ONLY } from './session'
import Editor2D from './Editor2D'
import Settings from './Settings'
import CatalogEditor from './ui/CatalogEditor'
import type { SettingsPane } from './ui/Controls'
import Report from './ui/Report'
import {
  formatHash, loadPrefs, parseHash, savePrefs,
  type Display, type MeasureMode, type NavMode, type Projection, type Speeds, type Tool,
} from './state'
import { Legend, SideControls, TopRight } from './ui/Controls'
import DisplayMenu from './ui/DisplayMenu'
import FloorRail from './ui/FloorRail'
import { MenuCtx, useOutsideClose } from './ui/menuCtx'
import LayersPanel from './ui/LayersPanel'
import NavPanel from './ui/NavPanel'
import { BuildingPanel, HelpButton, HelpOverlay, RoomCard } from './ui/Panels'
import Progress from './ui/Progress'
import SiteSettings from './ui/SiteSettings'
import TopBar from './ui/TopBar'
import FurniturePanel from './ui/FurniturePanel'
import RoutesPanel from './ui/RoutesPanel'
import Compare from './ui/Compare'
import { variantGroups } from './furniture/layers'
import Toolbar from './ui/Toolbar'
import { TILE_ATTRIBUTION } from './viewer/tiles'
import { SceneCtx, entrancePose, htmlLayer } from './viewer/scene'
import Viewer, { type Cuts, type DetailInfo, type Pick, type RoomHit } from './viewer/Viewer'
import { useFurniture } from './hooks/useFurniture'
import { useJobPolling } from './hooks/useJob'
import { useLayers } from './hooks/useLayers'
import { usePins } from './hooks/usePins'
import { usePlans } from './hooks/usePlans'
import { useRoute } from './hooks/useRoute'
import { useShapes } from './hooks/useShapes'

const introKey = (id: string) => `dwg3d.intro.${id}`
const seenIntro = (id: string | null) => {
  try { return !id || !!sessionStorage.getItem(introKey(id)) } catch { return true }
}

export default function App() {
  const initial = useMemo(() => parseHash(), [])
  const [jobId, setJobId] = useState<string | null>(() => initial?.job ?? new URLSearchParams(location.search).get('job'))
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
  const [settings, setSettings] = useState<SettingsPane | null>(null)
  const [, setCatalogTick] = useState(0)
  const [editor, setEditor] = useState(false)
  const [selRoom, setSelRoom] = useState<RoomHit | null>(null)
  const [cuts, setCuts] = useState<Cuts>({ h: { on: false, y: 0 }, v: { on: false, x: 0 } })
  const [view, setView] = useState<ViewSettings>({})
  const [preview, setPreview] = useState<ViewSettings | null>(null)
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

  // ---- state of the pieces of the viewer: each hook owns one kind of work
  const rebuilding = job?.status === 'queued' || job?.status === 'running'
  const reload = useCallback(() => setPollNonce((n) => n + 1), [])      // re-read the job: the server's state wins
  const projectId = shown?.project_id ?? job?.project_id ?? ''
  const { cx, cy, toPlan, planToGltf, loadPlan, loadGrid, clearCaches } = usePlans(shown, view)
  const {
    layers, setLayers, kinds, rules, hiddenNow, activeLayer, setActiveLayer, showVariant, toggleLayer, setAllLayers,
    layerFor, refuseLocked, syncLayers, patchLayer,
  } = useLayers(shown, projectId)
  const [comparing, setComparing] = useState(false)
  const [layersOpen, setLayersOpen] = useState(false)
  const { route, routeView, setRouteEnd, routeRoom, clearRoute } = useRoute({ setFloor, loadGrid, toPlan, planToGltf })
  const { openPin, setOpenPin, pending, setPending, pendingText, setPendingText, commitPending, deletePin, startPin } = usePins({
    shown, view, setView, rebuilding, reload, onDone: () => setTool('none'),
  })
  const {
    shapes, shapeSel, setShapeSel, shapeDraft, setShapeDraft, shapePicking, setShapePicking, shapePick,
    conflicts, shapeViews, saveShapes, computeStops, flyToPlan,
  } = useShapes({ shown, view, setView, layers, rules, hiddenNow, syncLayers, rebuilding, reload, floors, loadGrid, ctx, cx, cy, setFloor, tool })
  const furn = useFurniture({
    shown, view, setView, rebuilding, reload, hiddenNow, layerFor, refuseLocked, syncLayers, tool, setTool, floor, activeFloor,
    camViews: display.camViews, loadPlan,
  })
  const {
    furniture, shownFurniture, furnFloor, floorItems, furnPlan, issues, allCoverage, roomCover, furnSel, setFurnSel, placing, setPlacing,
    showZones, setShowZones, unplaced, resolveUnplaced, undoFurniture, updateItem, rotateItem, placeItem, duplicateItem, rowItems,
    deleteItem, moveItem, resetSaved, reset: resetFurn,
  } = furn

  // job settings stored on the server
  const adoptView = useCallback((v: ViewSettings) => {
    resetSaved(v)
    setView(v)
  }, [resetSaved])
  useEffect(() => { adoptView(shown?.view ?? {}) }, [shown?.id, shown?.view, adoptView])

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
    clearRoute()
    setNav('orbit')
    setTool('none')
    setDetailInfo(null)
    clearCaches()
    resetFurn()
    setIntro(!seenIntro(id))
  }, [clearCaches, clearRoute, resetFurn])
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

  const openShapes = () => {
    if (tool === 'shapes') { setTool('none'); return }
    if (nav === 'walk') exitWalk()
    else if (nav === 'fly') setNav('orbit')
    if (!floor) setFloor(entranceFloor?.id ?? null)
    setSelRoom(null)
    setBuildingOpen(false)
    setTool('shapes')
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

  // ---- clicks in the scene
  const onPick = (pk: Pick) => {
    const f = floors.find((x) => x.id === pk.floor)
    if (tool === 'route') {
      if (!f) return
      const end = route.step === 'to' ? 'to' : 'from'
      setRouteEnd(end, f, toPlan(pk.local), pk.room?.room.name || (end === 'from' ? 'точка A' : 'точка B'))
    } else if (tool === 'shapes') {
      if (!pk.floor || !shapePick.current) return
      const rm = pk.room?.room
      shapePick.current({ floor: pk.floor, at: toPlan(pk.local), room: rm ? { id: rm.id, name: rm.name || '' } : null })
    } else if (tool === 'marker' || tool === 'comment') {
      startPin(tool === 'marker' ? 'markers' : 'comments', pk.local.toArray() as V3, pk.floor ?? '')
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
  const saveDrawing = async (fmt: 'dxf' | 'dwg', withLayers: boolean) => {
    if (!job) return
    setSaving(fmt)
    setSaveErr(null)
    const shownLayers = layers.filter((l) => !hiddenNow.has(l.id)).map((l) => l.id)
    try { await downloadDrawing(job.id, fmt, withLayers ? shownLayers : 'none') } catch (e) { setSaveErr((e as Error).message) } finally { setSaving(null) }
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

  if (!jobId) return null

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
                  items: shownFurniture, editing: tool === 'furniture', active: furnFloor?.id ?? null, plan: furnPlan, issues,
                  selected: furnSel, placing, showZones, coverage: allCoverage, showViews: display.camViews, onSelect: (id) => { setFurnSel(id); setPlacing(null) },
                  onPlace: (pose) => { if (placing) placeItem(placing.item, pose); setPlacing(null) },
                  onPlacing: setPlacing, onMove: moveItem,
                }}
                shapes={{ items: shapeViews, selected: shapeSel, draft: shapeDraft, alerts: conflicts }} />
            </Suspense>
          ) : running ? (
            <div className="center-msg"><Progress job={job!} /></div>
          ) : null}
          <div className="html-layer" ref={(el) => { htmlLayer.current = el }} />
        </main>

        {r && (
          <>
            <HelpButton onClick={() => setHelp(true)} />
            <TopBar jobId={jobId} projectId={shown?.project_id ?? job?.project_id ?? ''} name={name} result={r}
              onOpenJob={openJob} onRoom={focusRoom} />
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
              furnitureCount={detailInfo?.furniture ?? null} placedCount={furniture.length} onFurniture={openFurniture}
              shapesOpen={tool === 'shapes'} onShapes={openShapes} shapesCount={shapes.length} conflictCount={conflicts.length}
              layersOpen={layersOpen} layersShown={layers.some((l) => !hiddenNow.has(l.id))} onLayers={() => setLayersOpen((v) => !v)} />
            {layersOpen && (
              <LayersPanel layers={layers} kinds={kinds} hidden={hiddenNow} activeLayer={activeLayer} projectId={projectId}
                editable={canEdit()} onToggle={toggleLayer} onVariant={showVariant} onAll={setAllLayers} onActive={setActiveLayer}
                onLock={patchLayer} onCompare={() => setComparing(true)} onClose={() => setLayersOpen(false)} />
            )}
            <NavPanel nav={nav} speeds={speeds} onSpeeds={setSpeeds} />
            {buildingOpen && job && shown && (
              <BuildingPanel job={job} shown={shown} active={floor} running={running} editCount={editCount}
                objectCount={shownFurniture.length + shapes.length} saving={saving}
                saveErr={saveErr} onFloor={selectFloor} onEditor={() => (canEdit() ? setEditor(true) : alert(READ_ONLY))} onSave={saveDrawing}
                onClose={() => setBuildingOpen(false)} />
            )}
            {tool === 'furniture' && (
              <FurniturePanel floor={furnFloor} items={floorItems} plan={furnPlan} issues={issues} selected={furnSel}
                placing={placing?.item ?? null} showZones={showZones} canUndo={furn.canUndo}
                onZones={setShowZones} roomCover={roomCover} camViews={display.camViews} onCamViews={(v) => patchDisplay({ camViews: v })} onPick={(c, drag) => { setFurnSel(null); setPlacing({ item: c, angle: placing?.angle ?? 0, drag }) }}
                onSelect={setFurnSel} onUpdate={updateItem} onRotate={rotateItem} onDuplicate={duplicateItem} onRow={rowItems}
                onDelete={deleteItem} onUndo={undoFurniture} onClose={() => setTool('none')}
                locked={rebuilding} readOnly={!canEdit()} unplaced={unplaced} onUnplaced={resolveUnplaced}
                layers={layers} kinds={kinds} activeLayer={activeLayer} onActiveLayer={setActiveLayer} />
            )}
            {tool === 'shapes' && rules && shown && (
              <RoutesPanel build={shown.build} floors={floors} activeFloor={activeFloor} layers={layers} rules={rules}
                shapes={shapes} conflicts={conflicts} editable={canEdit() && !rebuilding} selected={shapeSel} onSelect={setShapeSel}
                onDraft={setShapeDraft} pickRef={shapePick} onPicking={setShapePicking} save={saveShapes} compute={computeStops}
                createLayer={async (kind) => {
                  try { await createLayer(projectId, kind); setLayers(await listLayers(projectId)) } catch (e) { alert((e as Error).message) }
                }}
                flyTo={flyToPlan} planOf={(v) => toPlan(v)} onClose={() => setTool('none')} />
            )}
            {selRoom && nav !== 'walk' && (
              <RoomCard room={selRoom.room} floor={selRoom.floor} result={r} beside={buildingOpen || tool === 'furniture' || tool === 'shapes'} onClose={() => setSelRoom(null)}
                onFly={() => focusRoom(selRoom.floor, selRoom.room)}
                onRoute={(end) => { setTool('route'); routeRoom(end, selRoom.floor, selRoom.room) }} />
            )}
            {tool !== 'none' && (
              <div className="tool-hint">
                {tool === 'measure' ? (measureMode === 'length' ? 'Рулетка: кликните две точки · Esc — сброс'
                  : 'Площадь: кликайте вершины · замкнуть — клик по первой точке, двойной клик или Enter · Backspace — убрать точку')
                  : tool === 'route' ? (route.step === 'to' ? 'Маршрут: щёлкните конечную точку' : 'Маршрут: щёлкните начальную точку на полу')
                  : tool === 'marker' ? 'Щёлкните место для метки'
                  : tool === 'shapes' ? (shapePicking ? 'Маршруты и зоны: щёлкайте точки на плане' : 'Маршруты и зоны: выберите действие в панели')
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
            <a className="button small" href={`#/p/${job.project_id}`}>К проекту</a></div>
        )}
        {error && <div className="error-card floating">{error}</div>}
        {help && <HelpOverlay onClose={() => setHelp(false)} />}
        {editor && job && shown && activeFloor && (
          <Editor2D key={activeFloor.id} job={job.status === 'done' ? job : { ...shown, config: job.config }}
            floor={activeFloor} busy={running} onApply={applyEdits} onClose={() => setEditor(false)} />
        )}
        {settings === 'floors' && job?.result && <Settings job={job} onRebuild={rebuild} onClose={() => setSettings(null)} />}
        {settings === 'report' && shown && <Report projectId={shown.project_id} onClose={() => setSettings(null)} />}
        {comparing && shown && (() => {
          const g = variantGroups(layers).find((x) => x.some((l) => !hiddenNow.has(l.id))) ?? variantGroups(layers)[0]
          if (!g) return null
          const b = g.find((l) => !hiddenNow.has(l.id)) ?? g[1]
          const a = g.find((l) => l.id !== b.id) ?? g[0]
          return (
            <Compare projectId={shown.project_id} layers={layers} a={a.id} b={b.id} onClose={() => setComparing(false)}
              onShow={(o) => {
                setComparing(false)
                if (o.drawing_id !== shown.id) { location.hash = `#/f/${o.drawing_id}`; return }
                showVariant(o.change === 'removed' ? a.id : b.id)
                if (o.floor) flyToPlan(o.floor, o.at)
              }} />
          )
        })()}
        {settings === 'catalog' && <CatalogEditor onClose={() => setSettings(null)} onChanged={() => setCatalogTick((n) => n + 1)} />}
        {settings === 'site' && shown && (
          <SiteSettings jobId={shown.id} view={view} detailInfo={detailInfo} onPreview={setPreview}
            onSaved={(v) => { adoptView(v); setPreview(null) }} onClose={() => { setPreview(null); setSettings(null) }} />
        )}
      </div>
    </MenuCtx.Provider>
  )
}