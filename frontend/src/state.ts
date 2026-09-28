/** Viewer state shared by the panels and the 3D scene: display preferences
 * (persisted in localStorage), navigation speeds, and the URL hash view. */

export type NavMode = 'orbit' | 'fly' | 'walk'
export type Projection = '2d' | '3d'
export type Quality = 'auto' | 'high' | 'eco' | 'real'
export type Facade = 'auto' | 'weekday' | 'holiday'
export type DayTime = 'day' | 'evening' | 'night'
/** click tools of the scene (navigation modes are separate) */
export type Tool = 'none' | 'measure' | 'route' | 'marker' | 'comment'
export type MeasureMode = 'length' | 'area'

export interface Display {
  xray: boolean           // transparent walls
  onlyActive: boolean     // only the active floor
  roomColors: boolean     // room floors coloured by type
  explode: boolean        // floors pulled apart
  highlight: boolean      // active floor highlighted, others muted
  quality: Quality
  facade: Facade
  dayTime: DayTime
  map: boolean
  roof: boolean
  glass: boolean
  rooms: boolean
  labels: boolean
  pois: boolean           // entrances, stairs, lifts, user markers
  poiKinds: Record<'entrance' | 'stair' | 'lift' | 'marker', boolean>
  furniture: boolean
  comments: boolean
  explodeGap: number      // m between exploded floors
}

export interface Speeds {
  orbit: number   // zoom step (fraction per click / wheel multiplier)
  fly: number     // multiplier of the base flight speed
  walk: number    // multiplier of the base walking speed
  eye: number     // eye height, m
}

export const DEFAULT_DISPLAY: Display = {
  xray: false, onlyActive: false, roomColors: true, explode: false, highlight: false,
  quality: 'auto', facade: 'auto', dayTime: 'day', map: true,
  roof: true, glass: true, rooms: true, labels: true,
  pois: true, poiKinds: { entrance: true, stair: false, lift: true, marker: true },
  furniture: true, comments: true, explodeGap: 6,
}

export const DEFAULT_SPEEDS: Speeds = { orbit: 0.25, fly: 1, walk: 1, eye: 1.6 }

/** slider stops of the navigation panel */
export const SPEED_STEPS: Record<NavMode, number[]> = {
  orbit: [0.05, 0.1, 0.15, 0.25, 0.35, 0.5, 0.75],
  fly: [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5],
  walk: [0.5, 0.75, 1, 1.5, 2, 3],
}

const KEY = 'dwg3d.prefs.v1'

function read<T>(k: string): Partial<T> {
  try {
    const v = JSON.parse(localStorage.getItem(k) ?? '{}')
    return v && typeof v === 'object' ? v : {}
  } catch {
    return {}
  }
}

export function loadPrefs(): { display: Display; speeds: Speeds } {
  const p = read<{ display: Display; speeds: Speeds }>(KEY)
  const d = { ...DEFAULT_DISPLAY, ...(p.display ?? {}) }
  d.poiKinds = { ...DEFAULT_DISPLAY.poiKinds, ...(p.display?.poiKinds ?? {}) }
  return { display: d, speeds: { ...DEFAULT_SPEEDS, ...(p.speeds ?? {}) } }
}

export function savePrefs(display: Display, speeds: Speeds) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ display, speeds }))
  } catch { /* private mode / quota */ }
}

// ------------------------------------------------------------ URL hash ---
export interface HashView {
  job: string
  floor: string | null
  proj: Projection
  explode?: boolean
  onlyActive?: boolean
  xray?: boolean
}

/** `#/f/<job>/floor_<id>/<2d|3d>?e=1&o=1&x=1` (or `.../all/3d`) */
export function parseHash(h = location.hash): HashView | null {
  const m = /^#\/f\/([\w-]+)(?:\/(all|floor_([\w-]+)))?(?:\/(2d|3d))?(?:\?(.*))?$/.exec(h)
  if (!m) return null
  const q = new URLSearchParams(m[5] ?? '')
  const flag = (k: string) => (q.has(k) ? q.get(k) === '1' : undefined)
  return {
    job: m[1], floor: m[3] ?? null, proj: (m[4] as Projection) ?? '3d',
    explode: flag('e'), onlyActive: flag('o'), xray: flag('x'),
  }
}

export function formatHash(v: HashView): string {
  const q = new URLSearchParams()
  if (v.explode) q.set('e', '1')
  if (v.onlyActive) q.set('o', '1')
  if (v.xray) q.set('x', '1')
  const qs = q.toString()
  return `#/f/${v.job}/${v.floor ? `floor_${v.floor}` : 'all'}/${v.proj}${qs ? `?${qs}` : ''}`
}

// ------------------------------------------------------- facade lights ---
/** Evening / night facade lighting presets. */
export interface FacadePreset {
  windows: string[]        // window glow colours (cycled per floor)
  intensity: number
  contour: string          // outline (edge) colour
  contourIntensity: number
  animate: boolean
}

export const FACADE_PRESETS: Record<'weekday' | 'holiday', FacadePreset> = {
  weekday: { windows: ['#ffd9a0', '#fff1d6', '#ffe2b8'], intensity: 0.9, contour: '#ffe9c2', contourIntensity: 0.35, animate: false },
  holiday: { windows: ['#ff5d5d', '#ffd84d', '#5cb8ff', '#8cff8a', '#ff8ae6'], intensity: 1.35, contour: '#ffcc33', contourIntensity: 1, animate: true },
}

/** Public holidays (RU calendar) and the New Year season, as MM-DD. */
const HOLIDAYS = ['02-23', '03-08', '05-01', '05-09', '06-12', '11-04']

export function isHoliday(d = new Date()): boolean {
  const m = d.getMonth() + 1, day = d.getDate()
  if ((m === 12 && day >= 20) || (m === 1 && day <= 10)) return true
  return HOLIDAYS.includes(`${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`)
}

export function resolveFacade(f: Facade, d = new Date()): 'weekday' | 'holiday' {
  if (f !== 'auto') return f
  return isHoliday(d) ? 'holiday' : 'weekday'
}

/** Quality chosen by "Авто": weak / software GPUs and small devices get "eco". */
export function detectQuality(gl?: WebGLRenderingContext | WebGL2RenderingContext | null): 'high' | 'eco' {
  let renderer = ''
  try {
    const ctx = gl ?? document.createElement('canvas').getContext('webgl2')
    const ext = ctx?.getExtension('WEBGL_debug_renderer_info')
    renderer = String(ext && ctx ? ctx.getParameter(ext.UNMASKED_RENDERER_WEBGL) : ctx?.getParameter(ctx.RENDERER) ?? '')
  } catch { /* no webgl */ }
  const nav = navigator as Navigator & { deviceMemory?: number }
  const weakGpu = /swiftshader|llvmpipe|softpipe|software|basic render|mali-[4t]|adreno \(tm\) [2-5]\d\d|powervr/i.test(renderer)
  const smallDevice = (nav.deviceMemory ?? 8) < 4 || (nav.hardwareConcurrency ?? 8) < 4
  return weakGpu || smallDevice ? 'eco' : 'high'
}

export function jobColor(id: string): string {
  let h = 0
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360
  return `hsl(${h} 65% 48%)`
}
