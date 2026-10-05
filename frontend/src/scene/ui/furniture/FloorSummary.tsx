import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { FloorMeta, Layer, PlacedItem } from '@/scene/api'
import { catalogItem } from '@/scene/furniture/catalog'
import { roomAt, type Issue, type PlanIndex, type RoomCover } from '@/scene/furniture/geom'
import { cn } from '@/lib/utils'

const pct = (v: number) => `${Math.round(v * 100)}%`

/**
 * The layer being edited on the active floor, while nothing is selected:
 * items by room, their issues, camera coverage of the rooms.
 */
export default function FloorSummary(p: {
  layer: Layer
  floor: FloorMeta | null
  items: PlacedItem[]                  // on this floor, all shown layers
  plan: PlanIndex | null
  issues: Map<string, Issue[]>
  roomCover: RoomCover[]
  showZones: boolean
  onZones: (v: boolean) => void
  camViews: boolean
  onCamViews: (v: boolean) => void
  onSelect: (id: string) => void
}) {
  const mine = useMemo(() => p.items.filter((i) => i.layer === p.layer.id || !i.layer), [p.items, p.layer.id])
  const withIssues = mine.filter((i) => p.issues.get(i.id)?.length)
  const byRoom = useMemo(() => {
    const m = new Map<string, PlacedItem[]>()
    for (const it of mine) {
      const r = (p.plan && roomAt(p.plan, it.at)) || 'Вне помещений'
      m.set(r, [...(m.get(r) ?? []), it])
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], 'ru'))
  }, [mine, p.plan])
  const [closed, setClosed] = useState<Set<string>>(new Set())
  const cams = mine.some((i) => catalogItem(i.item).cam)
  return (
    <div className="grid gap-3 p-3 text-sm">
      <div>
        <b className="block">{p.layer.name}</b>
        <small className="text-xs text-muted-foreground">{p.floor?.name ?? 'Этаж не выбран'} · {mine.length} шт. на этаже</small>
      </div>
      <p className="m-0 text-xs text-muted-foreground">Перетащите предмет из каталога слева на план. Щелчок по предмету — его свойства здесь.</p>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" className="accent-primary" checked={p.showZones} onChange={(e) => p.onZones(e.target.checked)} /> Показывать зоны обслуживания</label>
      {withIssues.length > 0 && (
        <button className="flex cursor-pointer items-center gap-1.5 rounded-md border-0 bg-destructive/10 p-2 text-left text-xs text-destructive hover:bg-destructive/15"
          onClick={() => p.onSelect(withIssues[0].id)}>
          <AlertTriangle className="size-3.5 shrink-0" /> Замечания у {withIssues.length} шт. — показать
        </button>
      )}
      {cams && (
        <section className="grid gap-1.5">
          <div className="flex items-center gap-2">
            <b className="flex-1 text-xs">Видеонаблюдение</b>
            <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" className="accent-primary" checked={p.camViews} onChange={(e) => p.onCamViews(e.target.checked)} /> обзор</label>
          </div>
          <small className="text-xs text-muted-foreground">Доля площади помещения в поле зрения (в скобках — где различимы лица)</small>
          <ul className="m-0 grid list-none gap-0.5 p-0">
            {p.roomCover.map((r, i) => (
              <li key={i} className={cn('flex gap-2 text-xs', r.covered < 0.6 && 'text-destructive')}>
                <span className="min-w-0 flex-1 truncate">{r.name}</span><b>{pct(r.covered)}</b><small className="text-muted-foreground">({pct(r.ident)})</small>
              </li>
            ))}
          </ul>
        </section>
      )}
      {byRoom.length > 0 && (
        <section className="grid gap-0.5">
          <b className="text-xs">По помещениям</b>
          {byRoom.map(([room, list]) => {
            const open = !closed.has(room)
            return (
              <div key={room}>
                <button className="flex w-full cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-1 py-1 text-left text-xs text-foreground hover:bg-secondary"
                  onClick={() => setClosed((c) => { const n = new Set(c); if (n.has(room)) n.delete(room); else n.add(room); return n })}>
                  {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                  <span className="flex-1 truncate">{room}</span><small className="text-muted-foreground">{list.length}</small>
                </button>
                {open && (
                  <ul className="m-0 ml-4 grid list-none p-0">
                    {list.map((it) => (
                      <li key={it.id}>
                        <button className="flex w-full cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-1.5 py-0.5 text-left text-xs text-foreground hover:bg-secondary"
                          onClick={() => p.onSelect(it.id)}>
                          {p.issues.get(it.id)?.length ? <i className="size-1.5 shrink-0 rounded-full bg-destructive" /> : null}
                          <span className="truncate">{catalogItem(it.item).name}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
        </section>
      )}
    </div>
  )
}
