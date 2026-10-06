import { useGLTF } from '@react-three/drei'
import { Component, Suspense, useEffect, useMemo, type ReactNode } from 'react'
import * as THREE from 'three'
import type { PlacedItem, XY } from '../api'
import { catalogItem, type CatalogItem } from '../furniture/catalog'
import { footprint, itemElev, itemSize } from '../furniture/geom'
import { buildModel, type Materials } from '../furniture/models'
import type { SceneCtx } from './scene'

/**
 * Many placed items drawn at once: every mesh of their models becomes one instance of an
 * InstancedMesh per geometry and material, so a floor of two thousand items is a few dozen draws,
 * not tens of thousands. An instance knows its item (`userData.furnIds[instanceId]`) for picking;
 * the meshes of items one can bump into while walking are the scene's solids.
 */

interface Part { geometry: THREE.BufferGeometry; material: THREE.Material | THREE.Material[]; matrix: THREE.Matrix4; shadow: boolean }

/** The meshes of a model with their matrices relative to its root. */
function parts(root: THREE.Object3D): Part[] {
  root.updateMatrixWorld(true)
  const inv = root.matrixWorld.clone().invert()
  const out: Part[] = []
  root.traverse((o) => {
    const m = o as THREE.Mesh
    if (m.isMesh) out.push({ geometry: m.geometry, material: m.material, matrix: inv.clone().multiply(m.matrixWorld), shadow: m.castShadow })
  })
  return out
}

const uuid = (m: THREE.Material | THREE.Material[]) => (Array.isArray(m) ? m.map((x) => x.uuid).join(',') : m.uuid)
/** what one walking bumps into: tall enough, standing on the floor */
const solid = (it: PlacedItem, c: CatalogItem) => itemSize(it, c)[2] >= 0.3 && itemElev(it, c) < 1 && c.kind !== 'zone'

function instances(entries: { id: string; matrix: THREE.Matrix4; parts: Part[]; solid: boolean }[]): THREE.InstancedMesh[] {
  const buckets = new Map<string, { part: Part; solid: boolean; mats: THREE.Matrix4[]; ids: string[] }>()
  for (const e of entries) {
    for (const p of e.parts) {
      const key = `${p.geometry.uuid}|${uuid(p.material)}|${e.solid}`
      let b = buckets.get(key)
      if (!b) buckets.set(key, (b = { part: p, solid: e.solid, mats: [], ids: [] }))
      b.mats.push(e.matrix.clone().multiply(p.matrix))
      b.ids.push(e.id)
    }
  }
  return [...buckets.values()].map(({ part, solid: s, mats, ids }) => {
    const im = new THREE.InstancedMesh(part.geometry, part.material, mats.length)
    mats.forEach((m, i) => im.setMatrixAt(i, m))
    im.instanceMatrix.needsUpdate = true
    im.castShadow = part.shadow
    im.receiveShadow = true
    im.userData = { furnIds: ids, role: 'furniture', solid: s }
    im.computeBoundingBox()
    im.computeBoundingSphere()
    return im
  })
}

function placement(it: PlacedItem, c: CatalogItem, y0: number, center: [number, number]): THREE.Matrix4 {
  const pos = new THREE.Vector3(it.at[0] - center[0], y0 + itemElev(it, c), -(it.at[1] - center[1]))
  const rot = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), (it.angle * Math.PI) / 180)
  return new THREE.Matrix4().compose(pos, rot, new THREE.Vector3(1, 1, 1))
}

interface Props {
  ctx: SceneCtx
  items: PlacedItem[]
  y0: number
  center: [number, number]
  mats: Materials
  /** the instanced meshes of this set, for picking (null: gone) */
  register: (key: string, meshes: THREE.InstancedMesh[] | null) => void
}

/** The items of one floor: procedural models at once; an item type with a GLB — as soon as it has loaded. */
export function FurnitureInstances(p: Props) {
  const byModel = useMemo(() => {
    const plain: PlacedItem[] = []
    const glb = new Map<string, PlacedItem[]>()
    for (const it of p.items) {
      const c = catalogItem(it.item)
      if (c.model) glb.set(c.id, [...(glb.get(c.id) ?? []), it])
      else plain.push(it)
    }
    return { plain, glb }
  }, [p.items])
  return (
    <>
      <Procedural {...p} key="plain" items={byModel.plain} name="plain" />
      {[...byModel.glb].map(([cid, list]) => {
        const fallback = <Procedural {...p} items={list} name={`proc:${cid}`} />
        return (
          <Fallback key={cid} fallback={fallback}>
            <Suspense fallback={fallback}><Glb {...p} items={list} name={`glb:${cid}`} /></Suspense>
          </Fallback>
        )
      })}
    </>
  )
}

function Procedural({ ctx, items, y0, center, mats, register, name }: Props & { name: string }) {
  const meshes = useMemo(() => {
    const models = new Map<string, Part[]>()
    return instances(items.map((it) => {
      const c = catalogItem(it.item)
      const [w, d, h] = itemSize(it, c)
      const key = `${c.id}|${w}|${d}|${h}`
      let ps = models.get(key)
      if (!ps) models.set(key, (ps = parts(buildModel(c.kind, c.color, w, d, h, mats))))
      return { id: it.id, matrix: placement(it, c, y0, center), parts: ps, solid: solid(it, c) }
    }))
  }, [items, y0, center, mats])
  return <Meshes ctx={ctx} meshes={meshes} register={register} name={name} />
}

function Glb({ ctx, items, y0, center, register, name }: Props & { name: string }) {
  const c = catalogItem(items[0].item)
  const gltf = useGLTF(c.modelUrl ?? `/catalog/${c.model}`)
  const meshes = useMemo(() => {
    const models = new Map<string, Part[]>()
    return instances(items.map((it) => {
      const [w, d, h] = itemSize(it, c)
      const key = `${w}|${d}|${h}`
      let ps = models.get(key)
      if (!ps) models.set(key, (ps = parts(fitted(gltf.scene, c.modelRot ?? 0, w, d, h))))
      return { id: it.id, matrix: placement(it, c, y0, center), parts: ps, solid: solid(it, c) }
    }))
  }, [items, y0, center, gltf.scene, c])
  return <Meshes ctx={ctx} meshes={meshes} register={register} name={name} />
}

/** A GLB scene turned and scaled to the item's size, standing on its origin. */
function fitted(scene: THREE.Object3D, rot: number, w: number, d: number, h: number): THREE.Group {
  const inner = scene.clone(true)
  inner.rotation.y = (rot * Math.PI) / 180
  const wrap = new THREE.Group()
  wrap.add(inner)
  wrap.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(wrap)
  const s = box.getSize(new THREE.Vector3())
  const c = box.getCenter(new THREE.Vector3())
  const out = new THREE.Group()
  wrap.position.set(-c.x, -box.min.y, -c.z)
  out.add(wrap)
  out.scale.set(w / (s.x || 1), h / (s.y || 1), d / (s.z || 1))
  out.traverse((o) => { if ((o as THREE.Mesh).isMesh) { o.castShadow = true; o.receiveShadow = true } })
  return out
}

function Meshes({ ctx, meshes, register, name }: { ctx: SceneCtx; meshes: THREE.InstancedMesh[]; register: Props['register']; name: string }) {
  const group = useMemo(() => {
    const g = new THREE.Group()
    meshes.forEach((m) => g.add(m))
    return g
  }, [meshes])
  useEffect(() => {
    register(name, meshes)
    const walls = meshes.filter((m) => m.userData.solid)
    ctx.solids.push(...walls)
    return () => {
      register(name, null)
      const gone = new Set<THREE.Object3D>(walls)
      ctx.solids = ctx.solids.filter((o) => !gone.has(o))
      meshes.forEach((m) => m.dispose())
    }
  }, [meshes, ctx, register, name])
  return <primitive object={group} />
}

/** Thin outlines of many items as one set of segments (2D and editing). */
export function Outlines({ items, y, center, color = '#495057' }: { items: PlacedItem[]; y: number; center: [number, number]; color?: string }) {
  const geo = useMemo(() => {
    const v: number[] = []
    const at = ([x, z]: XY) => [x - center[0], y, -(z - center[1])]
    for (const it of items) {
      const [w, d] = itemSize(it, catalogItem(it.item))
      const q = footprint(it.at, it.angle, w, d)
      for (let i = 0; i < 4; i++) v.push(...at(q[i]), ...at(q[(i + 1) % 4]))
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3))
    return g
  }, [items, y, center])
  useEffect(() => () => geo.dispose(), [geo])
  return (
    <lineSegments geometry={geo} renderOrder={6}>
      <lineBasicMaterial color={color} />
    </lineSegments>
  )
}

class Fallback extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}
