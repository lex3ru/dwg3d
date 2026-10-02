import { Crosshair, Flag, MapPinned, X } from 'lucide-react'
import { useMemo } from 'react'
import type { FloorMeta, Layer, Result, RoomMeta } from '@/api'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { TreeObject } from '../SceneTree'

/**
 * The selected room: type, area, floor, what stands in it (objects of all
 * shown layers, by layer) and a route from or to it.
 */
export default function RoomInspector({ room, floor, result, objects, layers, onClose, onFly, onRoute, onObject }: {
  room: RoomMeta
  floor: FloorMeta
  result: Result
  /** the objects in this room, of the shown layers */
  objects: TreeObject[]
  layers: Layer[]
  onClose: () => void
  onFly: () => void
  onRoute: (end: 'from' | 'to') => void
  onObject: (o: TreeObject) => void
}) {
  const t = result.room_types?.find((x) => x.type === (room.type ?? 'other'))
  const byLayer = useMemo(() => {
    const m = new Map<string, TreeObject[]>()
    for (const o of objects) m.set(o.layer, [...(m.get(o.layer) ?? []), o])
    return [...m.entries()]
  }, [objects])
  return (
    <div className="grid gap-4 p-3 text-sm">
      <div className="flex items-start gap-2">
        <i className="mt-1 size-3.5 shrink-0 rounded-[4px] border border-black/10" style={{ background: t?.color ?? '#ece6da' }} />
        <div className="min-w-0 flex-1">
          <b className="block truncate text-base">{room.name || t?.label || 'Помещение'}</b>
          <small className="text-xs text-muted-foreground">{t?.label ?? 'Прочие'}</small>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Снять выделение" onClick={onClose}><X /></Button>
      </div>
      <dl className="m-0 grid grid-cols-2 gap-2">
        <div className="rounded-md bg-secondary p-2"><dt className="text-xs text-muted-foreground">Площадь</dt><dd className="m-0 font-medium">{room.area.toFixed(1)} м²</dd></div>
        <div className="rounded-md bg-secondary p-2"><dt className="text-xs text-muted-foreground">Этаж</dt><dd className="m-0 truncate font-medium">{floor.name}</dd></div>
      </dl>
      <div className="flex flex-wrap gap-1.5">
        <Button variant="outline" size="sm" onClick={onFly}><Crosshair /> Показать</Button>
        <Button variant="outline" size="sm" onClick={() => onRoute('from')} title="Путь A→B: начало здесь"><MapPinned /> Путь отсюда</Button>
        <Button variant="outline" size="sm" onClick={() => onRoute('to')} title="Путь A→B: конец здесь"><Flag /> Сюда</Button>
      </div>
      <section className="grid gap-1.5">
        <b className="text-xs">В помещении {objects.length ? <span className="font-normal text-muted-foreground">· {objects.length}</span> : null}</b>
        {!objects.length && <p className="m-0 text-xs text-muted-foreground">Объектов показанных слоёв здесь нет.</p>}
        {byLayer.map(([layer, list]) => (
          <div key={layer} className="grid gap-0.5">
            <small className="text-[11px] text-muted-foreground">{layers.find((l) => l.id === layer)?.name ?? 'Без слоя'}</small>
            <ul className="m-0 grid list-none gap-px p-0">
              {list.map((o) => (
                <li key={o.id}>
                  <button className="flex w-full cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-1.5 py-1 text-left text-xs text-foreground hover:bg-secondary"
                    onClick={() => onObject(o)}>
                    <i className={cn('size-2 shrink-0', o.kind === 'item' ? 'rounded-[2px]' : 'rounded-full')} style={{ background: o.color ?? '#adb5bd' }} />
                    <span className="min-w-0 flex-1 truncate">{o.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  )
}
