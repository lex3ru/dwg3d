/** Per-floor material registry: every floor gets its own copies of the
 * shared glTF materials so that transparency, highlighting, room-type colours
 * and facade lighting can differ per floor. Draw calls stay the same. */
import * as THREE from 'three'
import type { Display, FacadePreset } from '../state'

export const ACCENT = new THREE.Color('#1c7ed6')
const MUTED_TO = new THREE.Color('#f1f3f5')
const ROOM_DEFAULT = new THREE.Color('#f7f2e6')

export type Role = 'walls' | 'partitions' | 'columns' | 'slab' | 'stairs' | 'doors' | 'glass' | 'room' | 'roof'
  | 'edges' | 'detail' | 'furniture'

interface Entry {
  key: string
  floor: string | null        // null: roof / building-wide
  role: Role
  type?: string               // room type
  std: THREE.Material
  eco: THREE.Material         // simplified (Lambert / basic) variant
  meshes: THREE.Object3D[]
  base: { color: THREE.Color; opacity: number; transparent: boolean }
}

export function roleOf(o: THREE.Object3D): string | undefined {
  return (o.userData as { role?: string }).role
}

function toEco(m: THREE.Material): THREE.Material {
  if ((m as THREE.LineBasicMaterial).isLineBasicMaterial || (m as THREE.MeshBasicMaterial).isMeshBasicMaterial) return m.clone()
  const s = m as THREE.MeshStandardMaterial
  const l = new THREE.MeshLambertMaterial({
    color: s.color?.clone(), transparent: s.transparent, opacity: s.opacity, side: s.side,
    map: s.map ?? null, depthWrite: s.depthWrite, vertexColors: s.vertexColors,
    alphaTest: s.alphaTest,
  })
  l.name = `${m.name}_eco`
  return l
}

export interface LookParams {
  display: Display
  active: string | null
  eco: boolean
  edges: boolean
  night: number                     // 0 day .. 1 night (window glow strength)
  preset: FacadePreset
  typeColors: Record<string, string>
  planes: THREE.Plane[]
  time: number
  floorIndex: Map<string, number>
}

export class Looks {
  entries = new Map<string, Entry>()
  hovered: THREE.Mesh | null = null
  /** bumped on add / remove so that the looks are re-applied */
  version = 0
  hoverMat = new THREE.MeshStandardMaterial({ color: 0x4dabf7, emissive: 0x1c7ed6, emissiveIntensity: 0.35 })
  private eco = false

  /** Register every mesh / line of `root` belonging to `floor`. */
  add(root: THREE.Object3D, floor: string | null, roleOverride?: Role) {
    this.version++
    root.traverse((o) => {
      const mesh = o as THREE.Mesh
      if (!mesh.isMesh && !(o as THREE.LineSegments).isLineSegments) return
      const role = (roleOverride && roleOf(o) !== 'edges' ? roleOverride : (roleOf(o) ?? roleOverride ?? 'walls')) as Role
      const type = role === 'room' ? ((o.userData as { type?: string }).type ?? 'other') : undefined
      const orig = (o.userData.origMat ??= mesh.material) as THREE.Material | THREE.Material[]
      const src = Array.isArray(orig) ? orig[0] : orig
      const key = `${floor ?? '-'}|${role}|${type ?? ''}|${src.uuid}`
      let e = this.entries.get(key)
      if (!e) {
        const std = src.clone()
        const c = (std as THREE.MeshStandardMaterial).color?.clone() ?? new THREE.Color(1, 1, 1)
        e = {
          key, floor, role, type, std, eco: toEco(std), meshes: [],
          base: { color: c, opacity: std.opacity, transparent: std.transparent },
        }
        this.entries.set(key, e)
      }
      e.meshes.push(o)
      mesh.material = this.eco ? e.eco : e.std
    })
  }

  remove(root: THREE.Object3D) {
    this.version++
    const gone = new Set<THREE.Object3D>()
    root.traverse((o) => gone.add(o))
    for (const [k, e] of this.entries) {
      e.meshes = e.meshes.filter((m) => !gone.has(m))
      if (!e.meshes.length) {
        e.std.dispose()
        e.eco.dispose()
        this.entries.delete(k)
      }
    }
  }

  setHover(mesh: THREE.Mesh | null) {
    if (this.hovered === mesh) return
    const prev = this.hovered
    this.hovered = mesh
    if (prev) this.restore(prev)
    if (mesh) mesh.material = this.hoverMat
  }

  private restore(o: THREE.Object3D) {
    for (const e of this.entries.values()) {
      if (e.meshes.includes(o)) {
        (o as THREE.Mesh).material = this.eco ? e.eco : e.std
        return
      }
    }
  }

  apply(p: LookParams) {
    const d = p.display
    this.eco = p.eco
    const facadeOn = p.night > 0.01
    for (const e of this.entries.values()) {
      const dim = d.highlight && p.active != null && e.floor != null && e.floor !== p.active
      const isActive = d.highlight && p.active != null && e.floor === p.active
      for (const m of [e.std, e.eco]) {
        const mat = m as THREE.MeshStandardMaterial & THREE.LineBasicMaterial
        const color = e.base.color.clone()
        let opacity = e.base.opacity
        let transparent = e.base.transparent
        let depthWrite = true
        if (e.role === 'room') {
          if (d.roomColors && e.type) color.set(p.typeColors[e.type] ?? p.typeColors.other ?? ROOM_DEFAULT)
          else color.copy(ROOM_DEFAULT)
        }
        if (d.xray && (e.role === 'walls' || e.role === 'partitions' || e.role === 'columns' || e.role === 'detail'
          || e.role === 'roof' || e.role === 'doors')) {
          transparent = true
          opacity = Math.min(opacity, e.role === 'roof' ? 0.12 : 0.25)
          depthWrite = false
        }
        if (e.role === 'edges') {
          const f = e.floor ? p.floorIndex.get(e.floor) ?? 0 : 0
          if (facadeOn && p.preset.contourIntensity > 0) {
            const c = new THREE.Color(p.preset.animate
              ? p.preset.windows[(f + Math.floor(p.time / 1.5)) % p.preset.windows.length] : p.preset.contour)
            color.lerp(c, Math.min(1, p.night * p.preset.contourIntensity))
          }
          if (isActive) color.copy(ACCENT)
          transparent = true
          opacity = dim ? 0.15 : isActive ? 0.9 : 0.55
        }
        if (dim) {
          color.lerp(MUTED_TO, 0.62)
          if (e.role === 'glass') opacity *= 0.5
        }
        mat.color?.copy(color)
        mat.opacity = opacity
        if (mat.transparent !== transparent) {
          mat.transparent = transparent
          mat.needsUpdate = true
        }
        mat.depthWrite = e.role === 'glass' ? false : depthWrite
        // emissive: active-floor tint, lit windows and interiors at night
        if ('emissive' in mat && mat.emissive) {
          const em = new THREE.Color(0, 0, 0)
          let ei = 0
          if (isActive && e.role !== 'glass') { em.copy(ACCENT); ei = 0.1 }
          if (facadeOn && e.role === 'glass' && !dim) {
            const f = e.floor ? p.floorIndex.get(e.floor) ?? 0 : 0
            const k = p.preset.animate ? Math.floor(p.time / 1.5) : 0
            em.set(p.preset.windows[(f + k) % p.preset.windows.length])
            ei = p.preset.intensity * p.night
            mat.opacity = Math.max(opacity, 0.55 * p.night + opacity * (1 - p.night))
          }
          if (facadeOn && e.role === 'room' && !dim) { em.set('#ffe3b3'); ei = 0.35 * p.night }
          mat.emissive.copy(em)
          mat.emissiveIntensity = ei
        }
        if (mat.clippingPlanes !== p.planes) {
          mat.clippingPlanes = p.planes
          mat.clipShadows = true
          mat.needsUpdate = true
        }
      }
      for (const o of e.meshes) {
        if (e.role === 'edges') o.visible = p.edges
        if (o !== this.hovered) (o as THREE.Mesh).material = p.eco ? e.eco : e.std
      }
    }
    if (this.hoverMat.clippingPlanes !== p.planes) {
      this.hoverMat.clippingPlanes = p.planes
      this.hoverMat.needsUpdate = true
    }
  }

  dispose() {
    for (const e of this.entries.values()) {
      e.std.dispose()
      e.eco.dispose()
    }
    this.entries.clear()
    this.hoverMat.dispose()
  }
}
