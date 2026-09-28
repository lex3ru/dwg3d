import { OrbitControls, OrthographicCamera, PerspectiveCamera } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three/examples/jsm/controls/OrbitControls.js'
import type { Display, NavMode, Projection, Speeds } from '../state'
import { DEFAULT_VIEW_DIR as VIEW_DIR, easeInOut, framePose, type SceneCtx } from './scene'

interface Tween {
  t0: number
  dur: number
  fromPos: THREE.Vector3
  toPos: THREE.Vector3
  fromTarget: THREE.Vector3
  toTarget: THREE.Vector3
  fromZoom: number
  toZoom: number
}

interface Props {
  ctx: SceneCtx
  proj: Projection
  nav: NavMode
  display: Display
  floor: string | null
  speeds: Speeds
  intro: boolean
  onIntroDone: () => void
}

/** Cameras (perspective / top-down orthographic), orbit controls, animated
 * camera moves (fit, fly to floor, zoom steps, the intro fly-in). */
export default function Rig({ ctx, proj, nav, display, floor, speeds, intro, onIntroDone }: Props) {
  // always read the *current* default camera / controls: switching 2D <-> 3D
  // replaces them after this component's render
  const get = useThree((s) => s.get)
  const size = useThree((s) => s.size)
  const controlsState = useThree((s) => s.controls) as OrbitControlsImpl | null
  const cam = () => get().camera
  const ctl = () => get().controls as OrbitControlsImpl | null
  const pendingFrame = useRef(false)
  const tween = useRef<Tween | null>(null)
  const introState = useRef<'pending' | 'running' | 'done'>(intro ? 'pending' : 'done')
  const ready = useRef(false)

  const target = () => {
    const camera = cam(), controls = ctl()
    return controls ? controls.target.clone() : camera.position.clone().add(camera.getWorldDirection(new THREE.Vector3()).multiplyScalar(10))
  }

  const moveTo = (pos: THREE.Vector3, tgt: THREE.Vector3, dur = 700, zoom?: number) => {
    const camera = cam()
    const ortho = (camera as THREE.OrthographicCamera).isOrthographicCamera
    tween.current = {
      t0: performance.now(), dur,
      fromPos: camera.position.clone(), toPos: pos.clone(),
      fromTarget: target(), toTarget: tgt.clone(),
      fromZoom: camera.zoom, toZoom: ortho ? zoom ?? camera.zoom : camera.zoom,
    }
  }

  const topDown = (box: THREE.Box3, dur = 600) => {
    const c = box.getCenter(new THREE.Vector3())
    const s = box.getSize(new THREE.Vector3())
    const zoom = Math.min(size.width / Math.max(s.x, 1), size.height / Math.max(s.z, 1)) * 0.85
    moveTo(new THREE.Vector3(c.x, box.max.y + 200, c.z + 0.001), new THREE.Vector3(c.x, box.max.y, c.z), dur, zoom)
  }

  const frame = (box: THREE.Box3, dur = 700, keepDir = true, minElev = 0.3) => {
    if (proj === '2d') return topDown(box, dur)
    const camera = cam(), controls = ctl()
    const persp = camera as THREE.PerspectiveCamera
    let dir = VIEW_DIR.clone()
    if (keepDir && controls) {
      dir = camera.position.clone().sub(controls.target).normalize()
      if (dir.y < minElev) {
        const h = Math.hypot(dir.x, dir.z) || 1
        const k = Math.sqrt(1 - minElev * minElev) / h
        dir.set(dir.x * k, minElev, dir.z * k)
      }
    }
    const { pos, target: t } = framePose(box, persp.fov ?? 45, size.width / size.height, dir)
    moveTo(pos, t, dur)
  }

  // public camera API for the side buttons
  ctx.api = {
    zoom: (d) => {
      if (nav === 'walk') return
      const camera = cam()
      if (nav === 'fly') {
        const dir = camera.getWorldDirection(new THREE.Vector3())
        const step = 6 * speeds.fly * d
        const pos = camera.position.clone().addScaledVector(dir, step)
        tween.current = null
        moveTo(pos, pos.clone().add(dir), 250)
        return
      }
      const s = THREE.MathUtils.clamp(speeds.orbit, 0.02, 0.9)
      if ((camera as THREE.OrthographicCamera).isOrthographicCamera) {
        moveTo(camera.position, target(), 250, camera.zoom * (d > 0 ? 1 / (1 - s) : 1 - s))
        return
      }
      const t = target()
      const off = camera.position.clone().sub(t).multiplyScalar(d > 0 ? 1 - s : 1 / (1 - s))
      moveTo(t.clone().add(off), t, 250)
    },
    fit: () => {
      if (nav === 'walk') return
      if (proj === '2d') topDown(ctx.frameBox(floor, display, true))
      else frame(ctx.frameBox(null, display), 800, false)
    },
    flyToFloor: (id) => frame(ctx.frameBox(id, display)),
    flyToPoint: (p, r = 6) => {
      const box = new THREE.Box3().setFromCenterAndSize(p, new THREE.Vector3(r, r, r))
      frame(box, 800, true, 0.8)          // steep: the room floor is not hidden behind walls
    },
  }

  // user grabbing the camera cancels an animated move
  useEffect(() => {
    const controls = controlsState
    if (!controls) return
    const stop = () => {
      tween.current = null
      if (introState.current === 'running') { introState.current = 'done'; onIntroDone() }
    }
    controls.addEventListener('start', stop)
    return () => controls.removeEventListener('start', stop)
  }, [controlsState, onIntroDone])

  // first frame with a model: intro fly-in or a plain fit
  useFrame(({ camera, controls: c }) => {
    const controls = c as OrbitControlsImpl | null
    if (ready.current || ctx.bbox.isEmpty() || (nav === 'orbit' && !controls)) return
    ready.current = true
    const box = floor ? ctx.frameBox(floor, display) : ctx.frameBox(null, display)
    if (proj === '2d') {
      const c = box.getCenter(new THREE.Vector3())
      camera.position.set(c.x, box.max.y + 200, c.z + 0.001)
      controls?.target.set(c.x, box.max.y, c.z)
      topDown(box, 1)
      return
    }
    const persp = camera as THREE.PerspectiveCamera
    const { pos, target: t } = framePose(box, persp.fov, size.width / size.height)
    if (introState.current === 'pending' && !floor) {
      // from far above the map down to the facade view
      const r = Math.max(ctx.bbox.getSize(new THREE.Vector3()).length(), 60)
      camera.position.copy(t).add(new THREE.Vector3(0.12, 1, 0.3).normalize().multiplyScalar(r * 14))
      controls?.target.copy(t)
      controls?.update()
      introState.current = 'running'
      moveTo(pos, t, 3200)
    } else {
      camera.position.copy(pos)
      controls?.target.copy(t)
      controls?.update()
      introState.current = 'done'
    }
  })

  // active floor / explode / isolate changes: fly to what is now shown
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    if (nav !== 'orbit' || !ready.current) return
    pendingFrame.current = true          // done in the frame loop, once the right camera is in place
  }, [floor, display.explode, display.onlyActive, display.explodeGap, proj, nav])

  // controls came back after flight / walk: orbit around a point ahead
  const prevNav = useRef(nav)
  useEffect(() => {
    const camera = cam(), controls = controlsState
    if (prevNav.current !== 'orbit' && nav === 'orbit' && controls) {
      const dir = camera.getWorldDirection(new THREE.Vector3())
      controls.target.copy(camera.position).addScaledVector(dir, 15)
      controls.update()
    }
    prevNav.current = nav
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nav, controlsState])

  useFrame(({ camera, controls: c }) => {
    const controls = c as OrbitControlsImpl | null
    if (pendingFrame.current && nav === 'orbit' && controls &&
      !!(camera as THREE.OrthographicCamera).isOrthographicCamera === (proj === '2d')) {
      pendingFrame.current = false
      if (proj === '2d') topDown(ctx.frameBox(floor, display, true))
      else frame(ctx.frameBox(floor, display), display.explode ? 650 : 800)
    }
    const tw = tween.current
    if (tw) {
      const t = Math.min(1, (performance.now() - tw.t0) / tw.dur)
      const k = easeInOut(t)
      camera.position.lerpVectors(tw.fromPos, tw.toPos, k)
      const tg = new THREE.Vector3().lerpVectors(tw.fromTarget, tw.toTarget, k)
      if (tw.fromZoom !== tw.toZoom) {
        camera.zoom = tw.fromZoom * (tw.toZoom / tw.fromZoom) ** k
        camera.updateProjectionMatrix()
      }
      if (controls) {
        controls.target.copy(tg)
        controls.update()
      } else {
        camera.lookAt(tg)
      }
      if (t >= 1) {
        tween.current = null
        if (introState.current === 'running') { introState.current = 'done'; onIntroDone() }
      }
    }
    // depth range follows the distance (map tiles are far, rooms are near)
    const persp = camera as THREE.PerspectiveCamera
    if (persp.isPerspectiveCamera) {
      const d = controls ? camera.position.distanceTo(controls.target) : 20
      const near = nav === 'walk' ? 0.05 : THREE.MathUtils.clamp(d / 600, 0.05, 20)
      const far = Math.max(20000, d * 40)
      if (Math.abs(persp.near - near) / near > 0.1 || persp.far !== far) {
        persp.near = near
        persp.far = far
        persp.updateProjectionMatrix()
      }
    }
  })

  const orbit = nav === 'orbit' || proj === '2d'
  return (
    <>
      {proj === '3d'
        ? <PerspectiveCamera makeDefault fov={45} position={[80, 60, 80]} near={0.1} far={20000} />
        : <OrthographicCamera makeDefault position={[0, 300, 0.001]} zoom={5} near={0.1} far={5000} />}
      {orbit && (
        <OrbitControls
          key={proj}
          makeDefault
          enableDamping
          dampingFactor={0.12}
          zoomSpeed={THREE.MathUtils.clamp(speeds.orbit * 4, 0.2, 4)}
          maxPolarAngle={proj === '2d' ? 0 : Math.PI * 0.495}
          minPolarAngle={0}
          mouseButtons={proj === '2d'
            ? { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE }
            : { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN }}
          touches={proj === '2d' ? { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE } : { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN }}
        />
      )}
    </>
  )
}
