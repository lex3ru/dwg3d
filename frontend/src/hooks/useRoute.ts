import { useRef, useState } from 'react'
import type { FloorMeta, RoomMeta } from '../api'
import type { RouteState } from '../ui/Toolbar'
import { findPath, type Grid } from '../viewer/route'
import type { RouteView } from '../viewer/Viewer'
import type { V3 } from '../api'

export const NO_ROUTE: RouteState = { floor: null, step: 'from', fromLabel: '', toLabel: '', length: null, error: null }

/** The quick A-to-B route of the route tool: two ends on one floor, the way found over the floor's grid. */
export function useRoute(p: {
  setFloor: (id: string) => void
  loadGrid: (f: FloorMeta) => Promise<Grid | null>
  toPlan: (v: V3) => [number, number]
  planToGltf: (p: [number, number], elev: number) => V3
}) {
  const [route, setRoute] = useState<RouteState>(NO_ROUTE)
  const [routeView, setRouteView] = useState<RouteView | null>(null)
  const routeEnds = useRef<{ from: [number, number] | null; to: [number, number] | null }>({ from: null, to: null })

  const setRouteEnd = async (end: 'from' | 'to', f: FloorMeta, pt: [number, number], label: string) => {
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
    ends = { ...ends, [end]: pt }
    routeEnds.current = ends
    const next: RouteState = {
      ...st, floor: f.id, [end === 'from' ? 'fromLabel' : 'toLabel']: label, error: null, length: null,
      step: ends.from && ends.to ? 'done' : ends.from ? 'to' : 'from',
    }
    setRoute(next)
    p.setFloor(f.id)
    const elev = f.elevation!
    setRouteView({ floor: f.id, pts: [], from: ends.from ? p.planToGltf(ends.from, elev) : null, to: ends.to ? p.planToGltf(ends.to, elev) : null, length: 0 })
    if (!ends.from || !ends.to) return
    const grid = await p.loadGrid(f)
    const path = grid ? findPath(grid, ends.from, ends.to) : null
    if (!path) {
      setRoute({ ...next, error: 'Путь не найден: точки разделены стенами без проёмов' })
      return
    }
    setRoute({ ...next, length: path.length })
    setRouteView({
      floor: f.id, pts: path.pts.map((q) => p.planToGltf(q, elev)), from: p.planToGltf(ends.from, elev),
      to: p.planToGltf(ends.to, elev), length: path.length,
    })
  }
  const routeRoom = (end: 'from' | 'to', f: FloorMeta, room: RoomMeta) =>
    setRouteEnd(end, f, p.toPlan(room.label_pos), room.name || room.type || 'помещение')
  const clearRoute = () => {
    routeEnds.current = { from: null, to: null }
    setRoute(NO_ROUTE)
    setRouteView(null)
  }
  return { route, routeView, setRouteEnd, routeRoom, clearRoute }
}
