import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { ViewSettings } from '../api'
import { useDarkClass } from '../lib/theme'
import type { DayTime } from '../state'
import type { SceneCtx } from './scene'
import { DAY_TINT, GROUND, MAP_BG, skyColors, TILE_SUBDOMAINS, TILE_URL } from './tiles'

const lon2x = (lon: number, z: number) => ((lon + 180) / 360) * 2 ** z
const lat2y = (lat: number, z: number) => {
  const r = (lat * Math.PI) / 180
  return ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z
}

interface TileSpec { key: string; url: string; x: number; z: number; size: number; y: number }

/** Tiles of one zoom level around the site, placed in local meters
 * (east = +X, north = -Z) relative to the site point. */
function ring(url: string, lat: number, lon: number, zoom: number, n: number, retina: boolean, lift: number): TileSpec[] {
  const mpp = (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom   // meters per 256-px tile pixel
  const size = 256 * mpp
  const fx = lon2x(lon, zoom), fy = lat2y(lat, zoom)
  const cx = Math.floor(fx), cy = Math.floor(fy)
  const out: TileSpec[] = []
  const h = Math.floor(n / 2)
  const max = 2 ** zoom
  for (let dy = -h; dy <= h; dy++) {
    for (let dx = -h; dx <= h; dx++) {
      const tx = cx + dx, ty = cy + dy
      if (ty < 0 || ty >= max) continue
      const wx = ((tx + 0.5 - fx) * 256) * mpp
      const wz = ((ty + 0.5 - fy) * 256) * mpp
      const s = TILE_SUBDOMAINS[(tx + ty) % 4]
      const u = url.replace('{s}', s).replace('{z}', String(zoom)).replace('{x}', String(((tx % max) + max) % max))
        .replace('{y}', String(ty)).replace('{r}', retina ? '@2x' : '')
      out.push({ key: `${zoom}/${tx}/${ty}`, url: u, x: wx, z: wz, size, y: lift })
    }
  }
  return out
}

/** Desaturate and lighten the basemap: a quiet, light background. */
function desaturate(m: THREE.MeshBasicMaterial) {
  m.onBeforeCompile = (sh) => {
    // desaturate + lighten the texel first, then the time-of-day tint (material colour) darkens it
    sh.fragmentShader = sh.fragmentShader.replace('#include <map_fragment>', `#ifdef USE_MAP
      vec4 texel = texture2D(map, vMapUv);
      float lum = dot(texel.rgb, vec3(0.299, 0.587, 0.114));
      texel.rgb = mix(mix(vec3(lum), texel.rgb, 0.18), vec3(1.0), 0.28);
      diffuseColor *= texel;
    #endif`)
  }
  m.customProgramCacheKey = () => 'tile-desaturate'
}

function Tile({ t, material }: { t: TileSpec; material: THREE.MeshBasicMaterial }) {
  const mat = useMemo(() => {
    const m = material.clone()
    desaturate(m)
    m.map = null
    m.transparent = true
    m.opacity = 0
    new THREE.TextureLoader().setCrossOrigin('anonymous').load(t.url, (tex) => {
      tex.colorSpace = THREE.SRGBColorSpace
      tex.anisotropy = 8
      m.map = tex
      m.opacity = 1
      m.transparent = false
      m.needsUpdate = true
    })
    return m
  }, [t.url, material])
  useEffect(() => () => { mat.map?.dispose(); mat.dispose() }, [mat])
  return (
    <mesh position={[t.x, t.y, t.z]} rotation-x={-Math.PI / 2} material={mat} renderOrder={-2}>
      <planeGeometry args={[t.size, t.size]} />
    </mesh>
  )
}

/** Ground: the basemap around the site (when bound to a place and enabled)
 * or a neutral plane with a grid. Its top is also what a walker stands on
 * outside the building. */
export default function Ground({ ctx, site, showMap, dayTime, extent }: {
  ctx: SceneCtx
  site: ViewSettings['site'] | undefined
  showMap: boolean
  dayTime: DayTime
  extent: number
}) {
  const group = useRef<THREE.Group>(null)
  const plane = useRef<THREE.Mesh>(null)
  const tint = DAY_TINT[dayTime]
  const tileMat = useMemo(() => new THREE.MeshBasicMaterial({ color: tint, toneMapped: false, polygonOffset: true, polygonOffsetFactor: 2, polygonOffsetUnits: 2 }), [tint])
  const tiles = useMemo(() => {
    if (!site || !showMap) return []
    const url = site.tiles || TILE_URL
    const r = url.includes('{r}')
    // coarse far ring, the neighbourhood, and sharp tiles right around the building
    return [...ring(url, site.lat, site.lon, 14, 7, false, -0.1), ...ring(url, site.lat, site.lon, 17, 7, r, -0.05),
      ...ring(url, site.lat, site.lon, 19, 5, r, 0)]
  }, [site, showMap])
  const mapOn = tiles.length > 0

  useEffect(() => {
    const m = plane.current
    if (!m) return
    m.userData.role = 'ground'
    ctx.walkables.push(m)
    return () => { ctx.walkables = ctx.walkables.filter((o) => o !== m) }
  }, [ctx])

  useFrame(() => {
    if (group.current) group.current.position.y = ctx.groundY - 0.02
  })

  const dark = useDarkClass() && dayTime === 'day' && !mapOn
  const bg = new THREE.Color(mapOn ? MAP_BG : dark ? GROUND.dark : GROUND.light).multiply(new THREE.Color(tint))
  return (
    <group ref={group}>
      <mesh ref={plane} rotation-x={-Math.PI / 2} receiveShadow renderOrder={-3} position={[0, -0.08, 0]}>
        <planeGeometry args={[mapOn ? 40000 : 4000, mapOn ? 40000 : 4000]} />
        <meshStandardMaterial color={bg} roughness={1} polygonOffset polygonOffsetFactor={4} polygonOffsetUnits={4} />
      </mesh>
      {mapOn ? (
        <group rotation-y={((site!.azimuth ?? 0) * Math.PI) / 180} scale={site!.scale || 1}>
          {tiles.map((t) => <Tile key={t.key} t={t} material={tileMat} />)}
        </group>
      ) : (
        <gridHelper args={[Math.max(200, Math.ceil(extent * 4 / 10) * 10), Math.max(20, Math.ceil(extent * 4 / 10) * 2),
          dark ? '#3d4554' : dayTime === 'day' ? '#ced4da' : '#556', dark ? '#333a47' : dayTime === 'day' ? '#dee2e6' : '#445']} position={[0, -0.05, 0]} />
      )}
    </group>
  )
}

/** Gradient sky dome that follows the camera. */
export function Sky({ dayTime }: { dayTime: DayTime }) {
  const dark = useDarkClass()
  const ref = useRef<THREE.Mesh>(null)
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: { top: { value: new THREE.Color() }, horizon: { value: new THREE.Color() } },
    vertexShader: 'varying vec3 vDir; void main(){ vDir = normalize(position); vec4 p = modelViewMatrix * vec4(position,1.0); gl_Position = projectionMatrix * p; gl_Position.z = gl_Position.w; }',
    fragmentShader: 'uniform vec3 top; uniform vec3 horizon; varying vec3 vDir; void main(){ float h = clamp(vDir.y, 0.0, 1.0); gl_FragColor = vec4(mix(horizon, top, pow(h, 0.55)), 1.0); }',
    side: THREE.BackSide, depthWrite: false, depthTest: false,
  }), [])
  useEffect(() => {
    const [t, h] = skyColors(dayTime, dark)
    mat.uniforms.top.value.set(t)
    mat.uniforms.horizon.value.set(h)
  }, [dayTime, dark, mat])
  useFrame(({ camera }) => { ref.current?.position.copy(camera.position) })
  return (
    <mesh ref={ref} material={mat} renderOrder={-10} frustumCulled={false} raycast={() => null}>
      <sphereGeometry args={[1000, 32, 16]} />
    </mesh>
  )
}

