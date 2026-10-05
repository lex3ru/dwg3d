/** Mutable scene context shared by the components inside the Canvas
 * (building, camera rig, walk / fly controls, labels, detail model). */
import * as THREE from 'three'
import type { Entrance, FloorMeta, Result } from '../api'
import type { Display, NavMode } from '../state'
import { Looks, roleOf, type LookParams } from './looks'

const SOLID = new Set(['walls', 'partitions', 'columns', 'glass', 'doors'])
const WALKABLE = new Set(['slab', 'stairs', 'room'])
const VIEW_DIR = new THREE.Vector3(0.62, 0.42, 0.66).normalize()

export interface CameraApi {
  zoom: (dir: 1 | -1) => void
  fit: () => void
  flyToFloor: (id: string | null) => void
  flyToPoint: (p: THREE.Vector3, radius?: number) => void
}

export class SceneCtx {
  floors: FloorMeta[] = []                      // ascending elevation
  groups = new Map<string, THREE.Object3D>()    // floor id -> glTF node
  roof: THREE.Object3D | null = null
  /** meshes that block walking (walls, partitions, columns, glass, doors, detail) */
  solids: THREE.Object3D[] = []
  /** meshes you can stand on (slabs, stairs, room floors, ground) */
  walkables: THREE.Object3D[] = []
  looks = new Looks()
  /** current and target vertical offsets of floors (explode) */
  offset = new Map<string, number>()
  target = new Map<string, number>()
  roofOffset = { now: 0, target: 0 }
  anim: { t0: number; dur: number; from: Map<string, number>; roofFrom: number } | null = null
  groundY = 0
  bbox = new THREE.Box3()                        // whole model at rest
  floorBox = new Map<string, THREE.Box3>()       // per floor, at rest
  api: CameraApi | null = null
  /** section planes (constants follow the sliders; the array identity only
   * changes when a section is switched on / off, which recompiles shaders) */
  planes = { h: new THREE.Plane(new THREE.Vector3(0, -1, 0), 0), v: new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0) }
  activePlanes: THREE.Plane[] = []
  private lookKey = ''

  setCuts(h: { on: boolean; y: number }, v: { on: boolean; x: number }): THREE.Plane[] {
    this.planes.h.constant = h.y
    this.planes.v.constant = v.x
    const want = [...(h.on ? [this.planes.h] : []), ...(v.on ? [this.planes.v] : [])]
    if (want.length !== this.activePlanes.length || want.some((p, i) => p !== this.activePlanes[i])) this.activePlanes = want
    return this.activePlanes
  }

  /** Index the freshly loaded model: floor nodes, roof, collision meshes, per-floor materials. */
  prepare(scene: THREE.Object3D, floors: FloorMeta[], roofNode: string | null): THREE.Object3D {
    this.floors = floors
    this.groups.clear()
    this.solids = []
    this.walkables = this.walkables.filter((o) => roleOf(o) === 'ground')
    this.looks.dispose()
    this.looks = new Looks()
    this.lookKey = ''
    this.bbox.setFromObject(scene)
    for (const f of floors) {
      const node = scene.getObjectByName(f.node)
      if (!node) continue
      node.userData.floorId = f.id
      this.groups.set(f.id, node)
      this.looks.add(node, f.id)
      this.floorBox.set(f.id, new THREE.Box3().setFromObject(node))
      if (!this.offset.has(f.id)) this.offset.set(f.id, 0)
    }
    this.roof = roofNode ? scene.getObjectByName(roofNode) ?? null : null
    if (this.roof) this.looks.add(this.roof, null, 'roof')
    scene.traverse((o) => {
      const role = roleOf(o) ?? ''
      if ((o as THREE.Mesh).isMesh) {
        o.castShadow = role !== 'glass' && role !== 'room'
        o.receiveShadow = true
        if (SOLID.has(role)) this.solids.push(o)
        if (WALKABLE.has(role)) this.walkables.push(o)
      }
      if ((o as THREE.LineSegments).isLineSegments) o.raycast = () => {}
    })
    return scene
  }

  /** Start the (eased) explode animation towards the given floor offsets. */
  explode(on: boolean, gap: number, dur: number) {
    const from = new Map(this.offset)
    this.floors.forEach((f, i) => this.target.set(f.id, on ? i * gap : 0))
    this.roofOffset.target = on ? this.floors.length * gap : 0
    this.anim = { t0: performance.now(), dur, from, roofFrom: this.roofOffset.now }
  }

  /** Per frame: explode animation, floor / layer visibility, roof. */
  tick(visible: Set<string>, display: Display, roofVisible: boolean) {
    const a = this.anim
    if (a) {
      const t = Math.min(1, (performance.now() - a.t0) / a.dur)
      const k = easeInOut(t)
      for (const f of this.floors) {
        const from = a.from.get(f.id) ?? 0
        this.offset.set(f.id, from + ((this.target.get(f.id) ?? 0) - from) * k)
      }
      this.roofOffset.now = a.roofFrom + (this.roofOffset.target - a.roofFrom) * k
      if (t >= 1) this.anim = null
    }
    for (const f of this.floors) {
      const node = this.groups.get(f.id)
      if (!node) continue
      node.visible = visible.has(f.id)
      node.position.y = this.offset.get(f.id) ?? 0
      node.traverse((o) => {
        const role = roleOf(o)
        if (role === 'room') o.visible = display.rooms
        else if (role === 'glass') o.visible = display.glass
        else if (role === 'furniture') o.visible = display.furniture
      })
    }
    if (this.roof) {
      this.roof.visible = roofVisible
      this.roof.position.y = this.roofOffset.now
    }
  }

  /** Re-apply materials when anything they depend on changed. */
  applyLooks(p: LookParams, key: string) {
    const k = `${this.looks.version}|${key}`
    if (k === this.lookKey) return
    this.lookKey = k
    this.looks.apply(p)
  }

  setGround(y: number) {
    this.groundY = y
  }

  floorIndex(id: string): number {
    return this.floors.findIndex((f) => f.id === id)
  }

  /** Bounding box of what should be framed, at the *target* explode offsets. */
  frameBox(active: string | null, display: Display, only = false): THREE.Box3 {
    const box = new THREE.Box3()
    const fl = active ? this.floors.find((f) => f.id === active) : null
    for (const f of this.floors) {
      const b = this.floorBox.get(f.id)
      if (!b) continue
      if (fl && (only || display.onlyActive || !display.explode) && f.id !== fl.id) continue
      box.union(b.clone().translate(new THREE.Vector3(0, this.target.get(f.id) ?? 0, 0)))
    }
    if (!fl && this.roof && display.roof) {
      box.union(new THREE.Box3().setFromObject(this.roof).translate(new THREE.Vector3(0, this.roofOffset.target - this.roofOffset.now, 0)))
    }
    return box.isEmpty() ? this.bbox.clone() : box
  }
}


export function isVisible(o: THREE.Object3D | null): boolean {
  for (let p = o; p; p = p.parent) if (!p.visible) return false
  return true
}

export function floorOf(o: THREE.Object3D | null): string | null {
  for (let p = o; p; p = p.parent) {
    const id = (p.userData as { id?: string; floorId?: string }).floorId
    if (id) return id
  }
  return null
}

export const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)

/** Which floors are shown for the current view. */
export function visibleFloors(floors: FloorMeta[], display: Display, active: string | null, nav: NavMode): Set<string> {
  const act = floors.find((f) => f.id === active)
  if (nav === 'walk' || !act) return new Set(floors.map((f) => f.id))
  if (display.onlyActive) return new Set([act.id])
  if (display.explode) return new Set(floors.map((f) => f.id))
  return new Set(floors.filter((f) => f.elevation! <= act.elevation!).map((f) => f.id))
}

export function typeLabel(result: Result, type?: string): string {
  if (!type || type === 'other') return ''
  return result.room_types?.find((t) => t.type === type)?.label ?? ''
}

/** Camera position that frames `box` looking along `dir`. */
export function framePose(box: THREE.Box3, fovDeg: number, aspect: number, dir = VIEW_DIR, margin = 1.08) {
  const target = box.getCenter(new THREE.Vector3())
  const radius = box.getSize(new THREE.Vector3()).length() / 2
  const vfov = (fovDeg * Math.PI) / 180
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect)
  const dist = (radius / Math.sin(Math.min(vfov, hfov) / 2)) * margin
  return { target, pos: target.clone().addScaledVector(dir, Math.max(dist, 4)) }
}

export const DEFAULT_VIEW_DIR = VIEW_DIR

/** Start pose of a walk: outside the main entrance, facing the door. */
export function entrancePose(e: Entrance, eye: number) {
  const [x, y, z] = e.pos
  const out = new THREE.Vector3(e.dir[0], 0, e.dir[1]).normalize()
  const pos = new THREE.Vector3(x, y + eye, z).addScaledVector(out, 3.5)
  const look = new THREE.Vector3(x, y + eye, z)
  return { pos, look }
}

/** DOM layer for drei <Html> overlays. It lives outside the Canvas, so
 * unmounting the scene (switching buildings, quality change) never races
 * with the overlays' own React roots. */
export const htmlLayer: { current: HTMLElement | null } = { current: null }

/** Floors whose floor is seen (not covered by a floor above or the roof):
 * room labels and pins are shown only there. */
export function openFloors(floors: FloorMeta[], visible: Set<string>, o: {
  exploded: boolean; xray: boolean; topDown: boolean; walking: boolean; roofShown: boolean
}): Set<string> {
  const out = new Set<string>()
  if (o.walking) return out
  const vis = floors.filter((f) => visible.has(f.id))
  if (o.exploded || o.xray || o.topDown) vis.forEach((f) => out.add(f.id))
  else if (!o.roofShown && vis.length) out.add(vis.reduce((a, b) => (b.elevation! > a.elevation! ? b : a)).id)
  return out
}
