import { Html, Line } from '@react-three/drei'
import { useThree } from '@react-three/fiber'
import { useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import { htmlLayer } from './scene'
import type { MeasureMode } from '../state'

/** Vector area (Newell) of a closed 3D polygon: |n| / 2 = area, n = normal. */
export function newell(pts: THREE.Vector3[]): THREE.Vector3 {
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

/** Ruler: distance between two points or area of a contour in any plane.
 * Esc clears, Backspace removes the last point, Enter / double click /
 * a click on the first vertex closes the area contour. */
export function useMeasure(mode: MeasureMode, active: boolean) {
  const camera = useThree((s) => s.camera)
  const size = useThree((s) => s.size)
  const [pts, setPts] = useState<THREE.Vector3[]>([])
  const [closed, setClosed] = useState(false)
  const [probe, setProbe] = useState<THREE.Vector3 | null>(null)

  useEffect(() => {
    setPts([])
    setClosed(false)
    setProbe(null)
  }, [mode, active])

  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return
      if (e.key === 'Escape') { setPts([]); setClosed(false) }
      else if (e.key === 'Backspace' || e.key === 'Delete') { setClosed(false); setPts((m) => m.slice(0, -1)) }
      else if (e.key === 'Enter' && mode === 'area') setPts((m) => { if (m.length >= 3) setClosed(true); return m })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, mode])

  const toScreen = (p: THREE.Vector3) => {
    const v = p.clone().project(camera)
    return [(v.x + 1) / 2 * size.width, (1 - v.y) / 2 * size.height]
  }

  const pick = (p: THREE.Vector3, dbl = false) => {
    if (mode === 'length') { setPts((m) => (m.length >= 2 ? [p] : [...m, p])); return }
    if (dbl) {
      setPts((m) => {
        const out = m.length >= 2 && m[m.length - 1].distanceTo(m[m.length - 2]) < 0.05 ? m.slice(0, -1) : m
        if (out.length >= 3) setClosed(true)
        return out
      })
      return
    }
    if (closed) { setClosed(false); setPts([p]); return }
    if (pts.length >= 3) {
      const [fx, fy] = toScreen(pts[0])
      const [px, py] = toScreen(p)
      if (Math.hypot(fx - px, fy - py) < 12) { setClosed(true); return }
    }
    setPts((m) => [...m, p])
  }

  const areaPts = mode === 'area' ? (closed || !probe || pts.length < 2 ? pts : [...pts, probe]) : []
  const geomKey = areaPts.map((p) => p.toArray().join()).join('|')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const areaGeom = useMemo(() => (areaPts.length >= 3 ? polygonGeometry(areaPts) : null), [geomKey])
  const area = areaPts.length >= 3 ? newell(areaPts).length() : 0
  const perimeter = areaPts.reduce((s, p, i) =>
    s + (i < areaPts.length - 1 || areaPts.length >= 3 ? p.distanceTo(areaPts[(i + 1) % areaPts.length]) : 0), 0)
  const center = areaPts.length ? areaPts.reduce((c, p) => c.add(p), new THREE.Vector3()).multiplyScalar(1 / areaPts.length) : null

  const node = !active || pts.length === 0 ? null : (
    <>
      {pts.map((p, i) => {
        const closeTarget = mode === 'area' && !closed && i === 0 && pts.length >= 3
        return (
          <mesh key={i} position={p} renderOrder={11}>
            <sphereGeometry args={[closeTarget ? 0.16 : 0.08, 14, 14]} />
            <meshBasicMaterial color={closeTarget ? '#1c7ed6' : '#e03131'} depthTest={false} />
          </mesh>
        )
      })}
      {mode === 'length' && pts.length === 1 && probe && (
        <>
          <Line points={[pts[0], probe]} color="#e03131" lineWidth={1.5} dashed dashSize={0.2} gapSize={0.1} depthTest={false} />
          <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={probe} style={{ pointerEvents: 'none' }}>
            <div className="measure-label ghost">{pts[0].distanceTo(probe).toFixed(2)} м</div>
          </Html>
        </>
      )}
      {mode === 'length' && pts.length === 2 && (
        <>
          <Line points={pts} color="#e03131" lineWidth={2} depthTest={false} />
          <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={pts[0].clone().add(pts[1]).multiplyScalar(0.5)} center style={{ pointerEvents: 'none' }}>
            <div className="measure-label">{pts[0].distanceTo(pts[1]).toFixed(2)} м</div>
          </Html>
        </>
      )}
      {mode === 'area' && areaPts.length >= 2 && (
        <>
          <Line points={closed ? [...areaPts, areaPts[0]] : areaPts} color="#e03131" lineWidth={2} depthTest={false} />
          {areaGeom && (
            <mesh geometry={areaGeom} renderOrder={10}>
              <meshBasicMaterial color="#fa5252" transparent opacity={closed ? 0.3 : 0.18} side={THREE.DoubleSide} depthTest={false} />
            </mesh>
          )}
          {center && areaPts.length >= 3 && (
            <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={center} center style={{ pointerEvents: 'none' }}>
              <div className={`measure-label${closed ? '' : ' ghost'}`}>
                S {closed ? '=' : '≈'} {area.toFixed(2)} м²
                <small>P = {perimeter.toFixed(2)} м · {areaPts.length} точ.</small>
              </div>
            </Html>
          )}
        </>
      )}
    </>
  )
  return { pick, probe: setProbe, node }
}
