import Neighbours from './Neighbours'
import { facadeUrl } from '../compat'
import { Environment, GizmoHelper, GizmoViewport, Lightformer, PerformanceMonitor, SoftShadows } from '@react-three/drei'
import { Canvas, useThree } from '@react-three/fiber'
import { Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import type { Pin, Result, V3, ViewSettings } from '../api'
import {
  FACADE_PRESETS, detectQuality, resolveFacade,
  type Display, type MeasureMode, type NavMode, type Projection, type Speeds, type Tool,
} from '../state'
import Building, { type Pick, type RoomHit } from './Building'
import Detail, { type DetailInfo } from './Detail'
import { FlyControls, WalkControls } from './FlyWalk'
import Ground, { Sky } from './MapLayer'
import { useDarkClass } from '@/lib/theme'
import { PAGE_2D, skyColors } from './tiles'
import Furniture from './Furniture'
import Markers, { type RouteView } from './Markers'
import Shapes, { type ShapesProps } from './Shapes'
import { useMeasure } from './Measure'
import Rig from './Rig'
import { openFloors, visibleFloors, type SceneCtx } from './scene'

export interface Cuts { h: { on: boolean; y: number }; v: { on: boolean; x: number } }

export interface ViewerProps {
  jobId: string
  url: string
  result: Result
  display: Display
  floor: string | null
  proj: Projection
  nav: NavMode
  speeds: Speeds
  tool: Tool
  measureMode: MeasureMode
  cuts: Cuts
  view: ViewSettings
  selectedRoom: string | null
  route: RouteView | null
  openPin: string | null
  walkStart: { pos: THREE.Vector3; look: THREE.Vector3 } | null
  intro: boolean
  ctx: SceneCtx
  onIntroDone: () => void
  onRoomClick: (r: RoomHit | null) => void
  onPick: (p: Pick) => void
  onExitWalk: () => void
  onWalkFloor: (id: string) => void
  onPin: (id: string | null) => void
  onDeletePin: (kind: 'markers' | 'comments', id: string) => void
  onQuality: (q: 'high' | 'eco' | 'real') => void
  onDetailInfo: (i: DetailInfo | null) => void
  furniture: FurnitureView
  /** routes of people and zones (functional layers) */
  shapes: ShapesProps
}

/** Furniture layer props supplied by the app (the rest comes from the scene). */
export type FurnitureView = Omit<React.ComponentProps<typeof Furniture>, 'ctx' | 'floors' | 'center' | 'visible' | 'display' | 'proj'>

const NIGHT: Record<string, number> = { day: 0, evening: 0.6, night: 1 }

function Lights({ dayTime, shadows, extent, real }: { dayTime: string; shadows: boolean; extent: number; real: boolean }) {
  const e = Math.max(60, extent)
  const cfg = {
    day: { hemi: ['#ffffff', '#b0a99f', 1.1], sun: ['#ffffff', 1.6], pos: [0.6, 1, 0.4] },
    evening: { hemi: ['#ffd2a8', '#6b5a4a', 0.6], sun: ['#ffae6b', 0.9], pos: [-0.9, 0.35, 0.3] },
    night: { hemi: ['#6c7aa8', '#1b1b25', 0.28], sun: ['#9fb4ff', 0.18], pos: [0.3, 1, -0.5] },
  }[dayTime as 'day']
  return (
    <>
      <hemisphereLight args={[cfg.hemi[0] as string, cfg.hemi[1] as string, (cfg.hemi[2] as number) * (real ? 0.6 : 1)]} />
      <directionalLight
        position={[cfg.pos[0] * e, cfg.pos[1] * e, cfg.pos[2] * e]}
        color={cfg.sun[0] as string}
        intensity={cfg.sun[1] as number}
        castShadow={shadows}
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-e}
        shadow-camera-right={e}
        shadow-camera-top={e}
        shadow-camera-bottom={-e}
        shadow-camera-far={e * 4}
        shadow-bias={-0.0005}
        shadow-normalBias={0.02}
      />
    </>
  )
}

/** Resolves "Авто" once the renderer exists (GPU name) and steps down on low fps. */
function AutoQuality({ onQuality }: { onQuality: (q: 'high' | 'eco') => void }) {
  const gl = useThree((s) => s.gl)
  useEffect(() => { onQuality(detectQuality(gl.getContext())) }, [gl, onQuality])
  return <PerformanceMonitor bounds={() => [40, 55]} flipflops={2} onDecline={() => onQuality('eco')} />
}

function Scene(p: ViewerProps & { quality: 'high' | 'eco' | 'real'; setAuto: (q: 'high' | 'eco') => void }) {
  const { ctx, result, display } = p
  const dark = useDarkClass()
  const measure = useMeasure(p.measureMode, p.tool === 'measure')
  const active = ctx.setCuts(p.cuts.h, p.cuts.v)
  const floors = useMemo(() => [...result.floors].sort((a, b) => a.elevation! - b.elevation!), [result.floors])
  const visible = useMemo(() => visibleFloors(floors, display, p.floor, p.nav), [floors, display, p.floor, p.nav])
  const open = openFloors(floors, visible, {
    exploded: display.explode && p.proj === '3d' && p.nav !== 'walk', xray: display.xray, topDown: p.proj === '2d',
    walking: false, roofShown: display.roof && p.proj === '3d' && (p.floor == null || p.nav === 'walk'),
  })
  const night = NIGHT[display.dayTime] ?? 0
  const preset = FACADE_PRESETS[resolveFacade(display.facade)]
  const extent = ctx.bbox.isEmpty() ? 60 : ctx.bbox.getSize(new THREE.Vector3()).length() / 2

  const onPick = (pk: Pick) => {
    if (p.tool === 'measure') measure.pick(pk.point)
    else p.onPick(pk)
  }
  const detail = p.view.detail?.file ? p.view.detail : null
  return (
    <>
      {p.proj === '3d' ? <Sky dayTime={display.dayTime} /> : <color attach="background" args={[dark ? PAGE_2D.dark : PAGE_2D.light]} />}
      {p.proj === '3d' && <fog attach="fog" args={[skyColors(display.dayTime, dark)[1], 2500, 9000]} />}
      <Lights dayTime={display.dayTime} shadows={p.quality !== 'eco'} extent={extent} real={p.quality === 'real'} />
      {p.quality === 'real' && (
        <>
          <SoftShadows size={18} samples={12} focus={0.6} />
          <Environment resolution={128} frames={1}>
            <Lightformer intensity={1.6} position={[0, 6, 0]} rotation-x={Math.PI / 2} scale={[12, 12, 1]} />
            <Lightformer intensity={0.7} position={[-8, 2, 4]} rotation-y={Math.PI / 2} scale={[10, 3, 1]} color="#ffe8cc" />
            <Lightformer intensity={0.5} position={[8, 2, -4]} rotation-y={-Math.PI / 2} scale={[10, 3, 1]} color="#d0e4ff" />
          </Environment>
        </>
      )}
      <Building
        ctx={ctx} url={p.url} result={result} display={display} floor={p.floor} proj={p.proj} nav={p.nav} tool={p.tool}
        eco={p.quality === 'eco'} edges={p.quality !== 'eco'} night={night} preset={preset} planes={active}
        selectedRoom={p.selectedRoom} onRoomClick={p.onRoomClick} onPick={onPick}
        onDoublePick={(pk) => { if (p.tool === 'measure') measure.pick(pk.point, true) }}
        onPointer={(pk) => { if (p.tool === 'measure') measure.probe(pk?.point ?? null) }}
      />
      <Neighbours drawing={p.jobId} />
      {detail && (
        <Suspense fallback={null}>
          <Detail ctx={ctx} url={facadeUrl(p.jobId, detail.version ?? 0)} cfg={detail}
            floors={floors} display={display} active={p.floor} nav={p.nav} onInfo={p.onDetailInfo} />
        </Suspense>
      )}
      {measure.node}
      <Furniture ctx={ctx} floors={floors} center={result.center ?? [0, 0]} visible={visible} display={display} proj={p.proj} {...p.furniture} />
      <Shapes ctx={ctx} floors={floors} center={result.center ?? [0, 0]} visible={visible} {...p.shapes} />
      <Markers ctx={ctx} walking={p.nav === 'walk'} display={display} visible={visible} open={open} entrances={result.entrances ?? []} pois={result.pois ?? []}
        markers={p.view.markers ?? []} comments={p.view.comments ?? []} route={p.route} openPin={p.openPin}
        onPin={p.onPin} onDeletePin={p.onDeletePin} />
      <Ground ctx={ctx} site={p.view.site} showMap={display.map} dayTime={display.dayTime} extent={extent} />
      <Rig ctx={ctx} proj={p.proj} nav={p.nav} display={display} floor={p.floor} speeds={p.speeds}
        intro={p.intro} onIntroDone={p.onIntroDone} />
      {p.nav === 'fly' && p.proj === '3d' && <FlyControls speeds={p.speeds} />}
      {p.nav === 'walk' && p.proj === '3d' && (
        <WalkControls ctx={ctx} speeds={p.speeds} start={p.walkStart} onExit={p.onExitWalk} onFloor={p.onWalkFloor} />
      )}
      {p.quality !== 'real' && display.quality === 'auto' && <AutoQuality onQuality={p.setAuto} />}
      {p.nav !== 'walk' && (
        <GizmoHelper alignment="bottom-left" margin={[64, 64]}>
          <GizmoViewport axisColors={['#e03131', '#2f9e44', '#1c7ed6']} labelColor="#fff" hideNegativeAxes axisHeadScale={0.9} />
        </GizmoHelper>
      )}
    </>
  )
}

export default function Viewer(p: ViewerProps) {
  const [auto, setAutoState] = useState<'high' | 'eco' | null>(null)
  const setAuto = useCallback((q: 'high' | 'eco') => setAutoState((cur) => (cur === 'eco' ? 'eco' : q)), [])
  const quality = p.display.quality === 'auto' ? auto ?? 'high' : p.display.quality
  const { onQuality } = p
  useEffect(() => { onQuality(quality) }, [quality, onQuality])
  const dpr: [number, number] | number = quality === 'eco' ? 1 : [1, 2]
  return (
    <Canvas
      key={quality === 'eco' ? 'eco' : 'aa'}           // antialiasing is fixed at context creation
      shadows={quality !== 'eco'}
      dpr={dpr}
      gl={{ antialias: quality !== 'eco', powerPreference: 'high-performance', localClippingEnabled: true }}
      className={p.tool !== 'none' ? 'cursor-crosshair' : p.nav === 'walk' ? 'cursor-none' : ''}
    >
      <Scene {...p} quality={quality} setAuto={setAuto} />
    </Canvas>
  )
}

export type { Pick, RoomHit, RouteView, DetailInfo, Pin, V3 }
