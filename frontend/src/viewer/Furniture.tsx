import { Line, useGLTF } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { Component, Suspense, memo, useEffect, useMemo, useRef, type ReactNode } from 'react'
import * as THREE from 'three'
import type { FloorMeta, PlacedItem, XY } from '../api'
import { catalogItem, type CatalogItem } from '../furniture/catalog'
import { footprint, itemElev, itemSize, serviceZone, snapPose, type Coverage, type Issue, type PlanIndex, type Pose, type Quad } from '../furniture/geom'
import { Materials, buildModel } from '../furniture/models'
import type { Display, Projection } from '../state'
import FloorFollower from './FloorFollower'
import type { SceneCtx } from './scene'

export interface Placing {
  item: CatalogItem
  angle: number
  /** dragged out of the catalog (dropped on release) rather than click-to-place */
  drag: boolean
}

interface Props {
  ctx: SceneCtx
  floors: FloorMeta[]
  center: [number, number]
  items: PlacedItem[]
  visible: Set<string>
  display: Display
  proj: Projection
  editing: boolean
  /** the floor being furnished */
  active: string | null
  plan: PlanIndex | null
  issues: Map<string, Issue[]>
  selected: string | null
  placing: Placing | null
  showZones: boolean
  /** CCTV views of the cameras on the planned floor */
  coverage: Map<string, Coverage>
  showViews: boolean
  onSelect: (id: string | null) => void
  onPlace: (pose: Pose) => void
  onPlacing: (p: Placing | null) => void
  onMove: (id: string, pose: Pose, done: boolean) => void
  /** items of a proposal being looked at: outlined in its colour (new, changed, to be removed) */
  marks?: Map<string, ProposalMark>
}

/** outlines: a proposal's new, changed, to be removed items; `focus` — what an agent shows */
export type ProposalMark = 'new' | 'changed' | 'removed' | 'focus'
export const MARK_COLOR: Record<ProposalMark, string> = { new: '#2f9e44', changed: '#1c7ed6', removed: '#e03131', focus: '#f59f00' }

const CLICK_PX = 5
const Z_ZONE = 0.03, Z_LINE = 0.045
const BAD = new Set(['wall', 'overlap', 'door'])

/** Placed furniture and equipment: models on their floors, outlines and
 * service zones, and the editing interaction (drop from the catalog, drag
 * to move with wall snapping; Alt — no snapping). */
export default function Furniture(p: Props) {
  const { ctx, center, floors } = p
  const mats = useMemo(() => new Materials(), [])
  useEffect(() => () => mats.dispose(), [mats])
  useFrame(() => mats.setPlanes(ctx.activePlanes))
  const elev = useMemo(() => new Map(floors.map((f) => [f.id, f.elevation ?? 0])), [floors])
  const toLocal = (at: XY, y: number) => new THREE.Vector3(at[0] - center[0], y, -(at[1] - center[1]))
  const byFloor = useMemo(() => {
    const m = new Map<string, PlacedItem[]>()
    for (const it of p.items) m.set(it.floor, [...(m.get(it.floor) ?? []), it])
    return m
  }, [p.items])

  // ---- item groups (picking) and walk collisions
  const groups = useRef(new Map<string, THREE.Object3D>())
  useEffect(() => {
    const added: THREE.Object3D[] = []
    for (const it of p.items) {
      const c = catalogItem(it.item)
      const [, , h] = itemSize(it, c)
      if (h < 0.3 || itemElev(it, c) >= 1 || c.kind === 'zone') continue
      groups.current.get(it.id)?.traverse((o) => { if ((o as THREE.Mesh).isMesh) added.push(o) })
    }
    ctx.solids.push(...added)
    return () => {
      const gone = new Set(added)
      ctx.solids = ctx.solids.filter((o) => !gone.has(o))
    }
  }, [p.items, ctx])

  // ---- interaction
  const gl = useThree((s) => s.gl)
  const get = useThree((s) => s.get)
  const ghost = useRef<THREE.Group>(null)
  const ghostZone = useRef<THREE.Mesh>(null)
  const pose = useRef<Pose | null>(null)
  const drag = useRef<{ id: string; grab: XY; item: CatalogItem; size: [number, number, number]; angle: number; moved: boolean } | null>(null)
  const down = useRef<{ x: number; y: number; canvas: boolean } | null>(null)
  const latest = useRef(p)
  latest.current = p

  useEffect(() => {
    const el = gl.domElement
    const host = el.parentElement ?? el
    const ray = new THREE.Raycaster()
    const overCanvas = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom &&
        (document.elementFromPoint(e.clientX, e.clientY) === el || (e.target as Node) === el)
    }
    const aim = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), get().camera)
    }
    /** cursor on the active floor, plan coordinates */
    const floorPoint = (e: PointerEvent): XY | null => {
      const f = latest.current.active
      if (!f) return null
      aim(e)
      const y = (elev.get(f) ?? 0) + (ctx.offset.get(f) ?? 0)
      const hit = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -y), new THREE.Vector3())
      return hit ? [hit.x + center[0], -hit.z + center[1]] : null
    }
    const pickItem = (e: PointerEvent): string | null => {
      const s = latest.current
      aim(e)
      const objs = s.items.filter((it) => it.floor === s.active).map((it) => groups.current.get(it.id)).filter(Boolean) as THREE.Object3D[]
      const hit = ray.intersectObjects(objs, true)[0]
      for (let o: THREE.Object3D | null = hit?.object ?? null; o; o = o.parent) if (o.userData.furnId) return o.userData.furnId as string
      return null
    }
    const placePose = (e: PointerEvent, pl: Placing): Pose | null => {
      const q = floorPoint(e)
      return q ? snapPose(latest.current.plan, q, pl.angle, pl.item.w, pl.item.d, !!pl.item.wall && !e.altKey) : null
    }
    const showGhost = (ps: Pose | null) => {
      pose.current = ps
      const g = ghost.current
      if (!g) return
      g.visible = !!ps
      if (!ps) return
      const pl = latest.current.placing
      g.position.copy(toLocal(ps.at, (elev.get(latest.current.active!) ?? 0) + (pl?.item.elev ?? 0)))
      g.rotation.y = (ps.angle * Math.PI) / 180
    }

    const onDown = (e: PointerEvent) => {
      const s = latest.current
      if (!s.editing || e.button !== 0) return
      down.current = { x: e.clientX, y: e.clientY, canvas: overCanvas(e) }
      if (s.placing || !down.current.canvas) return
      const id = pickItem(e)
      if (!id) return
      const it = s.items.find((x) => x.id === id)!
      const q = floorPoint(e)
      e.stopPropagation()                       // no orbit / pan while dragging an item
      e.preventDefault()
      s.onSelect(id)
      if (q) {
        const c = catalogItem(it.item)
        drag.current = { id, grab: [q[0] - it.at[0], q[1] - it.at[1]], item: c, size: itemSize(it, c), angle: it.angle, moved: false }
      }
    }
    const onMove = (e: PointerEvent) => {
      const s = latest.current
      if (!s.editing) return
      if (drag.current) {
        const dr = drag.current
        const q = floorPoint(e)
        if (!q) return
        if (!dr.moved && down.current && Math.hypot(e.clientX - down.current.x, e.clientY - down.current.y) < CLICK_PX) return
        dr.moved = true
        const cur = s.items.find((x) => x.id === dr.id)
        const ps = snapPose(s.plan, [q[0] - dr.grab[0], q[1] - dr.grab[1]], cur?.angle ?? dr.angle, dr.size[0], dr.size[1], !!dr.item.wall && !e.altKey)
        s.onMove(dr.id, ps, false)
        return
      }
      if (s.placing) {
        showGhost(overCanvas(e) ? placePose(e, s.placing) : null)
        return
      }
      if (overCanvas(e)) el.style.cursor = pickItem(e) ? 'move' : ''
    }
    const onUp = (e: PointerEvent) => {
      const s = latest.current
      const d = down.current
      down.current = null
      if (!s.editing) return
      if (drag.current) {
        const dr = drag.current
        drag.current = null
        const cur = s.items.find((x) => x.id === dr.id)
        if (dr.moved && cur) s.onMove(dr.id, { at: cur.at, angle: cur.angle, wall: false }, true)
        return
      }
      const click = !!d && d.canvas && Math.hypot(e.clientX - d.x, e.clientY - d.y) < CLICK_PX
      if (s.placing) {
        const over = overCanvas(e)
        if (s.placing.drag && !over) {
          s.onPlacing({ ...s.placing, drag: false })      // released over the catalog: click-to-place
          return
        }
        if ((s.placing.drag && over) || click) {
          const ps = placePose(e, s.placing)
          if (ps) s.onPlace(ps)
          showGhost(null)
        }
        return
      }
      if (click && !pickItem(e)) s.onSelect(null)
    }
    host.addEventListener('pointerdown', onDown, true)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      host.removeEventListener('pointerdown', onDown, true)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      el.style.cursor = ''
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gl, get, ctx, elev, center])

  // the ghost follows the placing angle (R / Q / E) at once
  useEffect(() => {
    if (ghost.current && p.placing && pose.current && !pose.current.wall) ghost.current.rotation.y = (p.placing.angle * Math.PI) / 180
    if (!p.placing && ghost.current) ghost.current.visible = false
  }, [p.placing])

  const ghostModel = useMemo(() => {
    if (!p.placing) return null
    const c = p.placing.item
    return buildModel(c.kind, c.color, c.w, c.d, c.h, mats, true)
  }, [p.placing?.item, mats])        // eslint-disable-line react-hooks/exhaustive-deps

  const showAll = p.display.furniture || p.editing || !!p.marks?.size
  const outlines = p.editing || p.proj === '2d'
  return (
    <>
      {[...byFloor.entries()].map(([fid, list]) => p.visible.has(fid) && (
        <FloorFollower key={fid} ctx={ctx} floor={fid}>
          <group visible={showAll}>
            {list.map((it) => {
              const c = catalogItem(it.item)
              const [w, d, h] = itemSize(it, c)
              const iss = p.issues.get(it.id) ?? []
              const bad = iss.some((x) => BAD.has(x.kind))
              const sel = it.id === p.selected
              const editable = p.editing && fid === p.active
              const y0 = elev.get(fid) ?? 0
              const zone = (sel || p.showZones) && editable ? serviceZone(it.at, it.angle, w, d, c.clear ?? 0) : null
              const mark = p.marks?.get(it.id)
              return (
                <group key={it.id}>
                  <group position={toLocal(it.at, y0 + itemElev(it, c))} rotation-y={(it.angle * Math.PI) / 180}
                    userData={{ furnId: it.id, role: 'furniture' }}
                    ref={(g) => { if (g) groups.current.set(it.id, g); else groups.current.delete(it.id) }}>
                    <ItemModel c={c} w={w} d={d} h={h} mats={mats} />
                  </group>
                  {mark && <Outline quad={footprint(it.at, it.angle, w + 0.2, d + 0.2)} y={y0 + Z_LINE} center={center} color={MARK_COLOR[mark]} width={3} />}
                  {!mark && (outlines || sel || (editable && iss.length > 0)) && (
                    <Outline quad={footprint(it.at, it.angle, w, d)} y={y0 + Z_LINE} center={center}
                      color={bad && editable ? '#e03131' : iss.length && editable ? '#f08c00' : sel ? '#1c7ed6' : '#495057'}
                      width={sel ? 2.5 : editable && iss.length ? 2 : 1} />
                  )}
                  {zone && <ZoneQuad quad={zone} y={y0 + Z_ZONE} center={center} bad={iss.some((x) => x.kind === 'zone')} />}
                  {p.showViews && p.coverage.get(it.id) && (
                    <CameraView cov={p.coverage.get(it.id)!} y={y0} lensY={y0 + itemElev(it, c) + h / 2} center={center} selected={sel} />
                  )}
                </group>
              )
            })}
          </group>
        </FloorFollower>
      ))}
      {p.active && p.placing && (
        <FloorFollower ctx={ctx} floor={p.active}>
          <group ref={ghost} visible={false}>
            {ghostModel && <primitive object={ghostModel} />}
            {!!p.placing.item.clear && (
              <mesh ref={ghostZone} position={[0, Z_ZONE - (p.placing.item.elev ?? 0), p.placing.item.d / 2 + p.placing.item.clear / 2]} rotation-x={-Math.PI / 2} renderOrder={5}>
                <planeGeometry args={[p.placing.item.w, p.placing.item.clear]} />
                <meshBasicMaterial color="#40c057" transparent opacity={0.28} depthWrite={false} />
              </mesh>
            )}
          </group>
        </FloorFollower>
      )}
    </>
  )
}

const VIEW_COLOR = { cam: '#7048e8', radio: '#0ca678', detect: '#e03131' }

/** CCTV view: the seen floor (lighter up to the range, darker where faces
 * can be identified) and a see-through cone from the lens. */
function CameraView({ cov, y, lensY, center, selected }: { cov: Coverage; y: number; lensY: number; center: [number, number]; selected: boolean }) {
  const geos = useMemo(() => {
    const at = ([x, z]: XY, h: number): [number, number, number] => [x - center[0], h, -(z - center[1])]
    const fan = (apex: number[], arc: XY[], h: number) => {
      const v = [...apex, ...arc.flatMap((q) => at(q, h))]
      const idx: number[] = []
      const n = arc.length
      for (let i = 0; i < n - 1; i++) idx.push(0, i + 1, i + 2)
      if (cov.closed) idx.push(0, n, 1)
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3))
      g.setIndex(idx)
      return g
    }
    const floorY = y + Z_ZONE + 0.005
    return {
      full: fan(at(cov.apex, floorY), cov.arc, floorY),
      ident: fan(at(cov.apex, floorY + 0.002), cov.arcIdent, floorY + 0.002),
      cone: fan(at(cov.apex, lensY), cov.arc, floorY),
      edges: cov.closed ? [] : [cov.arc[0], cov.arc[cov.arc.length - 1]].map((q) => [at(cov.apex, lensY), at(q, floorY)]),
      rim: cov.arc.map((q) => at(q, floorY + 0.004)),
    }
  }, [cov, y, lensY, center])
  useEffect(() => () => { geos.full.dispose(); geos.ident.dispose(); geos.cone.dispose() }, [geos])
  const k = selected ? 1.6 : 1
  const hex = VIEW_COLOR[cov.kind ?? 'cam']
  const VIEW = new THREE.Color(hex)
  const cone = (cov.kind ?? 'cam') === 'cam'
  return (
    <group>
      <mesh geometry={geos.full} renderOrder={4}>
        <meshBasicMaterial color={VIEW} transparent opacity={0.16 * k} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
      <mesh geometry={geos.ident} renderOrder={4}>
        <meshBasicMaterial color={VIEW} transparent opacity={0.2 * k} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
      {cone && (
        <mesh geometry={geos.cone} renderOrder={3}>
          <meshBasicMaterial color={VIEW} transparent opacity={0.06 * k} depthWrite={false} side={THREE.DoubleSide} />
        </mesh>
      )}
      {geos.edges.map((e, i) => <Line key={i} points={e} color={hex} lineWidth={1} transparent opacity={0.6} />)}
      {geos.rim.length > 1 && <Line points={cov.closed ? [...geos.rim, geos.rim[0]] : geos.rim} color={hex} lineWidth={selected ? 2 : 1} transparent opacity={0.7} />}
    </group>
  )
}

function Outline({ quad, y, center, color, width }: { quad: Quad; y: number; center: [number, number]; color: string; width: number }) {
  const pts = [...quad, quad[0]].map(([x, z]) => [x - center[0], y, -(z - center[1])] as [number, number, number])
  return <Line points={pts} color={color} lineWidth={width} renderOrder={6} />
}

function ZoneQuad({ quad, y, center, bad }: { quad: Quad; y: number; center: [number, number]; bad: boolean }) {
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry()
    const v = quad.map(([x, z]) => [x - center[0], y, -(z - center[1])]).flat()
    g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3))
    g.setIndex([0, 1, 2, 0, 2, 3])
    return g
  }, [quad, y, center])
  useEffect(() => () => geo.dispose(), [geo])
  return (
    <mesh geometry={geo} renderOrder={5}>
      <meshBasicMaterial color={bad ? '#f08c00' : '#40c057'} transparent opacity={0.28} depthWrite={false} side={THREE.DoubleSide} />
    </mesh>
  )
}

/** Procedural model, replaced by the item's GLB once it has loaded. */
const ItemModel = memo(function ItemModel({ c, w, d, h, mats }: { c: CatalogItem; w: number; d: number; h: number; mats: Materials }) {
  const proc = useMemo(() => buildModel(c.kind, c.color, w, d, h, mats), [c.kind, c.color, w, d, h, mats])
  const fallback = <primitive object={proc} />
  if (!c.model) return fallback
  return (
    <Fallback fallback={fallback}>
      <Suspense fallback={fallback}>
        <GlbModel url={c.modelUrl ?? `/catalog/${c.model}`} rot={c.modelRot ?? 0} w={w} d={d} h={h} />
      </Suspense>
    </Fallback>
  )
})

function GlbModel({ url, rot, w, d, h }: { url: string; rot: number; w: number; d: number; h: number }) {
  const gltf = useGLTF(url)
  const obj = useMemo(() => {
    const inner = gltf.scene.clone(true)
    inner.rotation.y = (rot * Math.PI) / 180
    const wrap = new THREE.Group()
    wrap.add(inner)
    wrap.updateMatrixWorld(true)
    const box = new THREE.Box3().setFromObject(wrap)
    const s = box.getSize(new THREE.Vector3())
    const k = new THREE.Vector3(w / (s.x || 1), h / (s.y || 1), d / (s.z || 1))
    const c = box.getCenter(new THREE.Vector3())
    const out = new THREE.Group()
    wrap.position.set(-c.x, -box.min.y, -c.z)
    out.add(wrap)
    out.scale.copy(k)
    out.traverse((o) => { if ((o as THREE.Mesh).isMesh) { o.castShadow = true; o.receiveShadow = true } })
    return out
  }, [gltf.scene, rot, w, d, h])
  return <primitive object={obj} />
}

class Fallback extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}
