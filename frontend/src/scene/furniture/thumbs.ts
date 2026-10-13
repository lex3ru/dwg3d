/** Pictures of catalog items for the picker: the item's own model (its GLB, or
 * the procedural one while there is none or it fails) drawn three-quarters
 * from the front and above, on a transparent ground. One small offscreen
 * renderer draws them one at a time, giving the page its turn between them; a picture is kept as a
 * data URL for the page's life, by everything that changes the look. */
import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import type { CatalogItem } from './catalog'
import { buildModel, Materials } from './models'

const PX = 128
/** the eye looks at the front (+Z) from the left of it and from above */
const VIEW = new THREE.Vector3(-0.75, 0.7, 1).normalize()
const FOV = 30

const done = new Map<string, string>()
const waiting = new Map<string, { c: CatalogItem; listeners: Set<(url: string) => void> }>()
let busy = false

let ctx: { renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; mats: Materials } | null = null
let gltf: GLTFLoader | null = null

const keyOf = (c: CatalogItem) => [c.id, c.kind, c.color ?? '', c.w, c.d, c.h, c.modelUrl ?? c.model ?? '', c.modelRot ?? 0].join('|')

function setup() {
  if (ctx) return ctx
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })
  renderer.setPixelRatio(1)
  renderer.setSize(PX, PX, false)
  renderer.setClearColor(0x000000, 0)
  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f99, 1.6))
  const sun = new THREE.DirectionalLight(0xffffff, 2.2)
  sun.position.set(-2, 4, 3)
  scene.add(sun)
  const camera = new THREE.PerspectiveCamera(FOV, 1, 0.01, 100)
  ctx = { renderer, scene, camera, mats: new Materials() }
  return ctx
}

function loader() {
  if (!gltf) {
    gltf = new GLTFLoader()
    // the same decoder the viewer's useGLTF takes, so a compressed upload draws here as it does there
    const draco = new DRACOLoader().setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.5/')
    gltf.setDRACOLoader(draco)
  }
  return gltf
}

/** The GLB turned and scaled to the item's size, standing on its origin (as the viewer fits it). */
async function glbModel(c: CatalogItem): Promise<THREE.Object3D> {
  const g = await loader().loadAsync(c.modelUrl ?? `/catalog/${c.model}`)
  const inner = g.scene
  inner.rotation.y = ((c.modelRot ?? 0) * Math.PI) / 180
  const wrap = new THREE.Group()
  wrap.add(inner)
  wrap.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(wrap)
  const s = box.getSize(new THREE.Vector3())
  const ctr = box.getCenter(new THREE.Vector3())
  wrap.position.set(-ctr.x, -box.min.y, -ctr.z)
  const out = new THREE.Group()
  out.add(wrap)
  out.scale.set(c.w / (s.x || 1), c.h / (s.y || 1), c.d / (s.z || 1))
  return out
}

function dispose(o: THREE.Object3D) {
  o.traverse((x) => {
    const m = x as THREE.Mesh
    if (!m.isMesh) return
    m.geometry.dispose()
    for (const mat of Array.isArray(m.material) ? m.material : [m.material]) {
      for (const v of Object.values(mat)) if (v instanceof THREE.Texture) v.dispose()
      mat.dispose()
    }
  })
}

async function draw(c: CatalogItem): Promise<string> {
  const { renderer, scene, camera, mats } = setup()
  let obj: THREE.Object3D | null = null
  let own = false
  if (c.model) {
    try { obj = await glbModel(c); own = true } catch { obj = null }
  }
  // a zone is a mark on the floor: a few centimetres tall, so it reads as a disc and not as a coin on edge
  obj ??= buildModel(c.kind, c.color, c.w, c.d, c.kind === 'zone' ? Math.min(c.h, 0.03) : c.h, mats)
  scene.add(obj)
  obj.updateMatrixWorld(true)
  const sphere = new THREE.Box3().setFromObject(obj).getBoundingSphere(new THREE.Sphere())
  const r = Math.max(sphere.radius, 0.05)
  const dist = (r / Math.sin(THREE.MathUtils.degToRad(FOV / 2))) * 0.92
  camera.position.copy(sphere.center).addScaledVector(VIEW, dist)
  camera.near = dist / 20
  camera.far = dist * 4
  camera.updateProjectionMatrix()
  camera.lookAt(sphere.center)
  renderer.render(scene, camera)
  const url = renderer.domElement.toDataURL('image/png')
  scene.remove(obj)
  // the procedural model shares its geometries and materials with every other one: only a GLB is freed
  if (own) dispose(obj)
  return url
}

async function pump() {
  if (busy) return
  busy = true
  try {
    let since = performance.now()
    while (waiting.size) {
      const [key, job] = waiting.entries().next().value!
      let url = ''
      try { url = await draw(job.c) } catch (e) { console.warn('Не удалось нарисовать превью', job.c.name, e) }
      waiting.delete(key)
      done.set(key, url)
      job.listeners.forEach((f) => f(url))
      // the page gets its turn every few pictures, so a long catalog does not hold the dock up
      // (a timer, not a frame: frames stop in a hidden tab, and the pictures would wait for it to show)
      if (performance.now() - since > 12) {
        await new Promise((ok) => setTimeout(ok, 0))
        since = performance.now()
      }
    }
  } finally {
    busy = false
  }
}

/** The picture of an item: a data URL, '' when it could not be drawn, null until it is drawn. */
export function useThumb(c: CatalogItem): string | null {
  const key = keyOf(c)
  const [, redraw] = useState(0)
  // the item as last rendered; `key` says when its picture changes
  const item = useRef(c)
  useEffect(() => { item.current = c })
  useEffect(() => {
    if (done.has(key)) return
    let job = waiting.get(key)
    if (!job) waiting.set(key, (job = { c: item.current, listeners: new Set() }))
    const f = () => redraw((n) => n + 1)
    job.listeners.add(f)
    void pump()
    return () => { job.listeners.delete(f) }
  }, [key])
  return done.get(key) ?? null
}
