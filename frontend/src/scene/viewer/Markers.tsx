import { Html, Line } from '@react-three/drei'
import * as THREE from 'three'
import { htmlLayer } from './scene'
import type { Entrance, Pin, Poi, V3 } from '../api'
import type { Display } from '../state'
import FloorFollower from './FloorFollower'
import type { SceneCtx } from './scene'
import { Button } from '@/components/ui/button'
import { Tip, TooltipProvider } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export interface RouteView {
  floor: string
  pts: V3[]           // glTF, on the floor
  from: V3 | null
  to: V3 | null
  length: number
}

interface Props {
  ctx: SceneCtx
  walking: boolean
  display: Display
  visible: Set<string>
  /** floors whose floor is not covered: pins inside the building show only there */
  open: Set<string>
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

const pin = 'pointer-events-auto relative flex cursor-pointer items-end gap-1 select-none'
const pinIcon = 'text-[22px] leading-none drop-shadow-[0_1px_2px_rgba(0,0,0,.4)]'
const pinLabel = 'rounded-[5px] bg-white/95 px-1.5 py-px text-xs whitespace-nowrap text-[#212529] shadow-[0_1px_3px_rgba(0,0,0,.2)]'

/** The text of an open marker or comment, over the pin. */
function PinCard({ text, when, what, onDelete }: { text: string; when?: string; what: string; onDelete: () => void }) {
  return (
    <div className="pointer-events-auto absolute bottom-[calc(100%+6px)] left-0 grid w-56 cursor-default gap-1.5 rounded-lg border border-border bg-popover p-2.5 text-[12.5px] text-popover-foreground shadow-lg"
      onClick={(e) => e.stopPropagation()}>
      <p className="m-0 break-words whitespace-pre-wrap">{text}</p>
      {when && <small className="text-muted-foreground">{when}</small>}
      <Button variant="outline" size="sm" className="justify-self-start text-destructive" onClick={onDelete}
        hint={`${what} пропадёт у всех, кто открывает здание; отменить нельзя`}>Удалить</Button>
    </div>
  )
}

export default function Markers(p: Props) {
  const { ctx, display, visible } = p
  const onFloor = (f: string) => visible.has(f)
  const inside = (f: string) => !f || p.open.has(f)
  return (
    <>
      {display.pois && display.poiKinds.entrance && !p.walking && p.entrances.filter((e) => onFloor(e.floor)).map((e) => (
        <FloorFollower key={e.id} ctx={ctx} floor={e.floor}>
          <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={[e.pos[0], e.pos[1] + 3.2, e.pos[2]]} center zIndexRange={[20, 0]}>
            <div className={cn('pointer-events-auto grid size-[30px] cursor-default select-none place-items-center rounded-full border-[2.5px] border-white text-sm font-extrabold text-white shadow-[0_2px_6px_rgba(0,0,0,.35)] bg-[#1c7ed6]', e.main && 'size-[34px] bg-[#e8590c] text-base')} title={`${e.name} · ширина ${e.width} м`}>{e.label}</div>
          </Html>
          <Line points={[[e.pos[0], e.pos[1] + 0.05, e.pos[2]], [e.pos[0], e.pos[1] + 2.6, e.pos[2]]]} color="#1c7ed6" lineWidth={1.5} transparent opacity={0.6} />
        </FloorFollower>
      ))}
      {display.pois && p.pois.filter((x) => display.poiKinds[x.kind] && inside(x.floor)).map((x, i) => (
        <FloorFollower key={`poi${i}`} ctx={ctx} floor={x.floor}>
          <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={[x.pos[0], x.pos[1] + 1.8, x.pos[2]]} center zIndexRange={[18, 0]}>
            <div className={cn('pointer-events-auto grid size-[30px] cursor-default select-none place-items-center rounded-full border-[2.5px] border-white text-sm font-extrabold text-white shadow-[0_2px_6px_rgba(0,0,0,.35)] size-6 border-2 text-[13px]', x.kind === 'lift' ? 'bg-[#7048e8]' : 'bg-[#495057]')} title={x.kind === 'stair' ? 'Лестница' : 'Лифт'}>{POI_ICON[x.kind]}</div>
          </Html>
        </FloorFollower>
      ))}
      {display.pois && display.poiKinds.marker && p.markers.filter((m) => inside(m.floor)).map((m) => {
        const el = (
          <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={[m.pos[0], m.pos[1] + 0.2, m.pos[2]]} zIndexRange={[25, 0]} style={{ transform: 'translate(-50%, -100%)' }}>
            {/* Html renders in a root of its own: the hints need their provider here */}
            <TooltipProvider>
              <Tip label={p.openPin === m.id ? null : 'Полный текст метки; там же её можно удалить'}>
                <div className={pin} onClick={() => p.onPin(p.openPin === m.id ? null : m.id)}>
                  <span className={pinIcon}>📍</span>{m.label || m.text ? <b className={pinLabel}>{m.label || m.text}</b> : null}
                  {p.openPin === m.id && (
                    <PinCard text={m.text || 'Метка'} what="Метка" onDelete={() => p.onDeletePin('markers', m.id)} />
                  )}
                </div>
              </Tip>
            </TooltipProvider>
          </Html>
        )
        return m.floor ? <FloorFollower key={m.id} ctx={ctx} floor={m.floor}>{el}</FloorFollower> : <group key={m.id}>{el}</group>
      })}
      {display.comments && p.comments.filter((c) => inside(c.floor)).map((c) => {
        const el = (
          <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={c.pos} zIndexRange={[26, 0]} style={{ transform: 'translate(-4px, -100%)' }}>
            <TooltipProvider>
              <Tip label={p.openPin === c.id ? null : 'Текст комментария и время; там же его можно удалить'}>
                <div className={pin} onClick={() => p.onPin(p.openPin === c.id ? null : c.id)}>
                  <span className={pinIcon}>💬</span>
                  {p.openPin === c.id && (
                    <PinCard text={c.text} what="Комментарий" when={c.created ? new Date(c.created * 1000).toLocaleString('ru') : undefined}
                      onDelete={() => p.onDeletePin('comments', c.id)} />
                  )}
                </div>
              </Tip>
            </TooltipProvider>
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
            <Html portal={htmlLayer as React.RefObject<HTMLElement>} position={p.route.pts[Math.floor(p.route.pts.length / 2)]} center style={{ pointerEvents: 'none' }} zIndexRange={[22, 0]}>
              <div className="rounded-full bg-[#1c7ed6] px-2.5 py-0.5 text-[12.5px] font-bold whitespace-nowrap text-white shadow-[0_2px_6px_rgba(0,0,0,.25)] select-none">{p.route.length.toFixed(0)} м · ~{Math.max(1, Math.round(p.route.length / 1.3 / 60))} мин</div>
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
