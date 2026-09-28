import { Html, Line } from '@react-three/drei'
import * as THREE from 'three'
import type { Entrance, Pin, Poi, V3 } from '../api'
import type { Display } from '../state'
import FloorFollower from './FloorFollower'
import type { SceneCtx } from './scene'

export interface RouteView {
  floor: string
  pts: V3[]           // glTF, on the floor
  from: V3 | null
  to: V3 | null
  length: number
}

interface Props {
  ctx: SceneCtx
  display: Display
  visible: Set<string>
  entrances: Entrance[]
  pois: Poi[]
  markers: Pin[]
  comments: Pin[]
  route: RouteView | null
  openPin: string | null
  onPin: (id: string | null) => void
  onDeletePin: (kind: 'markers' | 'comments', id: string) => void
}

const POI_ICON: Record<string, string> = { stair: '▤', lift: '⇅' }

export default function Markers(p: Props) {
  const { ctx, display, visible } = p
  const onFloor = (f: string) => visible.has(f)
  return (
    <>
      {display.pois && display.poiKinds.entrance && p.entrances.filter((e) => onFloor(e.floor)).map((e) => (
        <FloorFollower key={e.id} ctx={ctx} floor={e.floor}>
          <Html position={[e.pos[0], e.pos[1] + 3.2, e.pos[2]]} center zIndexRange={[20, 0]}>
            <div className={`poi entrance${e.main ? ' main' : ''}`} title={`${e.name} · ширина ${e.width} м`}>{e.label}</div>
          </Html>
          <Line points={[[e.pos[0], e.pos[1] + 0.05, e.pos[2]], [e.pos[0], e.pos[1] + 2.6, e.pos[2]]]} color="#1c7ed6" lineWidth={1.5} transparent opacity={0.6} />
        </FloorFollower>
      ))}
      {display.pois && p.pois.filter((x) => display.poiKinds[x.kind] && onFloor(x.floor)).map((x, i) => (
        <FloorFollower key={`poi${i}`} ctx={ctx} floor={x.floor}>
          <Html position={[x.pos[0], x.pos[1] + 1.8, x.pos[2]]} center zIndexRange={[18, 0]}>
            <div className={`poi small ${x.kind}`} title={x.kind === 'stair' ? 'Лестница' : 'Лифт'}>{POI_ICON[x.kind]}</div>
          </Html>
        </FloorFollower>
      ))}
      {display.pois && display.poiKinds.marker && p.markers.filter((m) => !m.floor || onFloor(m.floor)).map((m) => {
        const el = (
          <Html position={[m.pos[0], m.pos[1] + 0.2, m.pos[2]]} zIndexRange={[25, 0]} style={{ transform: 'translate(-50%, -100%)' }}>
            <div className={`pin marker${p.openPin === m.id ? ' open' : ''}`} onClick={() => p.onPin(p.openPin === m.id ? null : m.id)}>
              <span>📍</span>{m.label || m.text ? <b>{m.label || m.text}</b> : null}
              {p.openPin === m.id && (
                <div className="pin-card" onClick={(e) => e.stopPropagation()}>
                  <p>{m.text || 'Метка'}</p>
                  <button className="small" onClick={() => p.onDeletePin('markers', m.id)}>Удалить</button>
                </div>
              )}
            </div>
          </Html>
        )
        return m.floor ? <FloorFollower key={m.id} ctx={ctx} floor={m.floor}>{el}</FloorFollower> : <group key={m.id}>{el}</group>
      })}
      {display.comments && p.comments.filter((c) => !c.floor || onFloor(c.floor)).map((c) => {
        const el = (
          <Html position={c.pos} zIndexRange={[26, 0]} style={{ transform: 'translate(-4px, -100%)' }}>
            <div className={`pin comment${p.openPin === c.id ? ' open' : ''}`} onClick={() => p.onPin(p.openPin === c.id ? null : c.id)}>
              <span>💬</span>
              {p.openPin === c.id && (
                <div className="pin-card" onClick={(e) => e.stopPropagation()}>
                  <p>{c.text}</p>
                  {c.created ? <small>{new Date(c.created * 1000).toLocaleString('ru')}</small> : null}
                  <button className="small" onClick={() => p.onDeletePin('comments', c.id)}>Удалить</button>
                </div>
              )}
            </div>
          </Html>
        )
        return c.floor ? <FloorFollower key={c.id} ctx={ctx} floor={c.floor}>{el}</FloorFollower> : <group key={c.id}>{el}</group>
      })}
      {p.route && onFloor(p.route.floor) && (
        <FloorFollower ctx={ctx} floor={p.route.floor}>
          {p.route.pts.length >= 2 && (
            <>
              <Line points={p.route.pts} color="#ffffff" lineWidth={9} depthTest={false} renderOrder={20} transparent opacity={0.9} />
              <Line points={p.route.pts} color="#1c7ed6" lineWidth={5} depthTest={false} renderOrder={21} />
            </>
          )}
          {p.route.from && <RouteEnd pos={p.route.from} color="#2b8a3e" />}
          {p.route.to && <RouteEnd pos={p.route.to} color="#e03131" />}
          {p.route.pts.length >= 2 && (
            <Html position={p.route.pts[Math.floor(p.route.pts.length / 2)]} center style={{ pointerEvents: 'none' }} zIndexRange={[22, 0]}>
              <div className="route-label">{p.route.length.toFixed(0)} м · ~{Math.max(1, Math.round(p.route.length / 1.3 / 60))} мин</div>
            </Html>
          )}
        </FloorFollower>
      )}
    </>
  )
}

function RouteEnd({ pos, color }: { pos: V3; color: string }) {
  return (
    <mesh position={new THREE.Vector3(pos[0], pos[1] + 0.05, pos[2])} rotation-x={-Math.PI / 2} renderOrder={22}>
      <circleGeometry args={[0.35, 24]} />
      <meshBasicMaterial color={color} depthTest={false} />
    </mesh>
  )
}
