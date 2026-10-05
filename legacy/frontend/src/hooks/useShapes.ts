import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { batchRows, type FloorMeta, type Job, type Layer, type RowOp, type ShapeObject, type ViewSettings, type XY } from '../api'
import { conflictText } from '../furniture/sync'
import { canEdit, READ_ONLY } from '../session'
import type { PlanClick } from './useShapeEditor'
import type { Grid } from '../viewer/route'
import { checkFlows, computeRoute, connectors, type CableProps, type RouteProps, type RouteStop, type Rules, type ZoneProps } from '../viewer/routing'
import type { SceneCtx } from '../viewer/scene'
import type { ShapeView } from '../viewer/Shapes'

/**
 * Routes of people, zones and cable lines (the shapes of the view): what the
 * scene draws, the flow conflicts, saving to the server, and the drawing state
 * of the routes panel.
 */
export function useShapes(p: {
  shown: Job | null
  view: ViewSettings
  setView: (f: (v: ViewSettings) => ViewSettings) => void
  layers: Layer[]
  rules: Rules | null
  hiddenNow: Set<string>
  syncLayers: (items: { layer?: string }[]) => void
  rebuilding: boolean
  reload: () => void
  floors: FloorMeta[]
  loadGrid: (f: FloorMeta) => Promise<Grid | null>
  ctx: SceneCtx
  cx: number
  cy: number
  setFloor: (id: string) => void
  tool: string
}) {
  const { shown, view, layers, rules, hiddenNow, floors } = p
  const shapes = useMemo(() => (view.shapes ?? []).filter((x) => !x.layer || !hiddenNow.has(x.layer)), [view.shapes, hiddenNow])
  const [shapeSel, setShapeSel] = useState<string | null>(null)
  const [shapeDraft, setShapeDraft] = useState<{ floor: string; pts: XY[]; closed: boolean } | null>(null)
  const [shapePicking, setShapePicking] = useState(false)
  const shapePick = useRef<((c: PlanClick) => void) | null>(null)
  const zoneLayerIds = useMemo(() => new Set(layers.filter((l) => l.kind === 'zones').map((l) => l.id)), [layers])
  const netLayerIds = useMemo(() => new Set(layers.filter((l) => l.kind === 'network').map((l) => l.id)), [layers])
  const conflicts = useMemo(() => {
    if (!rules) return []
    const routes = shapes.filter((x) => x.geom === 'route').map((x) => {
      const pr = (x.props ?? {}) as unknown as RouteProps
      return { id: x.id, name: pr.name, flow: pr.flow, path: pr.path ?? [] }
    })
    const zones = shapes.filter((x) => x.geom === 'polygon' && zoneLayerIds.has(x.layer ?? '')).map((x) => {
      const pr = (x.props ?? {}) as unknown as ZoneProps
      return { id: x.id, name: pr.name, zone: pr.zone, floor: x.floor, pts: x.points ?? [] }
    })
    return checkFlows(routes, zones, rules)
  }, [shapes, rules, zoneLayerIds])
  const shapeViews = useMemo<ShapeView[]>(() => shapes.flatMap((x): ShapeView[] => {
    if (x.geom === 'route') {
      const pr = (x.props ?? {}) as unknown as RouteProps
      return [{ id: x.id, kind: 'route', color: rules?.flows[pr.flow]?.color ?? '#1c7ed6', segments: pr.path ?? [],
        stops: (pr.stops ?? []).map((st, i) => ({ floor: st.floor, at: st.at, label: st.label || `Остановка ${i + 1}` })),
        broken: !!pr.problem, label: pr.name }]
    }
    if (x.geom === 'polygon' && zoneLayerIds.has(x.layer ?? '')) {
      const pr = (x.props ?? {}) as unknown as ZoneProps
      return [{ id: x.id, kind: 'zone', color: rules?.zone_kinds[pr.zone]?.color ?? '#868e96', segments: [{ floor: x.floor, pts: x.points ?? [] }], label: pr.name }]
    }
    if (x.geom === 'polyline' && netLayerIds.has(x.layer ?? '')) {
      const pr = (x.props ?? {}) as unknown as CableProps
      return [{ id: x.id, kind: 'line', color: rules?.cables[pr.cable]?.color ?? '#495057', segments: [{ floor: x.floor, pts: x.points ?? [] }], label: pr.name }]
    }
    return []
  }), [shapes, rules, zoneLayerIds, netLayerIds])

  const saveShapes = async (ops: RowOp[]): Promise<boolean> => {
    if (!shown) return false
    if (!canEdit()) { alert(READ_ONLY); return false }
    if (p.rebuilding) { alert('Идёт перестроение модели: маршруты и зоны можно менять после него'); return false }
    try {
      const res = await batchRows<ShapeObject>(shown.id, 'objects', shown.build, ops)
      p.setView((v) => {
        const got = new Map(res.items.map((it) => [it.id, it]))
        const kept = (v.shapes ?? []).filter((x) => !res.deleted.includes(x.id)).map((x) => got.get(x.id) ?? x)
        const added = res.items.filter((it) => !kept.some((x) => x.id === it.id))
        return { ...v, shapes: [...kept, ...added] }
      })
      p.syncLayers(res.items)
      return true
    } catch (e) {
      alert(conflictText(e, (i) => ((view.shapes ?? []).find((x) => x.id === i)?.props?.name as string) || 'Объект'))
      p.reload()
      return false
    }
  }
  const computeStops = (stops: RouteStop[]) => computeRoute(stops, floors, shown?.result ? connectors(shown.result) : [],
    async (fid) => { const f = floors.find((x) => x.id === fid); return f ? p.loadGrid(f) : null },
    (st, i) => st.label || `остановка ${i + 1}`)
  const flyToPlan = (fid: string, [x, y]: XY, dist = 16) => {
    const f = floors.find((q) => q.id === fid)
    if (!f) return
    p.setFloor(fid)
    const pt = new THREE.Vector3(x - p.cx, (f.elevation ?? 0) + (p.ctx.offset.get(fid) ?? 0), -(y - p.cy))
    setTimeout(() => p.ctx.api?.flyToPoint(pt, dist), 60)
  }
  useEffect(() => { if (p.tool !== 'shapes') { setShapeDraft(null); setShapePicking(false) } }, [p.tool])
  return {
    shapes, shapeSel, setShapeSel, shapeDraft, setShapeDraft, shapePicking, setShapePicking, shapePick,
    conflicts, shapeViews, saveShapes, computeStops, flyToPlan,
  }
}
