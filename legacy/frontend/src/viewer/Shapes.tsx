import { Html, Line } from '@react-three/drei'
import { useMemo } from 'react'
import * as THREE from 'three'
import type { FloorMeta, V3, XY } from '../api'
import FloorFollower from './FloorFollower'
import { htmlLayer, type SceneCtx } from './scene'

/** A route or a zone as drawn: plan coordinates, colours already chosen. */
export interface ShapeView {
  id: string
  kind: 'route' | 'zone' | 'line'
  color: string
  /** routes: the computed way per floor; zones: the outline (one segment) */
  segments: { floor: string; pts: XY[] }[]
  /** routes: numbered stops */
  stops?: { floor: string; at: XY; label: string }[]
  broken?: boolean
  label?: string
}

export interface ShapesProps {
  items: ShapeView[]
  selected: string | null
  /** a zone or route being drawn: its points so far */
  draft: { floor: string; pts: XY[]; closed: boolean } | null
  /** problems to point at */
  alerts: { floor: string; at: XY; text: string }[]
}

/** Routes of people and zones on the floors (above the floor, visible through the model). */
export default function Shapes({ ctx, floors, center, visible, ...p }: ShapesProps & {
  ctx: SceneCtx; floors: FloorMeta[]; center: [number, number]; visible: Set<string>
}) {
  const elev = useMemo(() => new Map(floors.map((f) => [f.id, f.elevation ?? 0])), [floors])
  const g = (floor: string, [x, y]: XY, dy: number): V3 => [x - center[0], (elev.get(floor) ?? 0) + dy, -(y - center[1])]
  const on = (f: string) => visible.has(f)
  return (
    <>
      {p.items.filter((s) => s.kind === 'zone').flatMap((s) => s.segments.filter((sg) => on(sg.floor) && sg.pts.length >= 3).map((sg, i) => (
        <FloorFollower key={`${s.id}-${i}`} ctx={ctx} floor={sg.floor}>
          <Zone pts={sg.pts.map((q) => g(sg.floor, q, 0.03))} color={s.color} selected={p.selected === s.id} />
        </FloorFollower>
      )))}
      {p.items.filter((s) => s.kind === 'line').flatMap((s) => s.segments.filter((sg) => on(sg.floor) && sg.pts.length >= 2).map((sg, i) => (
        <FloorFollower key={`${s.id}-l${i}`} ctx={ctx} floor={sg.floor}>
          <Line points={sg.pts.map((q) => g(sg.floor, q, 0.06))} color={s.color} lineWidth={p.selected === s.id ? 5 : 3}
            depthTest={false} renderOrder={17} />
        </FloorFollower>
      )))}
      {p.items.filter((s) => s.kind === 'route').flatMap((s) => [
        ...s.segments.filter((sg) => on(sg.floor) && sg.pts.length >= 2).map((sg, i) => {
          const pts = sg.pts.map((q) => g(sg.floor, q, 0.08))
          const sel = p.selected === s.id
          return (
            <FloorFollower key={`${s.id}-s${i}`} ctx={ctx} floor={sg.floor}>
              <Line points={pts} color="#ffffff" lineWidth={sel ? 9 : 6.5} depthTest={false} renderOrder={18} transparent opacity={0.7} />
              <Line points={pts} color={s.color} lineWidth={sel ? 6 : 4.5} depthTest={false} renderOrder={19}
                dashed={s.broken} dashSize={0.6} gapSize={0.4} />
            </FloorFollower>
          )
        }),
        ...(s.stops ?? []).filter((st) => on(st.floor)).map((st, i) => (
          <FloorFollower key={`${s.id}-p${i}`} ctx={ctx} floor={st.floor}>
            <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={g(st.floor, st.at, 0.1)} center zIndexRange={[21, 0]}>
              <div className={p.selected === s.id ? 'grid h-[18px] min-w-[18px] cursor-default place-items-center rounded-full border-2 border-white px-1 text-[11px] font-bold text-white shadow-[0_1px_4px_rgba(0,0,0,.3)]' : 'size-2.5 rounded-full border-[1.5px] border-white shadow-[0_1px_4px_rgba(0,0,0,.3)]'} style={{ background: s.color }} title={st.label}>{p.selected === s.id ? i + 1 : ''}</div>
            </Html>
          </FloorFollower>
        )),
      ])}
      {p.draft && on(p.draft.floor) && p.draft.pts.length > 0 && (
        <FloorFollower ctx={ctx} floor={p.draft.floor}>
          {p.draft.pts.length >= 2 && (
            <Line points={[...p.draft.pts, ...(p.draft.closed ? [p.draft.pts[0]] : [])].map((q) => g(p.draft!.floor, q, 0.09))}
              color="#f08c00" lineWidth={3} depthTest={false} renderOrder={23} dashed dashSize={0.4} gapSize={0.25} />
          )}
          {p.draft.pts.map((q, i) => (
            <mesh key={i} position={g(p.draft!.floor, q, 0.1)} rotation-x={-Math.PI / 2} renderOrder={24}>
              <circleGeometry args={[0.18, 16]} />
              <meshBasicMaterial color={i === 0 ? '#e8590c' : '#f08c00'} depthTest={false} />
            </mesh>
          ))}
        </FloorFollower>
      )}
      {p.alerts.filter((a) => on(a.floor)).map((a, i) => (
        <FloorFollower key={`alert${i}`} ctx={ctx} floor={a.floor}>
          <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={g(a.floor, a.at, 0.15)} center zIndexRange={[23, 0]}>
            <div className="grid size-5 place-items-center rounded-full border-2 border-white bg-destructive text-xs font-bold text-white shadow-[0_1px_6px_rgba(224,49,49,.5)]" title={a.text}>!</div>
          </Html>
        </FloorFollower>
      ))}
    </>
  )
}

function Zone({ pts, color, selected }: { pts: V3[]; color: string; selected: boolean }) {
  const geom = useMemo(() => {
    const shape = new THREE.Shape(pts.map(([x, , z]) => new THREE.Vector2(x, -z)))
    const g = new THREE.ShapeGeometry(shape)
    g.rotateX(-Math.PI / 2)
    g.translate(0, pts[0][1], 0)
    return g
  }, [pts])
  return (
    <>
      <mesh geometry={geom} renderOrder={12}>
        <meshBasicMaterial color={color} transparent opacity={selected ? 0.38 : 0.22} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
      <Line points={[...pts, pts[0]]} color={color} lineWidth={selected ? 3.5 : 2} renderOrder={13} />
    </>
  )
}
