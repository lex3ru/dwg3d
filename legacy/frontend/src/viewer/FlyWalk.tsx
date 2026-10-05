import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Speeds } from '../state'
import { isVisible, type SceneCtx } from './scene'

const FLY_BASE = 10     // m/s at x1
const WALK_BASE = 1.6   // m/s at x1
const STEP_UP = 0.45    // highest step the walker climbs, m

function useKeys() {
  const keys = useRef<Record<string, boolean>>({})
  useEffect(() => {
    const typing = (e: KeyboardEvent) => e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement
    const down = (e: KeyboardEvent) => { if (!typing(e)) keys.current[e.code] = true }
    const up = (e: KeyboardEvent) => { keys.current[e.code] = false }
    const blur = () => { keys.current = {} }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
    }
  }, [])
  return keys
}

/** Mouse look: pointer lock when the page has it, otherwise drag with the mouse. */
function useMouseLook(onUnlock?: () => void) {
  const camera = useThree((s) => s.camera)
  const gl = useThree((s) => s.gl)
  useEffect(() => {
    const el = gl.domElement
    const euler = new THREE.Euler(0, 0, 0, 'YXZ')
    let dragging = false
    let wasLocked = false
    const look = (mx: number, my: number) => {
      euler.setFromQuaternion(camera.quaternion)
      euler.y -= mx * 0.0025
      euler.x = Math.max(-1.45, Math.min(1.45, euler.x - my * 0.0025))
      euler.z = 0
      camera.quaternion.setFromEuler(euler)
    }
    const move = (e: MouseEvent) => {
      if (document.pointerLockElement === el || dragging) look(e.movementX, e.movementY)
    }
    const md = (e: MouseEvent) => { if (e.button === 0 || e.button === 2) dragging = true }
    const mu = () => { dragging = false }
    const lockChange = () => {
      if (document.pointerLockElement === el) wasLocked = true
      else if (wasLocked) { wasLocked = false; onUnlock?.() }
    }
    const menu = (e: Event) => e.preventDefault()
    window.addEventListener('mousemove', move)
    el.addEventListener('mousedown', md)
    el.addEventListener('contextmenu', menu)
    window.addEventListener('mouseup', mu)
    document.addEventListener('pointerlockchange', lockChange)
    return () => {
      window.removeEventListener('mousemove', move)
      el.removeEventListener('mousedown', md)
      el.removeEventListener('contextmenu', menu)
      window.removeEventListener('mouseup', mu)
      document.removeEventListener('pointerlockchange', lockChange)
      if (document.pointerLockElement === el) document.exitPointerLock()
    }
  }, [camera, gl, onUnlock])
}

/** Free flight: WASD / arrows move, Q/E (or Space/C) down/up, mouse drag
 * looks around, wheel moves forward / back. Shift = x3. */
export function FlyControls({ speeds }: { speeds: Speeds }) {
  const camera = useThree((s) => s.camera)
  const gl = useThree((s) => s.gl)
  const keys = useKeys()
  useMouseLook()
  useEffect(() => {
    const el = gl.domElement
    const wheel = (e: WheelEvent) => {
      e.preventDefault()
      const dir = camera.getWorldDirection(new THREE.Vector3())
      camera.position.addScaledVector(dir, -Math.sign(e.deltaY) * 2.5 * speeds.fly)
    }
    el.addEventListener('wheel', wheel, { passive: false })
    return () => el.removeEventListener('wheel', wheel)
  }, [camera, gl, speeds.fly])
  useFrame((_, dt) => {
    const k = keys.current
    const v = FLY_BASE * speeds.fly * (k.ShiftLeft || k.ShiftRight ? 3 : 1) * Math.min(dt, 0.1)
    const fwd = camera.getWorldDirection(new THREE.Vector3())
    const right = new THREE.Vector3().crossVectors(fwd, camera.up).normalize()
    const m = new THREE.Vector3()
    if (k.KeyW || k.ArrowUp) m.add(fwd)
    if (k.KeyS || k.ArrowDown) m.sub(fwd)
    if (k.KeyD || k.ArrowRight) m.add(right)
    if (k.KeyA || k.ArrowLeft) m.sub(right)
    if (k.KeyE || k.Space) m.y += 1
    if (k.KeyQ || k.KeyC) m.y -= 1
    if (m.lengthSq() > 0) camera.position.addScaledVector(m.normalize(), v)
  })
  return null
}

/** First-person walk: collisions with walls, glass and doors (sliding
 * along them), follows the floor under the feet (steps, stairs, slabs). */
export function WalkControls({ ctx, speeds, start, onExit, onFloor }: {
  ctx: SceneCtx
  speeds: Speeds
  start: { pos: THREE.Vector3; look: THREE.Vector3 } | null
  onExit: () => void
  onFloor: (id: string) => void
}) {
  const camera = useThree((s) => s.camera)
  const keys = useKeys()
  const ray = useMemo(() => new THREE.Raycaster(), [])
  const feet = useRef(0)
  const lastFloor = useRef<string | null>(null)
  useMouseLook(onExit)

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.code === 'Escape' && !document.pointerLockElement) onExit() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onExit])

  useEffect(() => {
    if (!start) return
    camera.position.copy(start.pos)
    camera.up.set(0, 1, 0)
    camera.lookAt(start.look)
    feet.current = start.pos.y - speeds.eye
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start, camera])

  const solids = () => ctx.solids.filter(isVisible)
  const ground = (x: number, z: number, fromY: number) => {
    ray.set(new THREE.Vector3(x, fromY + STEP_UP, z), new THREE.Vector3(0, -1, 0))
    ray.far = STEP_UP + 3
    const hit = ray.intersectObjects(ctx.walkables, false).find((h) => isVisible(h.object))
    return hit ? hit : null
  }

  useFrame((_, dt) => {
    dt = Math.min(dt, 0.1)
    const k = keys.current
    const speed = WALK_BASE * speeds.walk * (k.ShiftLeft || k.ShiftRight ? 2.5 : 1) * dt
    const fwd = camera.getWorldDirection(new THREE.Vector3())
    fwd.y = 0
    fwd.normalize()
    const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0))
    const move = new THREE.Vector3()
    if (k.KeyW || k.ArrowUp) move.add(fwd)
    if (k.KeyS || k.ArrowDown) move.sub(fwd)
    if (k.KeyD || k.ArrowRight) move.add(right)
    if (k.KeyA || k.ArrowLeft) move.sub(right)
    const sol = move.lengthSq() > 0 ? solids() : []
    if (move.lengthSq() > 0) {
      move.normalize()
      // keep 0.3 m from obstacles at knee and chest height; when blocked,
      // slide along the obstacle (try the X and Z parts of the move)
      const free = (d: THREE.Vector3) => {
        if (d.lengthSq() < 1e-6) return false
        const dn = d.clone().normalize()
        for (const h of [0.6, 1.4]) {
          ray.set(new THREE.Vector3(camera.position.x, feet.current + h, camera.position.z), dn)
          ray.far = speed + 0.3
          if (ray.intersectObjects(sol, false).length) return false
        }
        return true
      }
      const options = [move, new THREE.Vector3(move.x, 0, 0), new THREE.Vector3(0, 0, move.z)]
      const ok = options.find(free)
      if (ok) {
        const step = speed * (ok === move ? 1 : Math.max(Math.abs(ok.x), Math.abs(ok.z)))
        camera.position.addScaledVector(ok.clone().normalize(), step)
      }
    }
    // follow the floor: climb steps up to STEP_UP, fall gently otherwise
    const hit = ground(camera.position.x, camera.position.z, feet.current)
    const gy = hit ? hit.point.y : ctx.groundY
    feet.current = gy > feet.current ? gy : Math.max(gy, feet.current - 6 * dt)
    camera.position.y = feet.current + speeds.eye
    // which storey are we on
    let fl: string | null = null
    for (const f of ctx.floors) if (feet.current >= f.elevation! - 0.3) fl = f.id
    if (fl && fl !== lastFloor.current) {
      lastFloor.current = fl
      onFloor(fl)
    }
  })
  return null
}
