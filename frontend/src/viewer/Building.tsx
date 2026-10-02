import { Html, useGLTF } from '@react-three/drei'
import { useFrame, type ThreeEvent } from '@react-three/fiber'
import { Suspense, useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import type { FloorMeta, Result, RoomMeta } from '../api'
import type { Display, FacadePreset, NavMode, Projection, Tool } from '../state'
import FloorFollower from './FloorFollower'
import RoomLabels from './RoomLabels'
import { roleOf } from './looks'
import { floorOf, htmlLayer, isVisible, openFloors, typeLabel, visibleFloors, type SceneCtx } from './scene'

const EXPLODE_MS = 400

export interface RoomHit { room: RoomMeta; floor: FloorMeta; point: THREE.Vector3 }
export interface Pick {
  point: THREE.Vector3
  /** the point with the floor's explode offset removed (what pins store) */
  local: THREE.Vector3
  floor: string | null
  room: RoomHit | null
  normal: THREE.Vector3 | null
}

interface Props {
  ctx: SceneCtx
  url: string
  result: Result
  display: Display
  floor: string | null
  proj: Projection
  nav: NavMode
  tool: Tool
  eco: boolean
  edges: boolean
  night: number
  preset: FacadePreset
  planes: THREE.Plane[]
  selectedRoom: string | null
  onRoomClick: (r: RoomHit | null) => void
  onPick: (p: Pick) => void
  onDoublePick: (p: Pick) => void
  onPointer: (p: Pick | null) => void       // cursor probe for tools
  children?: React.ReactNode
}

export default function Building(p: Props) {
  const { ctx, result, display, floor: active, nav, proj } = p
  const gltf = useGLTF(p.url)
  // own copy: materials are swapped per floor, the cached glTF stays pristine
  const scene = useMemo(() => gltf.scene.clone(true), [gltf.scene])
  const [hover, setHover] = useState<RoomHit | null>(null)
  const floors = useMemo(() => [...result.floors].sort((a, b) => a.elevation! - b.elevation!), [result.floors])
  const roomByNode = useMemo(() => {
    const m = new Map<string, { room: RoomMeta; floor: FloorMeta }>()
    result.floors.forEach((f) => f.rooms.forEach((r) => m.set(r.node, { room: r, floor: f })))
    return m
  }, [result.floors])

  // ---- scene preparation (once per model)
  const model = useMemo(() => ctx.prepare(scene, floors, result.roof_node), [scene, floors, ctx, result.roof_node])

  // ---- explode targets (animated in ctx.tick)
  const visible = useMemo(() => visibleFloors(floors, display, active, nav), [floors, display, active, nav])
  const exploded = display.explode && proj === '3d' && nav !== 'walk'
  const roofShown = !!ctx.roof && display.roof && proj === '3d' && (active == null || nav === 'walk')
  useEffect(() => ctx.explode(exploded, display.explodeGap, EXPLODE_MS), [exploded, display.explodeGap, floors, ctx])

  // ---- ground level: under the entrance floor, lower when a basement is looked at
  useEffect(() => {
    const entrance = result.entrances?.[0]?.floor
    const ground = floors.find((f) => f.id === entrance) ?? floors.find((f) => f.elevation! >= -0.5) ?? floors[0]
    const act = floors.find((f) => f.id === active)
    const slab = 0.25
    let y = (ground?.elevation ?? 0) - 0.03
    if (exploded) y = (floors[0]?.elevation ?? 0) - slab - 0.05
    else if (act && nav !== 'walk' && act.elevation! < y) y = act.elevation! - slab - 0.05
    ctx.setGround(y)
  }, [floors, active, exploded, nav, result.entrances, ctx])

  // ---- materials (per-floor looks)
  const typeColors = useMemo(() => Object.fromEntries((result.room_types ?? []).map((t) => [t.type, t.color])), [result.room_types])
  const floorIndex = useMemo(() => new Map(floors.map((f, i) => [f.id, i])), [floors])

  useFrame((state) => {
    ctx.tick(visible, display, roofShown)
    // materials: on change, and every 1.5 s while an animated facade preset is lit
    const animated = p.night > 0.01 && p.preset.animate
    const key = JSON.stringify([display, active, nav, p.eco, p.edges, p.night, p.preset, p.planes.length,
      animated ? Math.floor(state.clock.elapsedTime / 1.5) : 0])
    ctx.applyLooks({
      display, active: nav === 'walk' ? null : active, eco: p.eco, edges: p.edges, night: p.night, preset: p.preset,
      typeColors, planes: p.planes, time: state.clock.elapsedTime, floorIndex,
    }, key)
  })

  // ---- pointer
  const firstHit = (e: ThreeEvent<PointerEvent | MouseEvent>) =>
    e.intersections.find((i) => isVisible(i.object) && (i.object as THREE.Mesh).isMesh && roleOf(i.object) !== 'label' &&
      p.planes.every((pl) => pl.distanceToPoint(i.point) >= -1e-3))

  const toPick = (hit: THREE.Intersection | undefined): Pick | null => {
    if (!hit) return null
    const r = roomByNode.get(hit.object.name)
    const n = hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : null
    const floor = floorOf(hit.object)
    const local = hit.point.clone()
    if (floor) local.y -= ctx.offset.get(floor) ?? 0
    return {
      point: hit.point.clone(), local, floor, normal: n,
      room: r ? { room: r.room, floor: r.floor, point: hit.point.clone() } : null,
    }
  }

  const onMove = (e: ThreeEvent<PointerEvent>) => {
    if (nav === 'walk') return
    const hit = firstHit(e)
    if (p.tool !== 'none') {
      ctx.looks.setHover(null)
      setHover(null)
      p.onPointer(toPick(hit))
      return
    }
    const obj = hit?.object as THREE.Mesh | undefined
    const r = obj && roomByNode.get(obj.name)
    if (!obj || !r) {
      ctx.looks.setHover(null)
      setHover(null)
      return
    }
    e.stopPropagation()
    ctx.looks.setHover(obj)
    setHover({ room: r.room, floor: r.floor, point: hit!.point.clone() })
  }

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    if (nav === 'walk' || e.delta > 4) return
    const pick = toPick(firstHit(e))
    if (p.tool !== 'none') {
      if (pick) {
        e.stopPropagation()
        p.onPick(pick)
      }
      return
    }
    p.onRoomClick(pick?.room ?? null)
  }

  const onDoubleClick = (e: ThreeEvent<MouseEvent>) => {
    if (nav === 'walk' || p.tool === 'none') return
    const pick = toPick(firstHit(e))
    if (pick) {
      e.stopPropagation()
      p.onDoublePick(pick)
    }
  }

  // keep the selected room highlighted
  useEffect(() => {
    if (!p.selectedRoom) return
    const mesh = scene.getObjectByName(p.selectedRoom) as THREE.Mesh | undefined
    if (mesh) ctx.looks.setHover(mesh)
    return () => ctx.looks.setHover(null)
  }, [p.selectedRoom, scene, ctx])

  const open = openFloors(floors, visible, { exploded, xray: display.xray, topDown: proj === '2d', walking: nav === 'walk', roofShown })

  return (
    <>
      <primitive object={model} onPointerMove={onMove} onClick={onClick} onDoubleClick={onDoubleClick}
        onPointerOut={() => { if (!p.selectedRoom) ctx.looks.setHover(null); setHover(null); p.onPointer(null) }} />
      {display.labels && floors.map((f) => (
        <FloorFollower key={f.id} ctx={ctx} floor={f.id}>
          {/* the font loads asynchronously: never hold the whole scene back for it */}
          <Suspense fallback={null}>
            <RoomLabels floor={f} show={open.has(f.id)} typeLabels={result.room_types ?? []} />
          </Suspense>
        </FloorFollower>
      ))}
      {hover && p.tool === 'none' && hover.room.node !== p.selectedRoom && (
        <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={hover.point} style={{ pointerEvents: 'none' }} zIndexRange={[10, 0]}>
          <div className="tooltip"><b>{hover.room.name || typeLabel(result, hover.room.type) || 'Помещение'}</b>
            <span>{hover.room.area.toFixed(1)} м² · {hover.floor.name}</span></div>
        </Html>
      )}
      {exploded && display.labels && floors.map((f, i) => {
        const b = ctx.floorBox.get(f.id)
        if (!b || !visible.has(f.id)) return null
        return (
          <Html portal={htmlLayer as React.RefObject<HTMLElement>} key={f.id} position={[b.min.x - 1.5, f.elevation! + i * display.explodeGap + 1.5, (b.min.z + b.max.z) / 2]}
            center style={{ pointerEvents: 'none' }} zIndexRange={[5, 0]}>
            <div className={`floor-label${f.id === active ? ' on' : ''}`}>{f.name}</div>
          </Html>
        )
      })}
      {p.children}
    </>
  )
}
