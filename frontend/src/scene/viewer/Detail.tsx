import { useGLTF } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import type { FloorMeta, ViewSettings } from '../api'
import type { Display, NavMode } from '../state'
import type { Role } from './looks'
import type { SceneCtx } from './scene'

const FURNITURE = /furn|мебел|interior|интерьер|equip|оборуд|decor|декор/i
const FLOOR_NAME = /(?:^|[^a-z])(?:floor|level|этаж)[ _-]?(-?\d+)/i

export interface DetailInfo { floors: number; building: number; furniture: number }

/** Where a node of the detailed model goes: one of our floors (by the name
 * `floor_<level>` or, failing that, by the height of its middle) or the whole
 * building (facade pieces spanning several storeys). */
function assign(node: THREE.Object3D, floors: FloorMeta[], box: THREE.Box3): string | null {
  const m = FLOOR_NAME.exec(node.name)
  if (m) {
    const lvl = Number(m[1])
    return floors.find((f) => f.level === lvl)?.id ?? null
  }
  const h = box.max.y - box.min.y
  const typical = floors.length ? floors.reduce((s, f) => s + (f.height ?? 3), 0) / floors.length : 3
  if (h > typical * 1.5) return null
  const mid = (box.min.y + box.max.y) / 2
  let best: string | null = null
  for (const f of floors) if (mid >= f.elevation! - 0.3) best = f.id
  return best
}

/** Detailed model (facade, furniture...) uploaded to the job, aligned to the
 * generated one and split between its floors so that the floor switches,
 * "only active floor", explode and x-ray act on it too. */
export default function Detail({ ctx, url, cfg, floors, display, active, nav, onInfo }: {
  ctx: SceneCtx
  url: string
  cfg: NonNullable<ViewSettings['detail']>
  floors: FloorMeta[]
  display: Display
  active: string | null
  nav: NavMode
  onInfo?: (i: DetailInfo) => void
}) {
  const gltf = useGLTF(url)
  const building = useMemo(() => new THREE.Group(), [])
  const align = useMemo(() => {
    const [x, y, z] = cfg.offset ?? [0, 0, 0]
    return new THREE.Matrix4().compose(new THREE.Vector3(x, y, z),
      new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), ((cfg.rotation ?? 0) * Math.PI) / 180),
      new THREE.Vector3().setScalar(cfg.scale || 1))
  }, [cfg.offset, cfg.rotation, cfg.scale])

  useEffect(() => {
    const src = gltf.scene.clone(true)
    src.updateMatrixWorld(true)
    const placed: { node: THREE.Object3D; parent: THREE.Object3D; role: Role; floor: string | null }[] = []
    const info: DetailInfo = { floors: 0, building: 0, furniture: 0 }
    const visit = (node: THREE.Object3D, furniture: boolean) => {
      const furn = furniture || FURNITURE.test(node.name)
      const hasFloorName = FLOOR_NAME.test(node.name)
      const isLeaf = (node as THREE.Mesh).isMesh || node.children.length === 0
      if (!hasFloorName && !isLeaf && node.children.some((c) => c.children.length || (c as THREE.Mesh).isMesh)) {
        // a plain group: decide per child (a floor-named child may be deeper)
        const box = new THREE.Box3().setFromObject(node).applyMatrix4(align)
        const whole = assign(node, floors, box)
        const deep = node.children.some((c) => FLOOR_NAME.test(c.name))
        if (deep || whole == null) {
          for (const c of [...node.children]) visit(c, furn)
          return
        }
      }
      const box = new THREE.Box3().setFromObject(node).applyMatrix4(align)
      if (box.isEmpty()) return
      const fid = assign(node, floors, box)
      const world = align.clone().multiply(node.matrixWorld)
      const parent = fid ? ctx.groups.get(fid) ?? building : building
      node.removeFromParent()
      node.matrixAutoUpdate = false
      node.matrix.copy(world)                       // floor nodes sit at the origin (plus explode offset)
      node.traverse((o) => { o.userData.role = furn ? 'furniture' : 'detail' })
      parent.add(node)
      const role: Role = furn ? 'furniture' : 'detail'
      ctx.looks.add(node, fid, role)
      node.traverse((o) => {
        if ((o as THREE.Mesh).isMesh) {
          o.castShadow = true
          o.receiveShadow = true
          if (!furn) ctx.solids.push(o)
        }
      })
      placed.push({ node, parent, role, floor: fid })
      if (furn) info.furniture++
      else if (fid) info.floors++
      else info.building++
    }
    for (const c of [...src.children]) visit(c, false)
    onInfo?.(info)
    return () => {
      for (const p of placed) {
        ctx.looks.remove(p.node)
        p.parent.remove(p.node)
        const gone = new Set<THREE.Object3D>()
        p.node.traverse((o) => gone.add(o))
        ctx.solids = ctx.solids.filter((o) => !gone.has(o))
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gltf.scene, align, floors, ctx])

  // building-wide pieces (facade): shown with the whole building only
  useFrame(() => {
    building.visible = nav === 'walk' || (active == null && !display.explode)
    building.position.y = 0
  })
  return <primitive object={building} />
}
