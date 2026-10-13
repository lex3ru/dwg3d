import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import {
  copilotStatus, createLayer, downloadDrawing, listLayers, listObjects, listPins, rebuildJob,
  type CopilotStatus, type FloorEdits, type FloorMeta, type Job, type PlacedItem, type ProposalFull, type RoomMeta, type ViewCommand, type ShapeObject, type V3, type ViewSettings, type XY,
} from './api'
import { canEdit, me, READ_ONLY } from './session'
import Editor2D from './Editor2D'
import Settings from './Settings'
import CatalogEditor from './ui/CatalogEditor'
import type { SettingsPane } from './ui/Controls'
import Copilot from './ui/Copilot'
import CopilotSettings from './ui/CopilotSettings'
import NumberAsk from './ui/NumberAsk'
import Proposals from './ui/Proposals'
import Report from './ui/Report'
import {
  formatHash, loadPrefs, parseHash, savePrefs,
  type Display, type MeasureMode, type NavMode, type Projection, type Speeds, type Tool,
} from './state'
import { Legend, SideControls, TopRight } from './ui/Controls'
import DisplayMenu from './ui/DisplayMenu'
import FloorRail from './ui/FloorRail'
import { Armchair, BookOpen, Bot, DoorOpen, FileText, ListTree, PanelLeft, Plus, Waypoints, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Tip } from '@/components/ui/tooltip'
import Dock from './dock/Dock'
import StatusBar from './dock/StatusBar'
import { useDockState } from './dock/useDockState'
import ContextBar from './ui/ContextBar'
import SceneTree, { type TreeObject } from './ui/SceneTree'
import { catalogItem } from './furniture/catalog'
import { SLAB, setCeilings } from './furniture/geom'
import { catColor } from './ui/furniture/parts'
import ModeMenu from './ui/ModeMenu'
import { currentMode, MODES, type ModeDef } from './viewmodes'
import NavPanel from './ui/NavPanel'
import { HelpButton, HelpOverlay } from './ui/Panels'
import DrawingInspector from './ui/inspector/DrawingInspector'
import RoomInspector from './ui/inspector/RoomInspector'
import Progress from './ui/Progress'
import SiteSettings from './ui/SiteSettings'
import TopBar from './ui/TopBar'
import Catalog from './ui/furniture/Catalog'
import FloorSummary from './ui/furniture/FloorSummary'
import ItemInspector from './ui/furniture/ItemInspector'
import { DraftCard, LayerShapes, OutlineInspector, RouteInspector } from './ui/shapes/ShapeInspector'
import { useShapeEditor } from './hooks/useShapeEditor'
import Compare from './ui/Compare'
import { variantGroup, variantGroups } from './furniture/layers'
import Toolbar from './ui/Toolbar'
import { TILE_ATTRIBUTION } from './viewer/tiles'
import { SceneCtx, entrancePose, htmlLayer } from './viewer/scene'
import Viewer, { type Cuts, type DetailInfo, type Pick, type RoomHit } from './viewer/Viewer'
import { MARK_COLOR } from './viewer/Furniture'
import type { RouteProps } from './viewer/routing'
import type { ShapeView } from './viewer/Shapes'
import { useFurniture } from './hooks/useFurniture'
import { useJobPolling } from './hooks/useJob'
import { useLayers } from './hooks/useLayers'
import { usePins } from './hooks/usePins'
import { useProjectEvents } from './hooks/useProjectEvents'
import { usePlans } from './hooks/usePlans'
import { useRoute } from './hooks/useRoute'
import { useShapes } from './hooks/useShapes'
import { useExpiring } from './hooks/useExpiring'
import { useUIContext } from './hooks/useUIContext'

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
  const [draftSeen, setDraftSeen] = useState<string | null>(null)      // the draft notice closed for this revision
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
  const [help, setHelp] = useState(false)
  const leftDock = useDockState('left', 280)
  const rightDock = useDockState('right', 340)
  /** the layer being edited (its tools are in the context bar), and the drawing chosen in the tree */
  const [editLayerId, setEditLayerId] = useState<string | null>(null)
  const [drawingSel, setDrawingSel] = useState(false)
  const [leftTab, setLeftTab] = useState<'tree' | 'catalog'>('tree')
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
  // the floors' ceilings, before anything is drawn: what hangs on a ceiling hangs under it (itemElev)
  useMemo(() => {
    const slab = Number((shown?.config?.building as { slab_thickness?: unknown } | undefined)?.slab_thickness ?? SLAB)
    setCeilings(r?.floors ?? [], Number.isFinite(slab) ? slab : SLAB)
  }, [r, shown?.config])
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
    layers, setLayers, kinds, rules, hiddenNow, setActiveLayer, showVariant, toggleLayer, setAllLayers,
    targetLayer, layerFor, refuseLocked, syncLayers, lockLayer, showOnlyKinds, reloadLayers,
  } = useLayers(shown, projectId)
  const [comparing, setComparing] = useState(false)
  const { route, routeView, setRouteEnd, routeRoom, clearRoute } = useRoute({ setFloor, loadGrid, toPlan, planToGltf })
  const { openPin, setOpenPin, pending, setPending, pendingText, setPendingText, commitPending, deletePin, startPin } = usePins({
    shown, view, setView, rebuilding, reload, onDone: () => setTool('none'),
  })
  const {
    shapes, shapeSel, setShapeSel, shapeDraft, setShapeDraft, setShapePicking, shapePick,
    conflicts, shapeViews, saveShapes, computeStops, flyToPlan,
  } = useShapes({ shown, view, setView, layers, rules, hiddenNow, syncLayers, rebuilding, reload, floors, loadGrid, ctx, cx, cy, setFloor, tool })
  const furn = useFurniture({
    shown, view, setView, rebuilding, reload, hiddenNow, layerFor, refuseLocked, syncLayers, tool, setTool, floor, activeFloor,
    camViews: display.camViews, loadPlan,
  })
  const {
    shownFurniture, furnFloor, floorItems, furnPlan, issues, allCoverage, roomCover, furnSel, setFurnSel, placing, setPlacing,
    showZones, setShowZones, undoFurniture, updateItem, rotateItem, placeItem, duplicateItem, rowItems,
    deleteItem, moveItem, resetSaved, reset: resetFurn, mergeRemote,
  } = furn

  // job settings stored on the server
  const adoptView = useCallback((v: ViewSettings) => {
    resetSaved(v)
    setView(v)
  }, [resetSaved])
  useEffect(() => { adoptView(shown?.view ?? {}) }, [shown?.id, shown?.view, adoptView])

  const shownRef = useRef(shown)
  const rebuildingRef = useRef(rebuilding)
  useEffect(() => { shownRef.current = shown; rebuildingRef.current = rebuilding }, [shown, rebuilding])
  // ---- changes made elsewhere (another window, the copilot): read them in, a moment after the last one
  const [notice, setNotice] = useExpiring<string | null>(null, 6000)
  const [proposalNonce, setProposalNonce] = useState(0)
  const [proposal, setProposal] = useState<ProposalFull | null>(null)
  const live = useRef({ objects: false, layers: false, drawing: false, proposals: false, count: 0, who: new Set<string>(), timer: 0 })
  const refreshObjects = async (id: string) => {
    const [objs, pins] = await Promise.all([listObjects(id), listPins(id)])
    if (shownRef.current?.id !== id || objs.build !== shownRef.current?.build) return
    mergeRemote(objs.items.filter((x): x is PlacedItem => x.geom == null || x.geom === 'point'))
    setView((v) => ({ ...v, shapes: objs.items.filter((x) => x.geom != null && x.geom !== 'point') as ShapeObject[],
      markers: pins.markers, comments: pins.comments }))
  }
  useProjectEvents(projectId, (ev) => {
    if (ev.entity === 'view') {               // the copilot shows something to this user (only their windows get it)
      if (ev.command) commandRef.current(ev.command, ev.agent ?? '')
      return
    }
    const cur = shownRef.current
    const l = live.current
    const mine = !ev.agent && ev.user_id != null && ev.user_id === me?.id      // this user, another window or this one
    const here = (ev.changes ?? []).filter((c) => (c.entity === 'object' || c.entity === 'pin') && c.drawing === cur?.id)
    if (ev.entity === 'resync' || ev.more) l.objects = l.layers = true
    if (here.length) l.objects = true
    if ((ev.changes ?? []).some((c) => c.entity === 'layer' || c.entity === 'object')) l.layers = true
    if (!mine && (ev.changes ?? []).some((c) => c.entity === 'drawing' && c.drawing === cur?.id)) l.drawing = true
    if (ev.entity === 'resync' || here.length || (ev.changes ?? []).some((c) => c.entity === 'proposal')) l.proposals = true
    if (!mine && (ev.actor || ev.agent) && (here.length || (ev.changes ?? []).some((c) => c.entity === 'layer'))) {
      l.count += here.length + (ev.more ?? 0)
      l.who.add(ev.actor || ev.agent || '')
    }
    window.clearTimeout(l.timer)
    l.timer = window.setTimeout(() => {
      const { objects, layers: lays, drawing, proposals, count, who } = l
      live.current = { objects: false, layers: false, drawing: false, proposals: false, count: 0, who: new Set(), timer: 0 }
      if (proposals) setProposalNonce((n) => n + 1)
      if (drawing) reload()
      else if (objects && cur && !rebuildingRef.current) refreshObjects(cur.id).catch(() => {})
      if (lays) reloadLayers()
      if (who.size) setNotice(`Изменения: ${[...who].join(', ')}${count ? ` · объектов: ${count}` : ''}`)
    }, 300)
  })
  // ---- for the user's copilot: what this window shows; its commands to it
  const [focus, setFocus] = useExpiring<string[]>([], 20000)
  // the built-in copilot: shown when an admin has set up its model
  const [copilot, setCopilot] = useState<CopilotStatus | null>(null)
  const [copilotOpen, setCopilotOpen] = useState(false)
  useEffect(() => {
    if (me?.guest) return
    copilotStatus().then(setCopilot).catch(() => setCopilot(null))
  }, [copilotOpen, settings])
  const commandRef = useRef<(cmd: ViewCommand, agent: string) => void>(() => {})
  const pendingCommand = useRef<{ cmd: ViewCommand; agent: string } | null>(null)
  const uiState = useUIContext(projectId, {
    drawing: shown?.id ?? null, floor, view: proj, selected: [furnSel, shapeSel].filter((x): x is string => !!x),
    room: selRoom?.room.id ?? null, proposal: proposal?.id ?? null, tool,
  })
  // a command for another drawing waits until it opens
  useEffect(() => {
    const p = pendingCommand.current
    if (p && shown?.id === p.cmd.drawing && r) { pendingCommand.current = null; commandRef.current(p.cmd, p.agent) }
  }, [shown?.id, r])

  // a proposal being looked at: the scene shows its result, its items outlined
  const proposalView = useMemo(() => {
    if (!proposal || proposal.drawing_id !== shown?.id) {
      if (!focus.length) return null
      return { items: shownFurniture, marks: new Map(focus.map((id) => [id, 'focus' as const])) }
    }
    const point = (r: { geom?: string }) => r.geom == null || r.geom === 'point'
    const items = new Map(shownFurniture.map((it) => [it.id, it]))
    const marks = new Map<string, 'new' | 'changed' | 'removed' | 'focus'>()
    for (const r of proposal.preview.created) if (point(r)) { items.set(r.id, r as PlacedItem); marks.set(r.id, 'new') }
    for (const u of proposal.preview.updated) if (point(u.after)) { items.set(u.after.id, u.after as PlacedItem); marks.set(u.after.id, 'changed') }
    for (const r of proposal.preview.deleted) if (point(r)) { if (!items.has(r.id)) items.set(r.id, r as PlacedItem); marks.set(r.id, 'removed') }
    return { items: [...items.values()], marks }
  }, [proposal, shown?.id, shownFurniture, focus])
  // ...and its routes, zones and lines over the scene's
  const previewShapes = useMemo<ShapeView[]>(() => {
    if (!proposal || proposal.drawing_id !== shown?.id) return []
    const rows: [ShapeObject, string][] = [
      ...proposal.preview.created.map((r) => [r as ShapeObject, MARK_COLOR.new] as [ShapeObject, string]),
      ...proposal.preview.updated.map((u) => [u.after as ShapeObject, MARK_COLOR.changed] as [ShapeObject, string])]
    return rows.flatMap(([x, color]): ShapeView[] => {
      if (x.geom === 'route') {
        const pr = (x.props ?? {}) as unknown as RouteProps
        return [{ id: x.id, kind: 'route', color, segments: pr.path ?? [], label: `${pr.name || 'Маршрут'} (предложение)`,
          stops: (pr.stops ?? []).map((st, i) => ({ floor: st.floor, at: st.at, label: st.label || `Остановка ${i + 1}` })) }]
      }
      if (x.geom === 'polygon' || x.geom === 'polyline') {
        return [{ id: x.id, kind: x.geom === 'polygon' ? 'zone' : 'line', color, segments: [{ floor: x.floor, pts: x.points ?? [] }],
          label: `${(x.props?.name as string) || ''} (предложение)` }]
      }
      return []
    })
  }, [proposal, shown?.id])
  // looking at a proposal: go to the floor of its first change
  useEffect(() => {
    const first = proposal && [...proposal.preview.created, ...proposal.preview.updated.map((u) => u.after), ...proposal.preview.deleted][0]
    if (first?.floor && floors.some((f) => f.id === first.floor)) setFloor(first.floor)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposal?.id])
  useEffect(() => { setProposal(null) }, [shown?.id])

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
  commandRef.current = (cmd, agent) => {
    if (cmd.drawing && cmd.drawing !== shown?.id) {
      pendingCommand.current = { cmd, agent }
      location.hash = `#/f/${cmd.drawing}`
      return
    }
    setProposal(null)
    if (cmd.view) switchProj(cmd.view)
    if (cmd.floor && floors.some((f) => f.id === cmd.floor)) setFloor(cmd.floor)
    if (cmd.floor && cmd.at) flyToPlan(cmd.floor, cmd.at, 12)
    setFocus(cmd.highlight ?? [])
    setNotice(`${agent || 'Копилот'}${cmd.label ? `: ${cmd.label}` : ' показывает'}`)
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
  /** objects of accounting on the drawing's floors (the base layers, not the items of variants): they go into the file */
  const factObjects = useMemo(() => {
    const base = new Set(layers.filter((l) => variantGroup(l) === l.id).map((l) => l.id))
    return (view.furniture ?? []).filter((it) => it.layer && base.has(it.layer)).length
  }, [layers, view.furniture])
  const saveDrawing = async (fmt: 'dxf' | 'dwg', withObjects: boolean) => {
    if (!job) return
    setSaving(fmt)
    setSaveErr(null)
    try { await downloadDrawing(job.id, fmt, withObjects) } catch (e) {
      setSaveErr((e as Error).message)
      if (!drawingSel) alert(`Чертёж не сохранён: ${(e as Error).message}`)        // from the tree: the inspector is not open
    } finally { setSaving(null) }
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

  const running = !!job && (job.status === 'queued' || job.status === 'running')

  // ---- editing a layer: its kind picks the tool (catalog items or lines and zones)
  const editLayer = layers.find((l) => l.id === editLayerId) ?? null
  const editLayerTo = (id: string | null) => {
    if (!id) { setEditLayerId(null); setTool('none'); return }
    const l = layers.find((x) => x.id === id)
    if (!l) return
    if (!canEdit()) { alert(READ_ONLY); return }
    if (l.locked) { alert(`Слой «${l.name}» заблокирован: снимите замок в дереве слева`); return }
    if (rebuilding) { alert('Идёт перестроение модели: слои можно менять после него'); return }
    if (nav === 'walk') exitWalk()
    else if (nav === 'fly') setNav('orbit')
    if (!floor) setFloor(entranceFloor?.id ?? null)
    setSelRoom(null)
    setDrawingSel(false)
    setActiveLayer(l.id)
    setEditLayerId(l.id)
    setTool(kinds.find((k) => k.kind === l.kind)?.geoms.includes('point') ? 'furniture' : 'shapes')
  }
  // leaving the layer's tool (Esc, another tool) ends the editing
  useEffect(() => {
    if (tool !== 'furniture' && tool !== 'shapes') setEditLayerId(null)
  }, [tool])
  const addLayer = async (kind: string) => {
    try {
      const l = await createLayer(projectId, kind as Parameters<typeof createLayer>[1])
      setLayers(await listLayers(projectId))
      setNewLayer(l.id)
    } catch (e) { alert((e as Error).message) }
  }
  // a layer just created is edited as soon as the list has it
  const [newLayer, setNewLayer] = useState<string | null>(null)
  useEffect(() => {
    if (!newLayer || !layers.some((l) => l.id === newLayer)) return
    setNewLayer(null)
    editLayerTo(newLayer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newLayer, layers])

  const shapeEd = useShapeEditor({
    active: tool === 'shapes', layer: editLayer, rules, routes: (view.shapes ?? []).filter((x) => x.geom === 'route'),
    activeFloor, build: shown?.build ?? 0, editable: canEdit() && !rebuilding, save: saveShapes, compute: computeStops,
    onSelect: setShapeSel, onDraft: setShapeDraft, pickRef: shapePick, onPicking: setShapePicking,
  })
  const selectShape = (x: ShapeObject) => {
    setShapeSel(x.id)
    const first = x.geom === 'route' ? ((x.props ?? {}) as { stops?: { floor: string; at: XY }[] }).stops?.[0] : null
    if (first) flyToPlan(first.floor, first.at)
    else flyToPlan(x.floor, x.at)
  }
  const shapeActions = tool !== 'shapes' || !editLayer || shapeEd.draft ? null
    : editLayer.kind === 'routes' ? <Button size="sm" variant="outline" hintSide="bottom" onClick={shapeEd.startRoute}
      hint="Путь людей по остановкам: щелчки на плане или помещения справа, не меньше двух; Esc — отмена"><Plus /> Новый маршрут</Button>
    : editLayer.kind === 'zones' ? <Button size="sm" variant="outline" hintSide="bottom" onClick={shapeEd.startZone}
      hint="Область на выбранном этаже по углам; Enter или щелчок по первой точке замыкает, Esc — отмена"><Plus /> Обвести зону</Button>
    : <Button size="sm" variant="outline" hintSide="bottom" onClick={shapeEd.startCable}
      hint="Кабельная линия по точкам на выбранном этаже с подсчётом длины; Enter — закончить, Esc — отмена"><Plus /> Нарисовать трассу</Button>

  const toolHint = tool === 'measure' ? (measureMode === 'length' ? 'Кликните две точки · Esc — сброс'
    : 'Кликайте вершины · замкнуть — клик по первой точке, двойной клик или Enter · Backspace — убрать точку')
    : tool === 'route' ? (route.step === 'to' ? 'Щёлкните конечную точку' : 'Щёлкните начальную точку на полу')
    : tool === 'marker' ? 'Щёлкните место для метки · Esc — отмена'
    : tool === 'comment' ? 'Щёлкните место для комментария · Esc — отмена'
    : tool === 'shapes' ? (shapeEd.hint ?? 'Выберите объект справа или начните новый')
    : tool === 'furniture' ? (placing ? `${placing.item.name}: щёлкните на плане · R / Q / E — повернуть · Alt — без привязки к стене · Esc — отмена`
      : 'Перетащите предмет из каталога на план · R — поворот · Del — удалить · Ctrl+D — копия')
    : ''

  // ---- the docks: the project tree on the left; on the right, what is selected (or the editing layer's panel)
  const toggleLeft = leftDock.toggle, toggleRight = rightDock.toggle
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t?.tagName === 'INPUT' || t?.tagName === 'TEXTAREA' || t?.tagName === 'SELECT' || t?.isContentEditable) return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === '[') toggleLeft()
      else if (e.key === ']') toggleRight()
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [toggleLeft, toggleRight])

  const catalogOpen = tool === 'furniture'
  const openLeft = leftDock.setOpen
  useEffect(() => {
    setLeftTab(catalogOpen ? 'catalog' : 'tree')
    if (catalogOpen) openLeft(true)
  }, [catalogOpen, openLeft])
  const editKind = editLayer ? kinds.find((k) => k.kind === editLayer.kind) : null
  // the objects of each layer for the tree: placed items and routes, zones, lines
  const treeObjects = useMemo(() => {
    const m = new Map<string, TreeObject[]>()
    const fname = (id: string) => floors.find((f) => f.id === id)?.level ?? ''
    const add = (layer: string | undefined, o: TreeObject) => { if (layer) m.set(layer, [...(m.get(layer) ?? []), o]) }
    for (const it of view.furniture ?? []) {
      const c = catalogItem(it.item)
      add(it.layer, { id: it.id, name: c.name, sub: `эт. ${fname(it.floor)}`, color: catColor(c.cat), floor: it.floor, at: it.at, kind: 'item', layer: it.layer ?? '', room: it.room ?? null })
    }
    for (const x of view.shapes ?? []) {
      const pr = (x.props ?? {}) as { name?: string; flow?: string; zone?: string; cable?: string; stops?: { floor: string; at: XY }[] }
      const kind = x.geom === 'route' ? rules?.flows[pr.flow ?? ''] : x.geom === 'polygon' ? rules?.zone_kinds[pr.zone ?? ''] : rules?.cables[pr.cable ?? '']
      const at = pr.stops?.[0] ?? { floor: x.floor, at: x.at }
      add(x.layer, { id: x.id, name: pr.name || kind?.name || 'Объект', sub: `эт. ${fname(at.floor)}`, color: kind?.color, floor: at.floor, at: at.at, kind: 'shape', layer: x.layer ?? '', room: x.geom === 'route' ? null : x.room ?? null })
    }
    return m
  }, [view.furniture, view.shapes, floors, rules])
  const onTreeObject = (layerId: string, o: TreeObject) => {
    flyToPlan(o.floor, o.at, o.kind === 'item' ? 7 : 12)
    if (editLayerId !== layerId) return
    if (o.kind === 'item') setTimeout(() => setFurnSel(o.id), 120)      // after the floor change has reset the selection
    else setShapeSel(o.id)
  }
  const leftContent = leftTab === 'catalog' && catalogOpen ? (
    // a layer offers its own sections only: a camera or a light is placed in its system's layer, not from «Объекты учёта»
    <Catalog categories={editKind?.categories ?? null} floor={furnFloor} placing={placing?.item ?? null}
      onPick={(c, drag) => { setFurnSel(null); setPlacing({ item: c, angle: placing?.angle ?? 0, drag }) }}
      locked={rebuilding} layerOf={(c) => {
        // a variant's layer is named by its variant: «Освещение · Перестановка»
        const t = targetLayer(c), k = t && kinds.find((x) => x.kind === t.kind)
        return t && { id: t.id, name: k && k.name !== t.name ? `${k.name} · ${t.name}` : t.name }
      }}
      onGoLayer={(id) => { setPlacing(null); showVariant(id); editLayerTo(id) }} />
  ) : r ? (
    <SceneTree jobId={jobId ?? ''} projectId={projectId} result={r} active={floor} selectedRoom={selRoom?.room.node ?? null}
      drawingSelected={drawingSel} onFloor={selectFloor} onRoom={(f, rm) => { setDrawingSel(false); focusRoom(f, rm) }} onOpenJob={openJob}
      onDrawing={() => { setSelRoom(null); setDrawingSel(true) }}
      onPlan={(fid) => { setFloor(fid); if (canEdit()) setEditor(true); else alert(READ_ONLY) }}
      onExport={(fmt) => saveDrawing(fmt, factObjects > 0)} onFloorSettings={() => setSettings('floors')}
      layers={layers} kinds={kinds} hidden={hiddenNow} editLayer={editLayerId} editable={canEdit()}
      onToggle={toggleLayer} onVariant={showVariant} onAll={setAllLayers}
      onLock={(l, locked) => { if (locked && editLayerId === l.id) editLayerTo(null); lockLayer(l, locked) }} onEdit={editLayerTo}
      onAddLayer={addLayer} onCompare={() => setComparing(true)}
      objects={treeObjects} selectedObject={tool === 'furniture' ? furnSel : tool === 'shapes' ? shapeSel : null} onObject={onTreeObject} />
  ) : null

  const inspector: { key: string; title: string; icon: typeof Armchair; body: React.ReactNode } | null = !r ? null
    : tool === 'furniture' ? (() => {
      const it = floorItems.find((x) => x.id === furnSel)
      return it ? {
        key: `item:${it.id}`, title: 'Предмет', icon: Armchair, body: (
          <ItemInspector item={it} items={floorItems} plan={furnPlan} issues={issues.get(it.id) ?? []} layers={layers}
            readOnly={!canEdit() || rebuilding} onSelect={setFurnSel} onUpdate={updateItem} onRotate={rotateItem}
            onDuplicate={duplicateItem} onRow={rowItems} onDelete={deleteItem} />
        ) } : {
        key: 'furniture', title: 'Слой на этаже', icon: Armchair, body: editLayer ? (
          <FloorSummary layer={editLayer} floor={furnFloor} items={floorItems} plan={furnPlan} issues={issues} roomCover={roomCover}
            showZones={showZones} onZones={setShowZones} camViews={display.camViews} onCamViews={(v) => patchDisplay({ camViews: v })}
            onSelect={setFurnSel} />
        ) : null }
    })()
    : tool === 'shapes' && rules && shown ? (() => {
      const d = shapeEd.draft
      if (d) return { key: 'draft', title: d.what === 'route' ? 'Новый маршрут' : d.what === 'zone' ? 'Новая зона' : 'Новая трасса', icon: Waypoints,
        body: <DraftCard ed={shapeEd} draft={d} rules={rules} floors={floors} planOf={(v) => toPlan(v)} /> }
      const sel = shapes.find((x) => x.id === shapeSel)
      if (sel) return { key: `shape:${sel.id}`, title: sel.geom === 'route' ? 'Маршрут' : sel.geom === 'polygon' ? 'Зона' : 'Трасса', icon: Waypoints,
        body: sel.geom === 'route'
          ? <RouteInspector key={sel.id} ed={shapeEd} r={sel} rules={rules} floors={floors} conflicts={conflicts} editable={canEdit() && !rebuilding}
            planOf={(v) => toPlan(v)} flyTo={flyToPlan} onClose={() => setShapeSel(null)} />
          : <OutlineInspector key={sel.id} ed={shapeEd} s={sel} rules={rules} floors={floors} editable={canEdit() && !rebuilding} onClose={() => setShapeSel(null)} /> }
      return editLayer ? { key: 'shapes', title: 'Слой', icon: Waypoints,
        body: <LayerShapes ed={shapeEd} layer={editLayer} shapes={shapes} rules={rules} floors={floors} conflicts={conflicts}
          editable={canEdit() && !rebuilding} onSelect={selectShape} /> } : null
    })()
    : selRoom && nav !== 'walk' ? {
      key: `room:${selRoom.room.node}`, title: 'Помещение', icon: DoorOpen, body: (
        <RoomInspector room={selRoom.room} floor={selRoom.floor} result={r} layers={layers}
          objects={[...treeObjects].filter(([l]) => !hiddenNow.has(l)).flatMap(([, list]) => list)
            .filter((o) => o.floor === selRoom.floor.id && o.room != null && o.room === selRoom.room.id)}
          onClose={() => setSelRoom(null)} onFly={() => focusRoom(selRoom.floor, selRoom.room)}
          onRoute={(end) => { setTool('route'); routeRoom(end, selRoom.floor, selRoom.room) }}
          onObject={(o) => onTreeObject(o.layer, o)} />
      ) }
    : drawingSel && job && shown ? {
      key: 'drawing', title: 'Чертёж', icon: FileText, body: (
        <DrawingInspector job={job} shown={shown} active={floor} running={running} editCount={editCount}
          objectCount={factObjects} saving={saving} saveErr={saveErr} editable={canEdit()}
          onFloor={selectFloor} onEditor={() => (canEdit() ? setEditor(true) : alert(READ_ONLY))} onSave={saveDrawing}
          onClose={() => setDrawingSel(false)} />
      ) }
    : null
  // a new thing to show opens the right dock
  const inspectorKey = inspector?.key ?? null
  const openRight = rightDock.setOpen
  useEffect(() => { if (inspectorKey) openRight(true) }, [inspectorKey, openRight])

  // ---- view modes: presets of the display and of the layers; "client" also hides the panels
  const mode = currentMode(display, layers, hiddenNow)
  const [presenting, setPresenting] = useState(() => !!me?.guest)
  const applyMode = (m: ModeDef) => {
    patchDisplay(m.patch)
    if (m.kinds) showOnlyKinds(m.kinds)
    setPresenting(!!m.presentation)
  }
  const applyModeRef = useRef(applyMode)
  applyModeRef.current = applyMode
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t?.tagName === 'INPUT' || t?.tagName === 'TEXTAREA' || t?.tagName === 'SELECT' || t?.isContentEditable) return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const m = MODES.find((x) => x.key === e.key)
      if (m) applyModeRef.current(m)
      else if (e.key === 'Escape') setPresenting(false)
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])

  if (!jobId) return null

  const name = shownView.name || (job?.filename ?? '').replace(/\.(dwg|dxf)$/i, '')

  return (
    <>
      <div className="relative flex h-full flex-col overflow-hidden bg-background text-foreground">
        <div className="flex min-h-0 flex-1">
        {r && !presenting && (
          <Dock side="left" label="Проект" state={leftDock} tab={catalogOpen ? leftTab : 'tree'} onTab={(t) => setLeftTab(t as 'tree' | 'catalog')}
            tabs={[{ id: 'tree', label: 'Здание', icon: ListTree, hint: 'Этажи, помещения и слои объектов: видимость и редактирование' },
              ...(catalogOpen ? [{ id: 'catalog', label: 'Каталог', icon: BookOpen, hint: 'Позиции для расстановки: перетащить на план выбранного этажа' }] : [])]}>
            {leftContent}
          </Dock>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
        {r && !presenting && nav !== 'walk' && (
          <ContextBar tool={tool} measureMode={measureMode} onTool={setToolSafe}
            onMeasure={(m) => { setMeasureMode(m); setToolSafe('measure') }} route={route} onClearRoute={clearRoute}
            editable={canEdit()} layers={layers} kinds={kinds} editLayer={editLayer} floorName={activeFloor?.name ?? null}
            onEdit={editLayerTo} canUndo={furn.canUndo} onUndo={undoFurniture} hint={toolHint} actions={shapeActions} />
        )}
        <div className="@container relative min-h-0 flex-1 overflow-hidden">
        <main className="absolute inset-0" onClick={() => {
          if (nav === 'walk' && !document.pointerLockElement) {
            // pointer lock may be refused (iframe policy, right after Esc): dragging then looks around
            try {
              const req = document.querySelector('canvas')?.requestPointerLock?.() as unknown as Promise<void> | undefined
              req?.catch?.(() => {})
            } catch { /* drag to look instead */ }
          }
        }}>
          {shown?.model_url && r ? (
            <Suspense fallback={<div className="absolute inset-0 grid place-items-center text-sm text-muted-foreground">Загрузка модели…</div>}>
              <Viewer key={shown.model_url} jobId={shown.id} url={shown.model_url} result={r} display={display}
                floor={floor} proj={proj} nav={nav} speeds={speeds} tool={tool} measureMode={measureMode} cuts={cuts}
                view={shownView} selectedRoom={selRoom?.room.node ?? null} route={routeView} openPin={openPin}
                walkStart={walkStart} intro={intro} ctx={ctx} onIntroDone={introDone}
                onRoomClick={onRoomClick} onPick={onPick} onExitWalk={exitWalk} onWalkFloor={onWalkFloor}
                onPin={setOpenPin} onDeletePin={deletePin} onQuality={setQuality} onDetailInfo={setDetailInfo}
                furniture={{
                  items: proposalView?.items ?? shownFurniture, marks: proposalView?.marks,
                  editing: tool === 'furniture' && !(proposal && proposal.drawing_id === shown?.id), active: furnFloor?.id ?? null, plan: furnPlan, issues,
                  selected: furnSel, placing, showZones, coverage: allCoverage, showViews: display.camViews, onSelect: (id) => { setFurnSel(id); setPlacing(null) },
                  onPlace: (pose) => { if (placing) placeItem(placing.item, pose); setPlacing(null) },
                  onPlacing: setPlacing, onMove: moveItem,
                }}
                shapes={{ items: previewShapes.length ? [...shapeViews.filter((v) => !previewShapes.some((x) => x.id === v.id)), ...previewShapes] : shapeViews,
                  selected: shapeSel, draft: shapeDraft, alerts: conflicts }} />
            </Suspense>
          ) : running ? (
            <div className="absolute inset-0 grid place-items-center p-4"><Progress job={job!} /></div>
          ) : null}
          <div className="pointer-events-none absolute inset-0 z-[1] overflow-hidden" ref={(el) => { htmlLayer.current = el }} />
        </main>

        {r && (
          <>
            <HelpButton onClick={() => setHelp(true)} />
            {presenting && (
              <Button variant="secondary" size="sm" className="absolute top-14 left-3.5 z-20 rounded-full border-0 bg-float shadow-md" onClick={() => setPresenting(false)}
                hint="Вернуть дерево здания, инструменты и инспектор, скрытые для показа; Esc" hintSide="right"><PanelLeft /> Панели</Button>
            )}
            {presenting && nav !== 'walk' && <TopBar jobId={jobId} projectId={shown?.project_id ?? job?.project_id ?? ''} name={name} result={r}
              onOpenJob={openJob} onRoom={focusRoom} />}
            {running && shown && <Progress job={job!} className="absolute top-16 left-1/2 z-15 w-[min(420px,calc(100%-2rem))] -translate-x-1/2" />}
            <TopRight
              displayMenu={<><ModeMenu mode={mode} onMode={applyMode} /><DisplayMenu display={display} set={patchDisplay} resolvedQuality={quality} cuts={cuts} setCuts={setCuts}
                yRange={r.height_range} xRange={r.extent?.x ?? [-60, 60]} floorCut={floorCut} /></>}
              proj={proj} onProj={switchProj}
              map={display.map && !!shownView.site} mapAvailable={!!shownView.site}
              onMap={(v) => (shownView.site ? patchDisplay({ map: v }) : setSettings('site'))}
              onSettings={setSettings}
            />
            {nav !== 'walk' && <FloorRail floors={r.floors} active={floor} onSelect={selectFloor} />}
            <SideControls dayTime={display.dayTime} onDayTime={(d) => patchDisplay({ dayTime: d })}
              onZoom={(d) => ctx.api?.zoom(d)} onFit={() => ctx.api?.fit()}
              legend={<Legend result={r} on={display.roomColors} onToggleColors={(v) => patchDisplay({ roomColors: v })} />} />
            <Toolbar nav={nav} onNav={changeNav} tool={tool}
              display={display} set={patchDisplay} markers={view.markers ?? []} comments={view.comments ?? []}
              onFlyToPin={(pin) => {
                if (pin.floor) setFloor(pin.floor)
                setOpenPin(pin.id)
                setTimeout(() => ctx.api?.flyToPoint(new THREE.Vector3(...pin.pos).setY(pin.pos[1] + (ctx.offset.get(pin.floor) ?? 0)), 10), 60)
              }} />
            {!presenting && <NavPanel nav={nav} speeds={speeds} onSpeeds={setSpeeds} />}
            {tool !== 'none' && presenting && (
              <div className="absolute bottom-[76px] left-1/2 z-16 flex w-max max-w-[calc(100%-2rem)] -translate-x-1/2 items-center gap-2 rounded-full bg-[#212529]/85 px-3.5 py-1.5 text-center text-[13px] text-white">
                {toolHint}
                <Tip label="Выключить инструмент и вернуться к просмотру">
                  <button className="cursor-pointer border-0 bg-transparent p-0 text-[13px] text-[#74c0fc] hover:underline" onClick={() => setTool('none')}>готово</button>
                </Tip>
              </div>
            )}
            {pending && (
              <div className="absolute top-[110px] left-1/2 z-30 grid w-[min(360px,calc(100%-2rem))] -translate-x-1/2 gap-2.5 rounded-xl border border-border bg-popover p-3 text-popover-foreground shadow-xl"
                onKeyDown={(e) => e.stopPropagation()}>
                <b className="text-sm">{pending.kind === 'markers' ? 'Новая метка' : 'Новый комментарий'}</b>
                <Textarea autoFocus value={pendingText} rows={pending.kind === 'markers' ? 1 : 3}
                  placeholder={pending.kind === 'markers' ? 'Подпись (например, «Вход B»)' : 'Текст комментария'}
                  onChange={(e) => setPendingText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commitPending() } }} />
                <div className="flex justify-end gap-2">
                  <Button variant="secondary" size="sm" hint={pending.kind === 'markers' ? 'Закрыть без сохранения: метка не появится' : 'Закрыть без сохранения: комментарий не появится'}
                    onClick={() => setPending(null)}>Отмена</Button>
                  <Button size="sm" disabled={pending.kind === 'comments' && !pendingText.trim()} onClick={commitPending}
                    hint={pending.kind === 'comments' && !pendingText.trim() ? 'Сначала напишите текст комментария'
                      : 'Сохранить на сервере: увидят все, кто открывает здание; Enter'}>Сохранить</Button>
                </div>
              </div>
            )}
            {nav === 'walk' && (
              <>
                <div className="pointer-events-none absolute top-16 left-1/2 z-16 max-w-[calc(100%-2rem)] -translate-x-1/2 rounded-full bg-[#212529]/80 px-4 py-2 text-center text-[13.5px] text-white">{walkMsg}</div>
                <div className="pointer-events-none absolute top-1/2 left-1/2 z-16 -mt-1 -ml-1 size-2 rounded-full bg-white shadow-[0_0_0_1.5px_rgba(0,0,0,.55)]" />
              </>
            )}
            {display.map && shownView.site && proj === '3d' && <div className="pointer-events-none absolute bottom-1 left-32 z-12 rounded bg-white/70 px-1.5 py-px text-[10.5px] text-[#495057] @max-3xl:bottom-16 @max-3xl:left-2.5">{shownView.site.tiles ? shownView.site.attribution || 'Источник карты не указан' : TILE_ATTRIBUTION}</div>}
          </>
        )}
        {job?.status === 'done' && job.draft && draftSeen !== job.draft.revision && (
          <div className="absolute top-[70px] left-1/2 z-30 flex w-[min(560px,calc(100%-2rem))] -translate-x-1/2 flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-warning/40 bg-card p-3 text-sm shadow-lg" data-testid="draft-notice">
            <span className="min-w-0 flex-1">
              <b>Сборка {job.draft.n} ждёт проверки</b>
              <span className="block text-muted-foreground">
                Показана опубликованная сборка {job.build}. Новая снимет помещений: {job.draft.retired}
                {job.draft.merged ? `, объединит: ${job.draft.merged}` : ''}.
              </span>
            </span>
            <Button asChild size="sm" hint="Открыть чертежи здания, где новую сборку проверяют перед публикацией">
              <a href={`#/b/${job.project_id}/drawings?review=${job.draft.revision}`}>Проверить</a></Button>
            <Button size="icon-sm" variant="ghost" aria-label="Скрыть" onClick={() => setDraftSeen(job.draft!.revision)}
              hint="Убрать уведомление до перезагрузки страницы; сборка по-прежнему ждёт проверки"><X /></Button>
          </div>
        )}
        {job?.status === 'error' && (
          <div className="absolute top-[70px] left-1/2 z-40 grid w-[min(520px,calc(100%-2rem))] -translate-x-1/2 gap-1.5 rounded-xl border border-destructive/30 bg-card p-3 text-sm shadow-lg">
            <b className="text-destructive">Ошибка обработки</b><p className="m-0 break-words text-muted-foreground">{job.error}</p>
            <Button asChild variant="outline" size="sm" className="justify-self-start" hint="Уйти на страницу здания со списком чертежей и этажей">
              <a href={`#/p/${job.project_id}`}>К зданию</a></Button></div>
        )}
        {error && <div className="absolute top-[70px] left-1/2 z-40 w-[min(520px,calc(100%-2rem))] -translate-x-1/2 rounded-xl border border-destructive/30 bg-card p-3 text-sm break-words text-destructive shadow-lg">{error}</div>}
        </div>
        </div>
        {inspector && !presenting && (
          <Dock side="right" label={inspector.title} tabs={[{ id: inspector.key, label: inspector.title, icon: inspector.icon, badge: inspector.key === 'routes' ? conflicts.length || undefined : undefined }]}
            tab={inspector.key} onTab={() => {}} state={rightDock}>
            {inspector.body}
          </Dock>
        )}
        </div>
        {r && !presenting && (
          <StatusBar floor={activeFloor?.name ?? 'Всё здание'} nav={nav} proj={proj} objects={shownFurniture.length + shapes.length}
            rooms={activeFloor ? activeFloor.stats.rooms : null} conflicts={conflicts.length}
            busy={running ? { text: 'Сборка модели', progress: job!.progress } : saving ? { text: `Готовлю ${saving.toUpperCase()}` } : null}
            error={saveErr} onConflicts={() => {
              const l = layers.find((x) => x.kind === 'routes' && !x.locked)
              if (l) editLayerTo(l.id)
            }} />
        )}
        {shown && projectId && !presenting && !me?.guest && (
          <Proposals projectId={projectId} drawingId={shown.id} nonce={proposalNonce} editable={canEdit()}
            preview={proposal} onPreview={setProposal} shifted={copilotOpen} />
        )}
        {shown && projectId && !presenting && !me?.guest && copilot?.enabled && (copilotOpen ? (
          <Copilot projectId={projectId} status={copilot} ui={uiState} editable={canEdit()} onPreview={setProposal}
            onClose={() => setCopilotOpen(false)} />
        ) : (
          <Tip label="ИИ-помощник по этому зданию: видит, что открыто, отвечает и готовит предложения изменений на проверку" side="left">
            <button type="button" onClick={() => setCopilotOpen(true)}
              className="fixed right-4 bottom-24 z-40 flex h-10 items-center gap-2 rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground shadow-lg hover:opacity-90">
              <Bot className="size-4" /> Копилот
            </button>
          </Tip>
        )
        )}
        {notice && (
          <div role="status" className="pointer-events-none fixed bottom-24 left-1/2 z-50 max-w-[calc(100vw-32px)] -translate-x-1/2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-card-foreground shadow-lg">
            {notice}
          </div>
        )}
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
        {settings === 'copilot' && <CopilotSettings onClose={() => setSettings(null)} />}
        <NumberAsk />
        {settings === 'catalog' && <CatalogEditor onClose={() => setSettings(null)} onChanged={() => setCatalogTick((n) => n + 1)} />}
        {settings === 'site' && shown && (
          <SiteSettings jobId={shown.id} view={view} detailInfo={detailInfo} onPreview={setPreview}
            onSaved={(v) => { adoptView(v); setPreview(null) }} onClose={() => { setPreview(null); setSettings(null) }} />
        )}
      </div>
    </>
  )
}