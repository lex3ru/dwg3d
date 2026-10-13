import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { batchRows, type FloorMeta, type Job, type PlacedItem, type PlanData, type ViewSettings } from '../api'
import { catalogItem, type CatalogItem } from '../furniture/catalog'
import {
  axes, cameraCoverage, checkFloor, indexPlan, itemSize, roomCoverage, systemsCoverage, type PlanIndex, type Pose,
} from '../furniture/geom'
import { conflictText, furnitureOps, sameItem } from '../furniture/sync'
import { canEdit, READ_ONLY } from '../session'
import type { Tool } from '../state'
import type { Placing } from '../viewer/Furniture'

/**
 * Placing furniture and equipment on a floor: the list (kept in the view),
 * selection, undo, saving the changed items to the server after a short pause,
 * keyboard shortcuts, and what is computed from the active floor's plan
 * (issues, camera views, Wi-Fi and detector coverage).
 */
export function useFurniture(p: {
  shown: Job | null
  view: ViewSettings
  setView: (f: (v: ViewSettings) => ViewSettings) => void
  rebuilding: boolean
  reload: () => void
  hiddenNow: Set<string>
  layerFor: (c: CatalogItem) => string | null | undefined
  refuseLocked: (it: PlacedItem | undefined) => boolean
  syncLayers: (items: { layer?: string }[]) => void
  tool: Tool
  setTool: (t: Tool) => void
  floor: string | null
  activeFloor: FloorMeta | null
  camViews: boolean
  loadPlan: (f: FloorMeta) => Promise<PlanData>
}) {
  const { shown, view, setView, rebuilding, tool, activeFloor } = p
  const [furnSel, setFurnSel] = useState<string | null>(null)
  const [placing, setPlacing] = useState<Placing | null>(null)
  const [showZones, setShowZones] = useState(false)
  const [planIdx, setPlanIdx] = useState<{ floor: string; idx: PlanIndex } | null>(null)
  const furnHistory = useRef<PlacedItem[][]>([])
  const dragSnap = useRef<PlacedItem[] | null>(null)
  const furnTimer = useRef<number | undefined>(undefined)
  /** Placed items as the server last confirmed them: the base of each diff and the versions to send */
  const furnSaved = useRef(new Map<string, PlacedItem>())
  /** Saves run one after another: each diff starts from what the previous one confirmed */
  const furnQueue = useRef<Promise<void>>(Promise.resolve())
  const [, setUndoTick] = useState(0)

  const furniture = useMemo(() => view.furniture ?? [], [view.furniture])
  /** the list as rendered last: what a merge of remote changes starts from */
  const furnNow = useRef(furniture)
  useEffect(() => { furnNow.current = furniture }, [furniture])
  const shownFurniture = useMemo(() => furniture.filter((it) => !it.layer || !p.hiddenNow.has(it.layer)), [furniture, p.hiddenNow])
  /** the view came from the server: its items are the base of the next diff */
  const resetSaved = useCallback((v: ViewSettings) => { furnSaved.current = new Map((v.furniture ?? []).map((it) => [it.id, it])) }, [])
  const reset = useCallback(() => {
    furnHistory.current = []
    setFurnSel(null)
    setPlacing(null)
    setPlanIdx(null)
  }, [])

  // a new build re-keys floors on the server: local undo steps refer to the old one
  useEffect(() => {
    furnHistory.current = []
    window.clearTimeout(furnTimer.current)
  }, [shown?.build])
  const furnFloor = tool === 'furniture' ? activeFloor : null
  // the plan is also needed to draw the camera views of the active floor
  const hasCams = !!activeFloor && shownFurniture.some((it) => { const c = catalogItem(it.item); return it.floor === activeFloor.id && (!!c.cam || !!c.params) })
  const planFloor = furnFloor ?? (p.camViews && hasCams ? activeFloor : null)
  const floorItems = useMemo(() => shownFurniture.filter((it) => it.floor === planFloor?.id), [shownFurniture, planFloor])
  const furnPlan = planIdx && planIdx.floor === planFloor?.id ? planIdx.idx : null
  const issues = useMemo(() => (furnFloor ? checkFloor(floorItems, furnPlan) : new Map()), [floorItems, furnPlan, furnFloor])
  const coverage = useMemo(() => cameraCoverage(floorItems, furnPlan), [floorItems, furnPlan])
  // Wi-Fi signal, the areas of fire detectors and of light sources, drawn like camera views
  const allCoverage = useMemo(() => new Map([...coverage, ...systemsCoverage(floorItems, furnPlan)]), [coverage, floorItems, furnPlan])
  // room shares are slower: let them lag behind while a camera is dragged
  const lazyCoverage = useDeferredValue(coverage)
  const roomCover = useMemo(() => (furnFloor ? roomCoverage(furnPlan, lazyCoverage) : []), [furnFloor, furnPlan, lazyCoverage])
  useEffect(() => {
    if (!planFloor || !shown || planIdx?.floor === planFloor.id) return
    let alive = true
    p.loadPlan(planFloor).then((pl) => { if (alive) setPlanIdx({ floor: planFloor.id, idx: indexPlan(pl) }) }).catch(() => {})
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planFloor?.id, shown?.id, shown?.build])
  useEffect(() => { setPlanIdx(null) }, [shown?.build])

  /** Send what changed since the server's last confirmed state (only the changed items). */
  const saveFurniture = async (id: string, build: number, list: PlacedItem[]) => {
    const ops = furnitureOps(furnSaved.current, list)
    if (!ops.length) return
    try {
      const res = await batchRows(id, 'objects', build, ops)
      for (const it of res.items) furnSaved.current.set(it.id, it)
      for (const d of res.deleted) furnSaved.current.delete(d)
      // the server chose the layer of items placed without one (and may have created it)
      const got = new Map(res.items.map((it) => [it.id, it.layer]))
      setView((v) => ({ ...v, furniture: (v.furniture ?? []).map((it) => (!it.layer && got.get(it.id) ? { ...it, layer: got.get(it.id) } : it)) }))
      p.syncLayers(res.items)
    } catch (e) {
      const was = (i: string) => furnSaved.current.get(i) as unknown as Record<string, unknown> | undefined
      alert(`Расстановка не сохранена. ${conflictText(e, (i) => catalogItem(list.find((x) => x.id === i)?.item ?? furnSaved.current.get(i)?.item ?? '').name, was)}`)
      furnHistory.current = []
      window.clearTimeout(furnTimer.current)
      p.reload()          // the server's state wins
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
  /** Rows changed by someone else (another window, the copilot): take the server's rows except
   * where this window has a change not saved yet (its save then meets the conflict as usual).
   * Undo steps are dropped: they could put back what the other one changed. */
  const mergeRemote = (rows: PlacedItem[]) => {
    const saved = furnSaved.current
    const local = furnNow.current
    const server = new Map(rows.map((it) => [it.id, it]))
    // a change of this window not on the server yet: a new item, a deleted one, edited fields
    const dirty = new Set([...local.map((it) => it.id), ...saved.keys()].filter((id) => {
      const l = local.find((x) => x.id === id), sv = saved.get(id)
      return sv ? !l || !sameItem(l, sv) : !!l
    }))
    const localIds = new Set(local.map((it) => it.id))
    const next = local.flatMap((l) => (dirty.has(l.id) ? [l] : server.has(l.id) ? [server.get(l.id)!] : []))
    for (const r of rows) if (!localIds.has(r.id) && !saved.has(r.id)) next.push(r)
    for (const r of rows) if (!dirty.has(r.id)) saved.set(r.id, r)
    for (const id of [...saved.keys()]) if (!server.has(id) && !dirty.has(id)) saved.delete(id)
    furnHistory.current = []
    setUndoTick((n) => n + 1)
    setView((v) => ({ ...v, furniture: next }))
    if (furnSel && !next.some((x) => x.id === furnSel)) setFurnSel(null)
  }
  const undoFurniture = () => {
    const prev = furnHistory.current.pop()
    if (!prev) return
    setUndoTick((n) => n + 1)
    setFurniture(prev, false)
    if (furnSel && !prev.some((x) => x.id === furnSel)) setFurnSel(null)
  }
  const newId = () => Math.random().toString(36).slice(2, 10)
  const updateItem = (id: string, patch: Partial<PlacedItem>, record = true) => {
    const it = furniture.find((x) => x.id === id)
    if (p.refuseLocked(it) || (patch.layer && p.refuseLocked({ ...it!, layer: patch.layer }))) return
    setFurniture(furniture.map((x) => (x.id === id ? { ...x, ...patch } : x)), record)
  }
  const rotateItem = (id: string, by: number) => {
    const it = furniture.find((x) => x.id === id)
    if (it) updateItem(id, { angle: (((it.angle + by) % 360) + 360) % 360 })
  }
  const placeItem = (c: CatalogItem, pose: Pose) => {
    if (!furnFloor) return
    const layer = p.layerFor(c)
    if (layer === null) return
    const it: PlacedItem = { id: newId(), floor: furnFloor.id, item: c.id, at: pose.at, angle: pose.angle, layer }
    if (p.refuseLocked(it)) return
    setFurniture([...furniture, it])
    setFurnSel(it.id)
  }
  const duplicateItem = (id: string) => {
    const it = furniture.find((x) => x.id === id)
    if (!it || p.refuseLocked(it)) return
    const [w] = itemSize(it)
    const { u } = axes(it.angle)
    const copy = { ...it, id: newId(), at: [it.at[0] + u[0] * (w + 0.1), it.at[1] + u[1] * (w + 0.1)] as [number, number] }
    setFurniture([...furniture, copy])
    setFurnSel(copy.id)
  }
  const rowItems = (id: string, n: number, gap: number) => {
    const it = furniture.find((x) => x.id === id)
    if (!it || p.refuseLocked(it)) return
    const [w] = itemSize(it)
    const { u } = axes(it.angle)
    const add = Array.from({ length: n - 1 }, (_, k) => ({
      ...it, id: newId(), at: [it.at[0] + u[0] * (w + gap) * (k + 1), it.at[1] + u[1] * (w + gap) * (k + 1)] as [number, number],
    }))
    setFurniture([...furniture, ...add])
  }
  const deleteItem = (id: string) => {
    if (p.refuseLocked(furniture.find((x) => x.id === id))) return
    setFurniture(furniture.filter((x) => x.id !== id))
    if (furnSel === id) setFurnSel(null)
  }
  const moveItem = (id: string, pose: Pose, done: boolean) => {
    if (!canEdit()) return
    if (!done && !dragSnap.current && p.refuseLocked(furniture.find((x) => x.id === id))) return
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
  useEffect(() => {
    if (tool !== 'furniture') { setPlacing(null); setFurnSel(null) }
  }, [tool])
  useEffect(() => { setFurnSel(null); setPlacing(null) }, [p.floor])

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
      else p.setTool('none')
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

  return {
    furniture, shownFurniture, furnFloor, floorItems, furnPlan, issues, allCoverage, roomCover,
    furnSel, setFurnSel, placing, setPlacing, showZones, setShowZones, canUndo: furnHistory.current.length > 0,
    undoFurniture, updateItem, rotateItem, placeItem, duplicateItem, rowItems, deleteItem, moveItem,
    resetSaved, reset, mergeRemote,
  }
}
