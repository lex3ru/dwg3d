/** Procedural low-poly models of catalog items, built from boxes, cylinders
 * and spheres to the item's size. Local frame: X — width (centred), Y — up
 * from the floor, Z — depth, the front at +Z (back to the wall at -Z). */
import * as THREE from 'three'

const BOX = new THREE.BoxGeometry(1, 1, 1)
const CYL = new THREE.CylinderGeometry(0.5, 0.5, 1, 20)
const SPH = new THREE.SphereGeometry(0.5, 16, 12)
/** rings with a bore along Z (CT gantry, MRI magnet), by size */
const RINGS = new Map<string, THREE.BufferGeometry>()
function ringGeometry(r: number, bore: number, len: number): THREE.BufferGeometry {
  const key = `${r.toFixed(3)}|${bore.toFixed(3)}|${len.toFixed(3)}`
  let g = RINGS.get(key)
  if (!g) {
    const shape = new THREE.Shape().absarc(0, 0, r, 0, Math.PI * 2, false)
    shape.holes.push(new THREE.Path().absarc(0, 0, bore, 0, Math.PI * 2, true))
    g = new THREE.ExtrudeGeometry(shape, { depth: len, bevelEnabled: false, curveSegments: 40 })
    g.translate(0, 0, -len / 2)
    RINGS.set(key, g)
  }
  return g
}

const METAL = '#ced4da'
const DARK = '#495057'
const BODY = '#f8f9fa'
const GLASS = 'glass'
const SCREEN = '#212529'

/** Shared materials (by colour; ghosts are see-through). */
export class Materials {
  private map = new Map<string, THREE.MeshStandardMaterial>()
  all: THREE.MeshStandardMaterial[] = []

  get(color: string, ghost = false): THREE.MeshStandardMaterial {
    const key = `${color}|${ghost}`
    let m = this.map.get(key)
    if (!m) {
      const glass = color === GLASS
      m = new THREE.MeshStandardMaterial({
        color: glass ? '#a5d8ff' : color, roughness: glass ? 0.1 : 0.65, metalness: color === METAL ? 0.4 : 0.05,
        transparent: glass || ghost, opacity: ghost ? 0.45 : glass ? 0.35 : 1, depthWrite: !ghost && !glass,
      })
      this.map.set(key, m)
      this.all.push(m)
    }
    return m
  }

  setPlanes(planes: THREE.Plane[]) {
    for (const m of this.all) {
      if (m.clippingPlanes !== planes) {
        m.clippingPlanes = planes
        m.needsUpdate = true
      }
    }
  }

  dispose() {
    this.all.forEach((m) => m.dispose())
    this.map.clear()
    this.all = []
  }
}

class Builder {
  group = new THREE.Group()
  private mats: Materials
  private ghost: boolean
  private main: string
  constructor(mats: Materials, ghost: boolean, main: string) {
    this.mats = mats
    this.ghost = ghost
    this.main = main
  }
  private add(g: THREE.BufferGeometry, color: string, pos: [number, number, number], scale: [number, number, number], rot?: THREE.Euler) {
    const m = new THREE.Mesh(g, this.mats.get(color === 'main' ? this.main : color, this.ghost))
    m.position.set(...pos)
    m.scale.set(...scale)
    if (rot) m.rotation.copy(rot)
    m.castShadow = !this.ghost
    m.receiveShadow = true
    this.group.add(m)
    return m
  }
  /** axis-aligned box by its extents */
  box(x0: number, x1: number, y0: number, y1: number, z0: number, z1: number, c = 'main') {
    return this.add(BOX, c, [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2], [Math.abs(x1 - x0), Math.abs(y1 - y0), Math.abs(z1 - z0)])
  }
  /** box by centre and size, tilted about X (rad) */
  tilt(cx: number, cy: number, cz: number, sx: number, sy: number, sz: number, rx: number, c = 'main') {
    return this.add(BOX, c, [cx, cy, cz], [sx, sy, sz], new THREE.Euler(rx, 0, 0))
  }
  /** vertical cylinder */
  cyl(x: number, z: number, y0: number, y1: number, r: number, c = 'main') {
    return this.add(CYL, c, [x, (y0 + y1) / 2, z], [2 * r, y1 - y0, 2 * r])
  }
  /** wheel: cylinder with its axis along X */
  wheel(x: number, y: number, z: number, r: number, t: number, c = DARK) {
    return this.add(CYL, c, [x, y, z], [2 * r, t, 2 * r], new THREE.Euler(0, 0, Math.PI / 2))
  }
  /** ring of outer radius r with a bore, axis along Z, centred at (x, y, z) */
  ring(x: number, y: number, z: number, r: number, bore: number, len: number, c = 'main') {
    return this.add(ringGeometry(r, bore, len), c, [x, y, z], [1, 1, 1])
  }
  sph(x: number, y: number, z: number, r: number, c = 'main', sy = 1) {
    return this.add(SPH, c, [x, y, z], [2 * r, 2 * r * sy, 2 * r])
  }
  legs(w: number, d: number, h: number, t = 0.04, inset = 0.03, c = METAL) {
    const x = w / 2 - inset - t / 2, z = d / 2 - inset - t / 2
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) this.box(sx * x - t / 2, sx * x + t / 2, 0, h, sz * z - t / 2, sz * z + t / 2, c)
  }
  casters(w: number, d: number, r = 0.04, inset = 0.06) {
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) this.wheel(sx * (w / 2 - inset), r, sz * (d / 2 - inset), r, 0.03)
  }
}

type Gen = (b: Builder, w: number, d: number, h: number) => void

const X0 = (w: number) => -w / 2
const seatRow = (b: Builder, x0: number, x1: number, d: number, h: number) => {
  b.box(x0 + 0.02, x1 - 0.02, 0.4, 0.46, -d / 2 + 0.08, d / 2, 'main')
  b.tilt((x0 + x1) / 2, 0.46 + (h - 0.46) / 2, -d / 2 + 0.06, x1 - x0 - 0.06, h - 0.46, 0.05, -0.12, 'main')
}

const GEN: Record<string, Gen> = {
  table(b, w, d, h) {
    b.box(X0(w), w / 2, h - 0.03, h, -d / 2, d / 2)
    b.legs(w, d, h - 0.03, 0.05, 0.05, DARK)
  },
  desk(b, w, d, h) {
    b.box(X0(w), w / 2, h - 0.03, h, -d / 2, d / 2)
    b.box(X0(w), X0(w) + 0.03, 0, h - 0.03, -d / 2, d / 2 - 0.05)
    b.box(w / 2 - 0.03, w / 2, 0, h - 0.03, -d / 2, d / 2 - 0.05)
    b.box(X0(w) + 0.03, X0(w) + 0.45, 0.05, h - 0.03, -d / 2, d / 2 - 0.08, BODY)   // pedestal
    b.box(X0(w) + 0.03, w / 2 - 0.03, 0.3, h - 0.03, -d / 2, -d / 2 + 0.02)
  },
  desk_pc(b, w, d, h) {
    GEN.desk(b, w, d, h)
    b.box(-0.05, 0.05, h, h + 0.12, -d / 2 + 0.12, -d / 2 + 0.2, DARK)
    b.box(-0.3, 0.3, h + 0.1, h + 0.45, -d / 2 + 0.14, -d / 2 + 0.17, SCREEN)
    b.box(-0.22, 0.22, h, h + 0.02, -0.05, 0.1, DARK)
  },
  chair(b, w, d, h) {
    b.legs(w - 0.04, d - 0.04, 0.45, 0.025, 0.02)
    b.box(X0(w) + 0.02, w / 2 - 0.02, 0.43, 0.48, -d / 2 + 0.02, d / 2 - 0.02)
    b.tilt(0, 0.48 + (h - 0.48) / 2, -d / 2 + 0.04, w - 0.06, h - 0.48, 0.04, -0.1)
  },
  chair_office(b, w, d, h) {
    const r = Math.min(w, d) / 2
    b.box(-r, r, 0.03, 0.06, -0.03, 0.03, DARK)
    b.box(-0.03, 0.03, 0.03, 0.06, -r, r, DARK)
    b.cyl(0, 0, 0.06, 0.45, 0.03, METAL)
    b.box(-r + 0.03, r - 0.03, 0.43, 0.5, -r + 0.05, r - 0.03)
    b.tilt(0, 0.5 + (h - 0.5) / 2, -r + 0.05, w - 0.12, h - 0.52, 0.06, -0.12)
  },
  stool(b, w, d) {
    const r = Math.min(w, d) / 2
    b.cyl(0, 0, 0.02, 0.06, r * 0.9, DARK)
    b.cyl(0, 0, 0.06, 0.52, 0.03, METAL)
    b.cyl(0, 0, 0.52, 0.6, r * 0.75)
  },
  seats(b, w, d, h) {
    const n = Math.max(1, Math.round(w / 0.56))
    const s = w / n
    b.box(X0(w), w / 2, 0.36, 0.4, -0.05, 0.05, METAL)
    for (const x of [X0(w) + 0.1, w / 2 - 0.1]) b.box(x - 0.03, x + 0.03, 0, 0.36, -d / 2 + 0.1, d / 2 - 0.1, METAL)
    for (let i = 0; i < n; i++) seatRow(b, X0(w) + i * s, X0(w) + (i + 1) * s, d, h)
  },
  sofa(b, w, d, h) {
    b.box(X0(w), w / 2, 0.08, 0.42, -d / 2, d / 2)
    b.box(X0(w), w / 2, 0.42, h, -d / 2, -d / 2 + 0.18)
    b.box(X0(w), X0(w) + 0.12, 0.42, 0.62, -d / 2, d / 2)
    b.box(w / 2 - 0.12, w / 2, 0.42, 0.62, -d / 2, d / 2)
    b.box(X0(w) + 0.05, w / 2 - 0.05, 0, 0.08, -d / 2 + 0.05, d / 2 - 0.05, DARK)
  },
  couch(b, w, d, h) {
    b.legs(w, d, h - 0.1, 0.035, 0.04)
    b.box(X0(w) + 0.02, w / 2 - 0.02, h - 0.14, h - 0.1, -d / 2 + 0.02, d / 2 - 0.02, METAL)
    b.box(X0(w), w / 2 - 0.55, h - 0.1, h, -d / 2, d / 2)
    b.tilt(w / 2 - 0.3, h + 0.04, 0, 0.55, 0.1, d, 0, 'main').rotation.set(0, 0, 0.3)
  },
  armchair_med(b, w, d, h) {
    b.box(X0(w) + 0.08, w / 2 - 0.08, 0, 0.1, -d / 2 + 0.1, d / 2 - 0.1, DARK)
    b.cyl(0, 0, 0.1, 0.4, 0.05, METAL)
    b.box(X0(w) + 0.08, w / 2 - 0.08, 0.4, 0.5, -d / 2 + 0.1, d / 2 - 0.05)
    b.tilt(0, 0.5 + (h - 0.5) / 2, -d / 2 + 0.1, w - 0.2, h - 0.5, 0.1, -0.25)
    b.box(w / 2 - 0.1, w / 2, 0.62, 0.7, -d / 2 + 0.1, d / 2, BODY)
    b.box(X0(w), X0(w) + 0.1, 0.62, 0.7, -d / 2 + 0.1, d / 2, BODY)
  },
  exam_chair(b, w, d, h) {
    b.box(X0(w) + 0.1, w / 2 - 0.1, 0, 0.12, -d / 2 + 0.2, d / 2 - 0.3, BODY)
    b.box(-0.1, 0.1, 0.12, 0.6, -0.15, 0.15, BODY)
    b.box(X0(w) + 0.05, w / 2 - 0.05, 0.6, 0.72, -0.2, 0.3)
    b.tilt(0, 0.95, -0.45, w - 0.1, 0.1, 0.6, 0.9)
    for (const s of [-1, 1]) {
      b.box(s * (w / 2 - 0.08) - 0.02, s * (w / 2 - 0.08) + 0.02, 0.6, h - 0.1, d / 2 - 0.25, d / 2 - 0.2, METAL)
      b.box(s * (w / 2 - 0.08) - 0.07, s * (w / 2 - 0.08) + 0.07, h - 0.15, h - 0.05, d / 2 - 0.3, d / 2 - 0.05)
    }
  },
  bed(b, w, d, h) {
    b.casters(w, d, 0.06, 0.1)
    b.box(X0(w) + 0.05, w / 2 - 0.05, 0.12, 0.45, -d / 2 + 0.05, d / 2 - 0.05, METAL)
    b.box(X0(w) + 0.05, w / 2 - 0.05, 0.45, 0.6, -d / 2 + 0.06, d / 2 - 0.06, '#e7f5ff')
    b.tilt(0, 0.68, -d / 2 + 0.4, w - 0.12, 0.14, 0.62, -0.35, '#e7f5ff')
    b.box(X0(w), w / 2, 0.1, h, -d / 2, -d / 2 + 0.05, 'main')
    b.box(X0(w), w / 2, 0.1, h - 0.15, d / 2 - 0.05, d / 2, 'main')
    for (const s of [-1, 1]) b.box(s * (w / 2 - 0.02) - 0.02, s * (w / 2 - 0.02) + 0.02, 0.6, 0.78, -d / 2 + 0.3, 0.2, METAL)
  },
  nightstand(b, w, d, h) {
    b.casters(w, d, 0.03, 0.05)
    b.box(X0(w), w / 2, 0.06, h, -d / 2, d / 2)
    b.box(X0(w) + 0.03, w / 2 - 0.03, h - 0.2, h - 0.04, d / 2, d / 2 + 0.01, METAL)
  },
  gurney(b, w, d, h) {
    b.casters(w, d, 0.07, 0.1)
    for (const z of [-d / 2 + 0.2, d / 2 - 0.2]) b.box(-0.03, 0.03, 0.14, h - 0.1, z - 0.03, z + 0.03, METAL)
    b.box(X0(w), w / 2, h - 0.12, h - 0.08, -d / 2, d / 2, METAL)
    b.box(X0(w) + 0.04, w / 2 - 0.04, h - 0.08, h, -d / 2 + 0.04, d / 2 - 0.04, '#74c0fc')
  },
  wheelchair(b, w, d, h) {
    for (const s of [-1, 1]) {
      b.wheel(s * (w / 2 - 0.02), 0.3, -0.1, 0.3, 0.03)
      b.wheel(s * (w / 2 - 0.12), 0.07, d / 2 - 0.15, 0.07, 0.03)
      b.box(s * (w / 2 - 0.1) - 0.015, s * (w / 2 - 0.1) + 0.015, 0.2, h, -d / 2 + 0.25, -d / 2 + 0.28, METAL)
    }
    b.box(X0(w) + 0.1, w / 2 - 0.1, 0.46, 0.5, -d / 2 + 0.28, d / 2 - 0.35)
    b.box(X0(w) + 0.1, w / 2 - 0.1, 0.5, h - 0.05, -d / 2 + 0.26, -d / 2 + 0.28)
    b.box(X0(w) + 0.14, w / 2 - 0.14, 0.12, 0.15, d / 2 - 0.22, d / 2 - 0.05, METAL)
  },
  cabinet(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, -d / 2, d / 2)
    b.box(-0.004, 0.004, 0.05, h - 0.05, d / 2, d / 2 + 0.004, DARK)
    for (const s of [-1, 1]) b.box(s * 0.04 - 0.01, s * 0.04 + 0.01, h / 2 - 0.1, h / 2 + 0.1, d / 2, d / 2 + 0.03, METAL)
  },
  lockers(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, -d / 2, d / 2)
    for (const x of [-w / 4, w / 4]) for (const y of [h / 4, (3 * h) / 4]) {
      b.box(x - w / 4 + 0.02, x + w / 4 - 0.02, y - h / 4 + 0.02, y + h / 4 - 0.02, d / 2, d / 2 + 0.01, BODY)
    }
  },
  cabinet_glass(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, -d / 2, -d / 2 + 0.02, BODY)
    for (const s of [-1, 1]) b.box(s * w / 2 - 0.02, s * w / 2 + 0.02, 0, h, -d / 2, d / 2, BODY)
    b.box(X0(w), w / 2, 0, 0.1, -d / 2, d / 2, BODY)
    b.box(X0(w), w / 2, h - 0.03, h, -d / 2, d / 2, BODY)
    for (const y of [0.55, 0.95, 1.35]) b.box(X0(w) + 0.02, w / 2 - 0.02, y, y + 0.01, -d / 2, d / 2 - 0.02, GLASS)
    b.box(X0(w) + 0.02, w / 2 - 0.02, 0.1, h - 0.03, d / 2 - 0.01, d / 2, GLASS)
  },
  rack(b, w, d, h) {
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) b.box(sx * w / 2 - 0.02 * sx, sx * w / 2, 0, h, sz * d / 2 - 0.02 * sz, sz * d / 2, METAL)
    const n = Math.max(2, Math.round(h / 0.4))
    for (let i = 0; i < n; i++) {
      const y = 0.08 + (i * (h - 0.1)) / (n - 1)
      b.box(X0(w), w / 2, y - 0.02, y, -d / 2, d / 2, 'main')
    }
  },
  server(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, -d / 2, d / 2, '#343a40')
    b.box(X0(w) + 0.03, w / 2 - 0.03, 0.08, h - 0.08, d / 2, d / 2 + 0.01, '#212529')
    for (let y = 0.2; y < h - 0.2; y += 0.18) b.box(X0(w) + 0.06, w / 2 - 0.06, y, y + 0.08, d / 2 + 0.01, d / 2 + 0.015, '#51cf66')
  },
  reception(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, d / 2 - 0.1, d / 2, 'main')                   // front (visitors)
    b.box(X0(w), w / 2, h - 0.03, h, d / 2 - 0.35, d / 2 + 0.05, BODY)       // high counter
    b.box(X0(w), w / 2, 0.72, 0.75, -d / 2, d / 2 - 0.1, BODY)               // work top
    for (const s of [-1, 1]) b.box(s * w / 2 - 0.04 * s, s * w / 2, 0, h, -d / 2, d / 2, 'main')
    b.box(-0.3, 0.3, 0.75, 1.1, -d / 2 + 0.25, -d / 2 + 0.28, SCREEN)
  },
  counter(b, w, d, h) {
    b.box(X0(w), w / 2, 0.08, h - 0.04, -d / 2, d / 2 - 0.03, BODY)
    b.box(X0(w) + 0.02, w / 2 - 0.02, 0, 0.08, -d / 2, d / 2 - 0.08, DARK)
    b.box(X0(w), w / 2, h - 0.04, h, -d / 2, d / 2, '#dee2e6')
    const n = Math.max(1, Math.round(w / 0.5))
    for (let i = 1; i < n; i++) b.box(X0(w) + (i * w) / n - 0.003, X0(w) + (i * w) / n + 0.003, 0.1, h - 0.06, d / 2 - 0.03, d / 2 - 0.02, METAL)
  },
  counter_sink(b, w, d, h) {
    GEN.counter(b, w, d, h)
    b.box(w / 4 - 0.2, w / 4 + 0.2, h - 0.001, h + 0.002, -0.15, 0.15, METAL)
    b.cyl(w / 4, -d / 2 + 0.07, h, h + 0.3, 0.015, METAL)
  },
  sink(b, w, d, h) {
    b.cyl(0, -d / 2 + 0.12, 0, h - 0.15, 0.08, BODY)
    b.box(X0(w), w / 2, h - 0.18, h, -d / 2, d / 2, BODY)
    b.box(X0(w) + 0.06, w / 2 - 0.06, h - 0.005, h + 0.001, -d / 2 + 0.12, d / 2 - 0.05, '#dee2e6')
    b.cyl(0, -d / 2 + 0.06, h, h + 0.2, 0.015, METAL)
  },
  toilet(b, w, d, h) {
    b.box(X0(w), w / 2, 0.4, h, -d / 2, -d / 2 + 0.18, BODY)
    b.cyl(0, 0.05, 0, 0.3, 0.13, BODY)
    b.cyl(0, 0.05, 0.3, 0.42, Math.min(w / 2, 0.2), BODY)
  },
  cart(b, w, d, h) {
    b.casters(w, d, 0.04, 0.05)
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) b.box(sx * (w / 2 - 0.04) - 0.012, sx * (w / 2 - 0.04) + 0.012, 0.08, h, sz * (d / 2 - 0.04) - 0.012, sz * (d / 2 - 0.04) + 0.012, METAL)
    for (const y of [0.2, h / 2 + 0.1, h - 0.02]) b.box(X0(w) + 0.02, w / 2 - 0.02, y - 0.02, y, -d / 2 + 0.02, d / 2 - 0.02, 'main')
  },
  iv(b, w, d, h) {
    const r = Math.min(w, d) / 2 - 0.03
    b.box(-r, r, 0.04, 0.07, -0.02, 0.02, METAL)
    b.box(-0.02, 0.02, 0.04, 0.07, -r, r, METAL)
    b.cyl(0, 0, 0.07, h, 0.013, METAL)
    b.box(-0.15, 0.15, h - 0.04, h - 0.02, -0.01, 0.01, METAL)
    b.box(0.1, 0.18, h - 0.3, h - 0.06, -0.03, 0.03, GLASS)
  },
  folding(b, w, d, h) {
    const n = 3, s = w / n
    for (let i = 0; i < n; i++) {
      const x0 = X0(w) + i * s, z = (i % 2 ? 1 : -1) * (d / 2 - 0.1)
      b.box(x0 + 0.01, x0 + s - 0.01, 0.2, h, z - 0.01, z + 0.01, 'main')
      for (const x of [x0 + 0.02, x0 + s - 0.02]) b.box(x - 0.012, x + 0.012, 0, h, z - 0.012, z + 0.012, METAL)
    }
  },
  cooler(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h - 0.4, -d / 2, d / 2, BODY)
    b.cyl(0, 0, h - 0.4, h, Math.min(w, d) / 2 - 0.03, GLASS)
    b.box(-0.05, 0.05, h - 0.7, h - 0.62, d / 2, d / 2 + 0.03, '#1c7ed6')
  },
  plant(b, w, d, h) {
    const r = Math.min(w, d) / 2
    b.cyl(0, 0, 0, 0.35, r * 0.6, '#868e96')
    b.sph(0, 0.35 + (h - 0.35) * 0.45, 0, r, '#40c057', ((h - 0.35) / (2 * r)) * 0.9)
  },
  kiosk(b, w, d, h) {
    b.box(X0(w), w / 2, 0, 0.05, -d / 2, d / 2, DARK)
    b.box(-w / 4, w / 4, 0.05, h - 0.4, -0.1, 0.1, BODY)
    b.tilt(0, h - 0.2, 0, w, 0.4, 0.1, -0.35, BODY)
    b.tilt(0, h - 0.2, 0.052, w - 0.06, 0.34, 0.01, -0.35, SCREEN)
  },
  screen_tv(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, -d / 2, d / 2, SCREEN)
  },
  stadiometer(b, w, d, h) {
    b.box(X0(w), w / 2, 0, 0.06, -d / 2, d / 2, BODY)
    b.box(-0.03, 0.03, 0.06, h, -d / 2, -d / 2 + 0.04, METAL)
    b.box(-0.12, 0.12, 1.7, 1.72, -d / 2 + 0.04, -d / 2 + 0.25, METAL)
  },
  bin(b, w, d, h) {
    const r = Math.min(w, d) / 2
    b.cyl(0, 0, 0, h - 0.04, r * 0.9)
    b.cyl(0, 0, h - 0.04, h, r)
  },
  fridge(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, -d / 2, d / 2, BODY)
    b.box(X0(w) + 0.04, w / 2 - 0.04, 0.1, h - 0.1, d / 2, d / 2 + 0.01, GLASS)
    b.box(w / 2 - 0.08, w / 2 - 0.05, h / 2 - 0.2, h / 2 + 0.2, d / 2, d / 2 + 0.04, METAL)
  },
  device(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, -d / 2, d / 2, 'main')
    b.box(X0(w) + 0.05, w / 2 - 0.05, h * 0.55, h * 0.85, d / 2, d / 2 + 0.01, DARK)
  },
  device_wall(b, w, d, h) {
    GEN.device(b, w, d, h)
  },
  panel(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, -d / 2, d / 2, '#adb5bd')
    b.box(X0(w) + 0.02, w / 2 - 0.02, 0.02, h - 0.02, d / 2, d / 2 + 0.005, '#ced4da')
    b.box(w / 2 - 0.08, w / 2 - 0.05, h / 2 - 0.05, h / 2 + 0.05, d / 2, d / 2 + 0.03, DARK)
  },
  ac(b, w, d, h) {
    b.box(X0(w), w / 2, 0, h, -d / 2, d / 2, BODY)
    b.box(X0(w) + 0.05, w / 2 - 0.05, 0.02, 0.06, d / 2 - 0.02, d / 2 + 0.005, DARK)
  },
  radiator(b, w, d, h) {
    const n = Math.max(3, Math.round(w / 0.08))
    for (let i = 0; i < n; i++) {
      const x = X0(w) + (i + 0.5) * (w / n)
      b.box(x - w / n / 2 + 0.005, x + w / n / 2 - 0.005, 0, h, -d / 2, d / 2, BODY)
    }
  },
  extinguisher(b, w, d, h) {
    const r = Math.min(w, d) / 2
    b.cyl(0, 0, 0, h - 0.1, r * 0.75, '#e03131')
    b.cyl(0, 0, h - 0.1, h, r * 0.3, DARK)
  },
  ultrasound(b, w, d, h) {
    b.casters(w, d, 0.05, 0.08)
    b.box(X0(w) + 0.05, w / 2 - 0.05, 0.1, 0.8, -d / 2 + 0.2, d / 2 - 0.2, BODY)
    b.box(X0(w), w / 2, 0.8, 0.9, -d / 2 + 0.05, d / 2, BODY)
    b.box(X0(w) + 0.1, w / 2 - 0.1, 0.9, 0.92, 0, d / 2 - 0.1, DARK)
    b.cyl(0, -d / 2 + 0.2, 0.9, h - 0.3, 0.025, METAL)
    b.tilt(0, h - 0.18, -d / 2 + 0.22, w, 0.36, 0.05, -0.15, SCREEN)
  },
  xray(b, w, d, h) {
    b.box(-0.3, 0.3, 0, 0.6, -0.25, 0.25, BODY)
    b.box(X0(w) + 0.2, w / 2 - 0.2, 0.6, 0.72, -d / 2 + 0.15, d / 2 - 0.15, 'main')
    b.box(X0(w) + 0.15, X0(w) + 0.35, 0, h, -d / 2, -d / 2 + 0.2, METAL)
    b.box(X0(w) + 0.25, 0.1, h - 0.15, h - 0.05, -d / 2 + 0.05, -d / 2 + 0.15, METAL)
    b.box(-0.1, 0.25, h - 0.55, h - 0.15, -0.2, 0.2, '#e9ecef')
  },
  ct(b, w, d, h) {
    // gantry at the back, the patient table runs out of the bore to the front (+Z)
    const gd = 0.9, gz = -d / 2 + gd / 2 + 0.05
    const R = Math.min(w / 2, h / 2) - 0.02, cy = h / 2
    b.ring(0, cy, gz, R, 0.38, gd, BODY)
    b.ring(0, cy, gz + gd / 2 + 0.005, R - 0.04, R - 0.12, 0.01, 'main')      // accent band on the face
    b.ring(0, cy, gz, 0.4, 0.37, gd + 0.02, '#dee2e6')                        // bore lining
    b.box(-R * 0.8, R * 0.8, 0, cy - R * 0.6, gz - gd / 2, gz + gd / 2, BODY) // plinth
    b.box(-w / 2, w / 2, 0, 0.04, gz - gd / 2 - 0.05, gz + gd / 2 + 0.05, '#adb5bd')
    const tz0 = gz + gd / 2 + 0.1
    b.box(-0.25, 0.25, 0, 0.62, tz0 + 0.3, d / 2 - 0.4, BODY)                   // table pedestal
    b.box(-0.27, 0.27, 0.62, 0.9, tz0 + 0.1, d / 2 - 0.1, BODY)
    b.box(-0.24, 0.24, 0.9, 0.97, gz - 0.2, d / 2, '#dee2e6')                   // cradle into the bore
    b.box(-0.22, 0.22, 0.97, 1.02, tz0, d / 2 - 0.05, '#74c0fc')              // mattress
  },
  mri(b, w, d, h) {
    // magnet with a long bore at the back, table in front (+Z)
    const md = Math.min(1.9, d * 0.42), mz = -d / 2 + md / 2 + 0.05
    const R = Math.min(w / 2, h / 2) - 0.02, cy = h / 2
    b.box(-w / 2 + 0.05, w / 2 - 0.05, 0, cy, mz - md / 2, mz + md / 2, BODY)   // housing, lower half
    b.ring(0, cy, mz, R, 0.36, md, BODY)
    b.ring(0, cy, mz + md / 2 + 0.005, 0.5, 0.37, 0.02, 'main')                 // bore flare
    b.ring(0, cy, mz, 0.38, 0.35, md + 0.03, '#dee2e6')
    b.box(-w / 2, w / 2, 0, 0.04, mz - md / 2 - 0.05, mz + md / 2 + 0.05, '#adb5bd')
    const tz0 = mz + md / 2 + 0.05
    b.box(-0.3, 0.3, 0, 0.7, tz0 + 0.2, d / 2 - 0.2, BODY)                      // table
    b.box(-0.3, 0.3, 0.7, 0.9, tz0, d / 2, BODY)
    b.box(-0.25, 0.25, 0.9, 0.95, mz, d / 2 - 0.05, '#dee2e6')                  // cradle into the bore
    b.box(-0.22, 0.22, 0.95, 1.0, tz0, d / 2 - 0.1, '#74c0fc')
  },
  hood(b, w, d, h) {
    b.box(X0(w), w / 2, 0, 0.8, -d / 2, d / 2, '#dee2e6')
    b.box(X0(w), w / 2, 0.8, h, -d / 2, -d / 2 + 0.1, BODY)
    for (const s of [-1, 1]) b.box(s * w / 2 - 0.04 * s, s * w / 2, 0.8, h, -d / 2, d / 2 - 0.1, BODY)
    b.box(X0(w), w / 2, h - 0.35, h, -d / 2, d / 2, BODY)
    b.tilt(0, 1.25, d / 2 - 0.1, w - 0.08, 0.7, 0.01, 0.12, GLASS)
  },
  dental(b, w, d, h) {
    // patient chair along Z (head at the back), unit arm on the left, lamp over the head
    b.box(-0.25, 0.25, 0, 0.1, -0.4, 0.5, BODY)
    b.box(-0.12, 0.12, 0.1, 0.45, -0.1, 0.2, BODY)
    b.box(-0.3, 0.3, 0.45, 0.58, -0.15, 0.45, 'main')
    b.tilt(0, 0.62, 0.72, 0.5, 0.1, 0.55, -0.35, 'main')
    b.tilt(0, 0.8, -0.55, 0.52, 0.1, 0.8, 0.55, 'main')
    b.box(-0.12, 0.12, 1.02, 1.1, -0.95, -0.8, 'main')
    b.box(X0(w), X0(w) + 0.35, 0, 0.95, -0.2, 0.2, BODY)                          // spittoon block
    b.cyl(X0(w) + 0.18, 0.05, 0.95, 1.02, 0.1, '#dee2e6')
    b.box(w / 2 - 0.5, w / 2 - 0.05, 0.9, 0.95, 0.0, 0.4, BODY)                    // doctor's tray
    b.box(w / 2 - 0.3, w / 2 - 0.25, 0.1, 0.9, 0.15, 0.2, METAL)
    b.cyl(X0(w) + 0.18, -d / 2 + 0.15, 0, h - 0.1, 0.03, METAL)                    // lamp post
    b.box(X0(w) + 0.18, 0.05, h - 0.1, h - 0.05, -d / 2 + 0.12, -d / 2 + 0.18, METAL)
    b.box(-0.15, 0.15, h - 0.2, h - 0.08, -d / 2 + 0.05, -d / 2 + 0.3, '#fff3bf')
  },
  cam_dome(b, w, d, h) {
    const r = Math.min(w, d) / 2
    b.cyl(0, 0, h - 0.02, h, r, BODY)
    b.sph(0, h - 0.02, 0, r * 0.8, SCREEN, 0.9)
  },
  cam_fisheye(b, w, d, h) {
    const r = Math.min(w, d) / 2
    b.cyl(0, 0, 0.02, h, r, BODY)
    b.sph(0, 0.02, 0, r * 0.45, SCREEN, 0.6)
  },
  cam_bullet(b, w, d, h) {
    b.box(-0.04, 0.04, h / 2 - 0.04, h / 2 + 0.04, -d / 2, -d / 2 + 0.02, BODY)          // wall plate
    b.box(-0.012, 0.012, h / 2 - 0.012, h / 2 + 0.012, -d / 2, -d / 2 + 0.08, METAL)    // arm
    b.tilt(0, h / 2, 0.04, w, h * 0.75, d - 0.1, 0.2, BODY)                            // body, tilted down
    b.tilt(0, h / 2 - 0.035, d / 2 - 0.03, w * 0.7, h * 0.5, 0.01, 0.2, SCREEN)          // lens
  },
  cam_ptz(b, w, d, h) {
    const r = Math.min(w, d) / 2
    b.cyl(0, 0, h - 0.03, h, r * 0.6, BODY)
    b.cyl(0, 0, h * 0.45, h - 0.03, r * 0.7, BODY)
    b.sph(0, h * 0.45, 0, r * 0.75, SCREEN, 0.9)
  },
  zone(b, w, d, h) {
    b.cyl(0, 0, 0, Math.max(0.005, h), Math.min(w, d) / 2 - 0.05, 'main')
  },
}

export const KINDS = Object.keys(GEN)

/** Model of an item scaled to its size; unknown kinds fall back to a box. */
export function buildModel(kind: string, color: string | undefined, w: number, d: number, h: number, mats: Materials, ghost = false): THREE.Group {
  const b = new Builder(mats, ghost, color ?? BODY)
  ;(GEN[kind] ?? GEN.device)(b, w, d, h)
  return b.group
}

/** Procedural model kinds a catalog item can use (`kind`). */
export const MODEL_KINDS = Object.keys(GEN).sort()
