import { useCallback, useEffect, useRef } from 'react'
import type * as THREE from 'three'
import { getPlan, type FloorMeta, type Job, type PlanData, type V3, type ViewSettings } from '../api'
import { catalogItem } from '../furniture/catalog'
import { footprint, itemElev, itemSize } from '../furniture/geom'
import { buildGrid, type Grid } from '../viewer/route'

/**
 * 2D plans of the shown build and the walkability grids made from them (cached
 * until the build or the furniture changes), and the conversion between plan
 * coordinates (m, Y up the page) and the viewer's glTF frame.
 */
export function usePlans(shown: Job | null, view: ViewSettings) {
  const plans = useRef(new Map<string, PlanData>())
  const grids = useRef(new Map<string, Grid | null>())
  const cx = shown?.result?.center?.[0] ?? 0, cy = shown?.result?.center?.[1] ?? 0

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
  const clearCaches = useCallback(() => { plans.current.clear(); grids.current.clear() }, [])

  useEffect(() => { grids.current.clear() }, [view.furniture])
  useEffect(() => { plans.current.clear() }, [shown?.build])
  return { cx, cy, toPlan, planToGltf, loadPlan, loadGrid, clearCaches }
}
