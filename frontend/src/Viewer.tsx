import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber'
import { Html, Line, OrbitControls, useGLTF } from '@react-three/drei'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three/examples/jsm/controls/OrbitControls.js'
import type { FloorMeta, Result, RoomMeta } from './api'

export type ViewMode = 'all' | 'isolate' | 'below' | 'explode'
export type Tool = 'orbit' | 'measure' | 'walk'
export type MeasureMode = 'length' | 'area'

export interface ViewState {
  mode: ViewMode
  selected: string | null   // floor id
  explode: number           // extra meters between floors
  showRoof: boolean
  showRooms: boolean
  showGlass: boolean
  labels: boolean
  cutH: { on: boolean; y: number }   // horizontal section: keep below y
  cutV: { on: boolean; x: number }   // vertical section: keep x <= value
}

export interface FocusRoom {
  node: string
  nonce: number
}

interface Props {
  url: string
  result: Result
  view: ViewState
  tool: Tool
  focusRoom: FocusRoom | null
  measureMode: MeasureMode
  onExitWalk: () => void
}

/** Vector area (Newell) of a closed 3D polygon: |n| / 2 = area, n = normal. */
function newell(pts: THREE.Vector3[]): THREE.Vector3 {
  const n = new THREE.Vector3()
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length]
    n.x += (a.y - b.y) * (a.z + b.z)
    n.y += (a.z - b.z) * (a.x + b.x)
    n.z += (a.x - b.x) * (a.y + b.y)
  }
  return n.multiplyScalar(0.5)
}

/** Fill triangles for a (roughly planar) 3D polygon. */
function polygonGeometry(pts: THREE.Vector3[]): THREE.BufferGeometry | null {
  if (pts.length < 3) return null
  const n = newell(pts)
  if (n.lengthSq() < 1e-10) return null
  n.normalize()
  const u = new THREE.Vector3().crossVectors(Math.abs(n.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0), n).normalize()
  const v = new THREE.Vector3().crossVectors(n, u)
  const flat = pts.map((p) => new THREE.Vector2(p.dot(u), p.dot(v)))
  const tris = THREE.ShapeUtils.triangulateShape(flat, [])
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pts.flatMap((p) => [p.x, p.y, p.z]), 3))
  g.setIndex(tris.flat())
  return g
}

const HOVER_MAT = new THREE.MeshStandardMaterial({ color: 0x4dabf7, emissive: 0x1c7ed6, emissiveIntensity: 0.35 })
const SOLID_ROLES = new Set(['walls', 'partitions', 'columns', 'glass', 'doors'])

function isVisible(o: THREE.Object3D | null): boolean {
  for (let p = o; p; p = p.parent) if (!p.visible) return false
  return true
}

function roleOf(o: THREE.Object3D): string | undefined {
  return (o.userData as { role?: string }).role
}

interface Hover { name: string; area: number; point: THREE.Vector3 }

function Model({ url, result, view, tool, focusRoom, measureMode, onExitWalk }: Props) {
  const { scene } = useGLTF(url)
  const controls = useThree((s) => s.controls) as OrbitControlsImpl | null
  const camera = useThree((s) => s.camera)
  const gl = useThree((s) => s.gl)
  const [hover, setHover] = useState<Hover | null>(null)
  const hovered = useRef<{ mesh: THREE.Mesh; mat: THREE.Material | THREE.Material[] } | null>(null)
  const focus = useRef<{ target: THREE.Vector3; pos: THREE.Vector3 } | null>(null)
  const [measure, setMeasure] = useState<THREE.Vector3[]>([])
  const [closed, setClosed] = useState(false)                       // area polygon finished
  const [probe, setProbe] = useState<THREE.Vector3 | null>(null)    // cursor point for previews
  const size = useThree((s) => s.size)

  const floors = useMemo(() => [...result.floors].sort((a, b) => a.elevation! - b.elevation!), [result.floors])
  const roomByNode = useMemo(() => {
    const m = new Map<string, { room: RoomMeta; floor: FloorMeta }>()
    result.floors.forEach((f) => f.rooms.forEach((r) => m.set(r.node, { room: r, floor: f })))
    return m
  }, [result.floors])

  // scene preparation: shadows, edge line style, floor groups
  const groups = useMemo(() => {
    const g = new Map<string, THREE.Object3D>()
    scene.traverse((o) => {
      const role = roleOf(o)
      if ((o as THREE.Mesh).isMesh) {
        const mesh = o as THREE.Mesh
        mesh.castShadow = role !== 'glass' && role !== 'room'
        mesh.receiveShadow = true
      }
      if ((o as THREE.LineSegments).isLineSegments) {
        const l = o as THREE.LineSegments
        const m = l.material as THREE.LineBasicMaterial
        m.transparent = true
        m.opacity = 0.55
        l.raycast = () => {}
      }
    })
    for (const f of result.floors) {
      const node = scene.getObjectByName(f.node)
      if (node) g.set(f.id, node)
    }
    return g
  }, [scene, result.floors])

  // section planes
  const planes = useMemo(() => ({
    h: new THREE.Plane(new THREE.Vector3(0, -1, 0), 0),
    v: new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0),
  }), [])
  useEffect(() => {
    gl.localClippingEnabled = true
    const active = [...(view.cutH.on ? [planes.h] : []), ...(view.cutV.on ? [planes.v] : [])]
    scene.traverse((o) => {
      const mat = (o as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined
      if (!mat) return
      for (const m of Array.isArray(mat) ? mat : [mat]) {
        m.clippingPlanes = active
        m.clipShadows = true
        m.needsUpdate = true
      }
    })
    HOVER_MAT.clippingPlanes = active
    HOVER_MAT.needsUpdate = true
  }, [view.cutH.on, view.cutV.on, scene, gl, planes])
  planes.h.constant = view.cutH.y
  planes.v.constant = view.cutV.x

  // fit camera on load
  useEffect(() => {
    const box = new THREE.Box3().setFromObject(scene)
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())
    const r = Math.max(size.x, size.y, size.z)
    const fov = ((camera as THREE.PerspectiveCamera).fov ?? 40) * Math.PI / 180
    const dist = (size.length() / 2 / Math.tan(fov / 2)) * 1.05
    const dir = new THREE.Vector3(0.62, 0.42, 0.66).normalize()
    camera.position.copy(center).addScaledVector(dir, dist)
    camera.near = r / 2000
    camera.far = r * 20
    camera.updateProjectionMatrix()
    if (controls) {
      controls.target.copy(center)
      controls.update()
    }
  }, [scene, camera, controls])

  // user grabbing the camera cancels an ongoing fly-to
  useEffect(() => {
    if (!controls) return
    const stop = () => { focus.current = null }
    controls.addEventListener('start', stop)
    return () => controls.removeEventListener('start', stop)
  }, [controls])

  const flyTo = (box: THREE.Box3, minElev = 0.35) => {
    const target = box.getCenter(new THREE.Vector3())
    const fov = ((camera as THREE.PerspectiveCamera).fov ?? 40) * Math.PI / 180
    const dist = (box.getSize(new THREE.Vector3()).length() / 2 / Math.tan(fov / 2)) * 1.1
    const dir = controls ? camera.position.clone().sub(controls.target).normalize() : new THREE.Vector3(0.62, 0.42, 0.66).normalize()
    if (dir.y < minElev) dir.setY(minElev).normalize()
    focus.current = { target, pos: target.clone().addScaledVector(dir, Math.max(dist, 4)) }
  }

  // focus the selected floor / whole exploded building
  useEffect(() => {
    if (tool === 'walk') return
    const f = floors.find((x) => x.id === view.selected)
    const node = f && groups.get(f.id)
    if (view.mode === 'explode') {
      const box = new THREE.Box3()
      floors.forEach((fl, i) => {
        const n = groups.get(fl.id)
        if (!n) return
        const b = new THREE.Box3().setFromObject(n)
        b.translate(new THREE.Vector3(0, i * view.explode - n.position.y, 0))
        box.union(b)
      })
      const roof = result.roof_node ? scene.getObjectByName(result.roof_node) : null
      if (roof && view.showRoof) {
        const b = new THREE.Box3().setFromObject(roof)
        b.translate(new THREE.Vector3(0, floors.length * view.explode - roof.position.y, 0))
        box.union(b)
      }
      if (!box.isEmpty()) flyTo(box)
    } else if (node && view.mode !== 'all') {
      flyTo(new THREE.Box3().setFromObject(node))
    } else {
      focus.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.selected, view.mode, view.explode, view.showRoof, floors, groups, scene, result.roof_node, tool])

  // fly to a searched room and flash it
  useEffect(() => {
    if (!focusRoom) return
    const mesh = scene.getObjectByName(focusRoom.node) as THREE.Mesh | undefined
    if (!mesh) return
    const t = setTimeout(() => {
      const box = new THREE.Box3().setFromObject(mesh)
      box.expandByScalar(2)
      flyTo(box, 0.6)
      clearHover()
      hovered.current = { mesh, mat: mesh.material }
      mesh.material = HOVER_MAT
      const r = roomByNode.get(focusRoom.node)
      if (r) setHover({ name: r.room.name || 'Помещение', area: r.room.area, point: box.getCenter(new THREE.Vector3()) })
    }, 50)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRoom])

  // walk mode: start inside the largest room of the selected floor
  const walkFloor = useMemo(() => floors.find((f) => f.id === view.selected) ?? floors[0], [floors, view.selected])
  useEffect(() => {
    if (tool !== 'walk' || !walkFloor) return
    focus.current = null
    const room = [...walkFloor.rooms].sort((a, b) => b.area - a.area)[0]
    const node = groups.get(walkFloor.id)
    const c = room ? new THREE.Vector3(...room.label_pos) : new THREE.Box3().setFromObject(node!).getCenter(new THREE.Vector3())
    camera.position.set(c.x, walkFloor.elevation! + 1.6 + (node?.position.y ?? 0), c.z)
    camera.lookAt(c.x + 1, walkFloor.elevation! + 1.6, c.z)
  }, [tool, walkFloor, groups, camera])

  const keys = useRef<Record<string, boolean>>({})
  useEffect(() => {
    if (tool !== 'walk') return
    const el = gl.domElement
    const euler = new THREE.Euler(0, 0, 0, 'YXZ').setFromQuaternion(camera.quaternion)
    let dragging = false
    let wasLocked = false
    const look = (mx: number, my: number) => {
      euler.y -= mx * 0.0025
      euler.x = Math.max(-1.4, Math.min(1.4, euler.x - my * 0.0025))
      camera.quaternion.setFromEuler(euler)
    }
    const down = (e: KeyboardEvent) => {
      keys.current[e.code] = true
      if (e.code === 'Escape' && document.pointerLockElement !== el) onExitWalk()
    }
    const up = (e: KeyboardEvent) => { keys.current[e.code] = false }
    // mouse look: pointer lock when available, otherwise drag with the mouse
    const move = (e: MouseEvent) => {
      if (document.pointerLockElement === el || dragging) look(e.movementX, e.movementY)
    }
    const md = () => { dragging = true }
    const mu = () => { dragging = false }
    const lockChange = () => {
      if (document.pointerLockElement === el) wasLocked = true
      else if (wasLocked) onExitWalk()      // Esc released the lock
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('mousemove', move)
    el.addEventListener('mousedown', md)
    window.addEventListener('mouseup', mu)
    document.addEventListener('pointerlockchange', lockChange)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('mousemove', move)
      el.removeEventListener('mousedown', md)
      window.removeEventListener('mouseup', mu)
      document.removeEventListener('pointerlockchange', lockChange)
      if (document.pointerLockElement === el) document.exitPointerLock()
      keys.current = {}
    }
  }, [tool, gl, camera, onExitWalk])
  const ray = useMemo(() => new THREE.Raycaster(), [])
  const solids = useMemo(() => {
    const out: THREE.Object3D[] = []
    scene.traverse((o) => { if ((o as THREE.Mesh).isMesh && SOLID_ROLES.has(roleOf(o) ?? '')) out.push(o) })
    return out
  }, [scene])

  // measure: Esc clears, Backspace removes the last point, Enter closes the area
  useEffect(() => {
    setMeasure([])
    setClosed(false)
    setProbe(null)
  }, [tool, measureMode])
  useEffect(() => {
    if (tool !== 'measure') return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setMeasure([]); setClosed(false) }
      else if (e.key === 'Backspace' || e.key === 'Delete') {
        setClosed(false)
        setMeasure((m) => m.slice(0, -1))
      } else if (e.key === 'Enter' && measureMode === 'area') {
        setMeasure((m) => { if (m.length >= 3) setClosed(true); return m })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tool, measureMode])

  useFrame((_, dt) => {
    const sel = floors.find((x) => x.id === view.selected)
    const k = 1 - Math.exp(-dt * 8)
    floors.forEach((f, i) => {
      const node = groups.get(f.id)
      if (!node) return
      let visible = true
      if (view.mode === 'isolate' && sel) visible = f.id === sel.id
      if (view.mode === 'below' && sel) visible = f.elevation! <= sel.elevation!
      node.visible = visible
      const ty = view.mode === 'explode' ? i * view.explode : 0
      node.position.y += (ty - node.position.y) * k
      node.traverse((o) => {
        const role = roleOf(o)
        if (role === 'room') o.visible = view.showRooms
        if (role === 'glass') o.visible = view.showGlass
      })
    })
    if (result.roof_node) {
      const roof = scene.getObjectByName(result.roof_node)
      if (roof) {
        roof.visible = view.showRoof && (view.mode === 'all' || view.mode === 'explode') && tool !== 'walk'
        const ty = view.mode === 'explode' ? floors.length * view.explode : 0
        roof.position.y += (ty - roof.position.y) * k
      }
    }
    if (tool === 'walk') {
      const kk = keys.current
      const speed = (kk.ShiftLeft || kk.ShiftRight ? 6 : 2.5) * dt
      const fwd = new THREE.Vector3()
      camera.getWorldDirection(fwd)
      fwd.y = 0
      fwd.normalize()
      const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0))
      const move = new THREE.Vector3()
      if (kk.KeyW || kk.ArrowUp) move.add(fwd)
      if (kk.KeyS || kk.ArrowDown) move.sub(fwd)
      if (kk.KeyD || kk.ArrowRight) move.add(right)
      if (kk.KeyA || kk.ArrowLeft) move.sub(right)
      if (move.lengthSq() > 0) {
        move.normalize()
        // simple collision: stop 0.3 m before walls / glass / doors
        ray.set(camera.position.clone().setY(camera.position.y - 0.6), move)
        ray.far = speed + 0.3
        const hit = ray.intersectObjects(solids, false).find((h) => isVisible(h.object))
        if (!hit) camera.position.addScaledVector(move, speed)
      }
      return
    }
    if (focus.current && controls) {
      const kk = 1 - Math.exp(-dt * 4)
      controls.target.lerp(focus.current.target, kk)
      camera.position.lerp(focus.current.pos, kk)
      if (controls.target.distanceTo(focus.current.target) < 0.02 && camera.position.distanceTo(focus.current.pos) < 0.05) {
        focus.current = null
      }
      controls.update()
    }
  })

  const clearHover = () => {
    if (hovered.current) {
      hovered.current.mesh.material = hovered.current.mat
      hovered.current = null
    }
    setHover(null)
  }

  const firstVisibleHit = (e: ThreeEvent<PointerEvent | MouseEvent>) =>
    e.intersections.find((i) => isVisible(i.object) && (i.object as THREE.Mesh).isMesh &&
      (!view.cutH.on || i.point.y <= view.cutH.y) && (!view.cutV.on || i.point.x <= view.cutV.x))

  const onMove = (e: ThreeEvent<PointerEvent>) => {
    if (tool === 'walk') return
    const hit = firstVisibleHit(e)
    if (tool === 'measure') {
      if (hovered.current || hover) clearHover()
      setProbe(hit ? hit.point.clone() : null)
      return
    }
    const obj = hit?.object as THREE.Mesh | undefined
    const r = obj && roomByNode.get(obj.name)
    if (!obj || !r) {
      if (hovered.current) clearHover()
      return
    }
    e.stopPropagation()
    if (hovered.current?.mesh !== obj) {
      clearHover()
      hovered.current = { mesh: obj, mat: obj.material }
      obj.material = HOVER_MAT
    }
    setHover({ name: r.room.name || 'Помещение', area: r.room.area, point: hit!.point.clone() })
  }

  const toScreen = (p: THREE.Vector3) => {
    const v = p.clone().project(camera)
    return [(v.x + 1) / 2 * size.width, (1 - v.y) / 2 * size.height]
  }

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    if (tool !== 'measure' || e.delta > 4) return
    const hit = firstVisibleHit(e)
    if (!hit) return
    e.stopPropagation()
    const p = hit.point.clone()
    if (measureMode === 'length') {
      setMeasure((m) => (m.length >= 2 ? [p] : [...m, p]))
      return
    }
    if (closed) { setClosed(false); setMeasure([p]); return }
    if (measure.length >= 3) {
      // clicking the first vertex (within 12 px) closes the contour
      const [fx, fy] = toScreen(measure[0])
      const [px, py] = toScreen(p)
      if (Math.hypot(fx - px, fy - py) < 12) { setClosed(true); return }
    }
    setMeasure((m) => [...m, p])
  }

  const onDoubleClick = (e: ThreeEvent<MouseEvent>) => {
    if (tool !== 'measure' || measureMode !== 'area' || closed) return
    e.stopPropagation()
    // the two clicks of a double click added the same point twice
    setMeasure((m) => {
      const out = m.length >= 2 && m[m.length - 1].distanceTo(m[m.length - 2]) < 0.05 ? m.slice(0, -1) : m
      if (out.length >= 3) setClosed(true)
      return out
    })
  }

  // area polygon (with live preview through the cursor point while open)
  const areaPts = measureMode === 'area'
    ? (closed || !probe || measure.length < 2 ? measure : [...measure, probe])
    : []
  const areaGeom = useMemo(() => (areaPts.length >= 3 ? polygonGeometry(areaPts) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [areaPts.map((p) => p.toArray().join()).join('|')])
  const area = areaPts.length >= 3 ? newell(areaPts).length() : 0
  const perimeter = areaPts.reduce((sum, p, i) =>
    sum + (i < areaPts.length - 1 || areaPts.length >= 3 ? p.distanceTo(areaPts[(i + 1) % areaPts.length]) : 0), 0)
  const areaCenter = areaPts.length
    ? areaPts.reduce((c, p) => c.add(p), new THREE.Vector3()).multiplyScalar(1 / areaPts.length)
    : null

  // labels
  const sel = floors.find((x) => x.id === view.selected)
  const labelFloors = view.mode === 'isolate' || view.mode === 'below' ? (sel ? [sel] : []) : []

  return (
    <>
      <primitive object={scene} onPointerMove={onMove} onPointerOut={() => { clearHover(); setProbe(null) }}
        onClick={onClick} onDoubleClick={onDoubleClick} />
      {hover && tool !== 'walk' && (
        <Html position={hover.point} style={{ pointerEvents: 'none' }} zIndexRange={[10, 0]}>
          <div className="tooltip"><b>{hover.name}</b><span>{hover.area.toFixed(1)} м²</span></div>
        </Html>
      )}
      {view.labels && labelFloors.flatMap((f) => f.rooms.filter((r) => r.name).map((r) => (
        <Html key={r.node} position={r.label_pos} center style={{ pointerEvents: 'none' }} zIndexRange={[5, 0]}>
          <div className="room-label">{r.name}</div>
        </Html>
      )))}
      {view.labels && view.mode === 'explode' && floors.map((f, i) => {
        const n = groups.get(f.id)
        if (!n) return null
        const b = new THREE.Box3().setFromObject(n)
        const y = f.elevation! + i * view.explode + 1.5     // target position (floors are animating)
        return (
          <Html key={f.id} position={[b.min.x - 1, y, (b.min.z + b.max.z) / 2]}
            center style={{ pointerEvents: 'none' }} zIndexRange={[5, 0]}>
            <div className="floor-label">{f.name}</div>
          </Html>
        )
      })}
      {measure.length > 0 && (
        <>
          {measure.map((p, i) => {
            // the first vertex of an open area contour is the "close here" target
            const closeTarget = measureMode === 'area' && !closed && i === 0 && measure.length >= 3
            return (
              <mesh key={i} position={p} renderOrder={11}>
                <sphereGeometry args={[closeTarget ? 0.16 : 0.08, 14, 14]} />
                <meshBasicMaterial color={closeTarget ? '#1c7ed6' : '#e03131'} depthTest={false} />
              </mesh>
            )
          })}
          {measureMode === 'length' && measure.length === 1 && probe && (
            <>
              <Line points={[measure[0], probe]} color="#e03131" lineWidth={1.5} dashed dashSize={0.2} gapSize={0.1} depthTest={false} />
              <Html position={probe} style={{ pointerEvents: 'none' }}>
                <div className="measure-label ghost">{measure[0].distanceTo(probe).toFixed(2)} м</div>
              </Html>
            </>
          )}
          {measureMode === 'area' && areaPts.length >= 2 && (
            <>
              <Line points={closed ? [...areaPts, areaPts[0]] : areaPts} color="#e03131" lineWidth={2} depthTest={false} />
              {areaGeom && (
                <mesh geometry={areaGeom} renderOrder={10}>
                  <meshBasicMaterial color="#fa5252" transparent opacity={closed ? 0.3 : 0.18}
                    side={THREE.DoubleSide} depthTest={false} />
                </mesh>
              )}
              {areaCenter && areaPts.length >= 3 && (
                <Html position={areaCenter} center style={{ pointerEvents: 'none' }}>
                  <div className={`measure-label${closed ? '' : ' ghost'}`}>
                    S {closed ? '=' : '≈'} {area.toFixed(2)} м²
                    <small>P = {perimeter.toFixed(2)} м · {areaPts.length} точ.</small>
                  </div>
                </Html>
              )}
            </>
          )}
          {measureMode === 'length' && measure.length === 2 && (
            <>
              <Line points={measure} color="#e03131" lineWidth={2} depthTest={false} />
              <Html position={measure[0].clone().add(measure[1]).multiplyScalar(0.5)} center style={{ pointerEvents: 'none' }}>
                <div className="measure-label">{measure[0].distanceTo(measure[1]).toFixed(2)} м</div>
              </Html>
            </>
          )}
        </>
      )}
    </>
  )
}

function Ground({ result }: { result: Result }) {
  const y = result.height_range[0] - 0.02
  return (
    <group position={[0, y, 0]}>
      <mesh rotation-x={-Math.PI / 2} receiveShadow>
        <planeGeometry args={[2000, 2000]} />
        <meshStandardMaterial color="#e9ecef" />
      </mesh>
      <gridHelper args={[400, 80, '#ced4da', '#dee2e6']} position={[0, 0.01, 0]} />
    </group>
  )
}

export default function Viewer(props: Props) {
  const { result, tool } = props
  const top = result.height_range[1]
  const ext = Math.max(60, top * 1.5)
  return (
    <Canvas shadows camera={{ fov: 50, position: [80, 60, 80] }} gl={{ antialias: true }}
      className={tool === 'measure' ? 'cursor-cross' : ''}>
      <color attach="background" args={['#f8f9fa']} />
      <hemisphereLight args={['#ffffff', '#b0a99f', 1.1]} />
      <directionalLight
        position={[ext * 0.6, ext, ext * 0.4]}
        intensity={1.6}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-ext}
        shadow-camera-right={ext}
        shadow-camera-top={ext}
        shadow-camera-bottom={-ext}
        shadow-camera-far={ext * 4}
        shadow-bias={-0.0005}
      />
      <Model {...props} />
      <Ground result={result} />
      {tool !== 'walk' && (
        <OrbitControls makeDefault enableDamping dampingFactor={0.1} maxPolarAngle={Math.PI * 0.495} />
      )}
    </Canvas>
  )
}
