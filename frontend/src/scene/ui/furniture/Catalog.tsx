import { ArrowRight, Search } from 'lucide-react'
import { useState } from 'react'
import type { FloorMeta } from '@/scene/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Tip } from '@/components/ui/tooltip'
import { CATALOG, CATEGORIES, catalogError, type CatalogItem } from '@/scene/furniture/catalog'
import { cn } from '@/lib/utils'
import { cm, ItemThumb } from './parts'

/**
 * The catalog of the layer being edited (its categories only), in the left
 * dock: drag an item onto the plan, or click it and then click the plan.
 * What the search finds in other layers' sections (a light while «Объекты
 * учёта» is edited) is not placed from here: it is named with its layer, to go
 * and edit that one.
 */
export default function Catalog(p: {
  /** catalog categories the layer takes; null: any */
  categories: string[] | null
  floor: FloorMeta | null
  placing: CatalogItem | null
  onPick: (c: CatalogItem, drag: boolean) => void
  locked: boolean
  /** the layer an item of another section belongs in, next to the one being edited */
  layerOf: (c: CatalogItem) => { id: string; name: string } | null
  onGoLayer: (id: string) => void
}) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('all')
  const own = CATALOG.filter((c) => !p.categories || p.categories.includes(c.cat))
  const cats = CATEGORIES.filter((c) => own.some((x) => x.cat === c.id))
  const s = q.trim().toLowerCase()
  const hit = (c: CatalogItem) => !s || `${c.name} ${c.tags ?? ''}`.toLowerCase().includes(s)
  const found = own.filter((c) => (cat === 'all' || c.cat === cat) && hit(c))
  // found in the sections of other layers, by the layer each goes to
  const away = new Map<string, { name: string; items: CatalogItem[] }>()
  if (s && p.categories) {
    for (const c of CATALOG) {
      if (p.categories.includes(c.cat) || !hit(c)) continue
      const l = p.layerOf(c)
      if (!l) continue
      if (!away.has(l.id)) away.set(l.id, { name: l.name, items: [] })
      away.get(l.id)!.items.push(c)
    }
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="grid shrink-0 gap-2 border-b border-border p-2">
        <div className="relative">
          <Search className="pointer-events-none absolute top-2 left-2 size-3.5 text-muted-foreground" />
          <Tip label="Ищет по названию и тегам типа, среди разделов, которые берёт этот слой" side="bottom">
            <Input className="h-7 pl-7 text-xs" value={q} placeholder="Поиск в каталоге" onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.stopPropagation()} />
          </Tip>
        </div>
        {cats.length > 1 && (
          <Tip label="Оставить в списке один раздел каталога; в скобках — сколько в нём типов" side="bottom">
            <Select className="h-7 text-xs" value={cat} onChange={(e) => setCat(e.target.value)}>
              <option value="all">Все категории ({own.length})</option>
              {cats.map((c) => <option key={c.id} value={c.id}>{c.name} ({own.filter((x) => x.cat === c.id).length})</option>)}
            </Select>
          </Tip>
        )}
      </div>
      {catalogError && <p className="m-2 rounded-md bg-warning/15 p-2 text-xs text-warning">{catalogError}. Обновите страницу, когда сервер будет доступен.</p>}
      {p.locked && <p className="m-2 rounded-md bg-accent p-2 text-xs text-accent-foreground">Идёт перестроение модели — расстановку можно будет менять после него.</p>}
      {!p.floor && <p className="m-2 text-xs text-muted-foreground">Выберите этаж в дереве или на ленте этажей.</p>}
      <ul className="m-0 min-h-0 flex-1 list-none overflow-y-auto p-1">
        {found.map((c) => (
          <li key={c.id} className={cn('flex cursor-grab items-center gap-2 rounded-md px-2 py-1 select-none hover:bg-secondary', p.placing?.id === c.id && 'bg-accent text-accent-foreground')}
            onPointerDown={(e) => { if (e.button === 0 && p.floor && !p.locked) { e.preventDefault(); p.onPick(c, true) } }}>
            <ItemThumb c={c} size={40} />
            {/* the hint on the text, not the row: the row's pointerdown (a drag) would keep it open over the plan */}
            <Tip side="right" label={!p.floor ? 'Сначала выберите этаж в дереве или на ленте этажей'
              : 'Перетащите на план или щёлкните, а затем место на плане; R и Q поворачивают, Esc отменяет'}>
              <div className="min-w-0 leading-tight">
                <div className="truncate text-sm">{c.name}</div>
                <small className="text-[11px] text-muted-foreground">{cm(c.w)}×{cm(c.d)}×{cm(c.h)} см{c.elev ? ` · на высоте ${cm(c.elev)}` : ''}</small>
              </div>
            </Tip>
          </li>
        ))}
        {!found.length && <li className="p-3 text-center text-xs text-muted-foreground">{away.size ? 'В этом слое ничего не найдено' : 'Ничего не найдено'}</li>}
      </ul>
      {away.size > 0 && (
        <div className="grid shrink-0 gap-1.5 border-t border-border p-2 text-xs">
          {[...away].map(([id, l]) => (
            <div key={id} className="flex items-center gap-2 rounded-md bg-secondary p-2">
              <div className="min-w-0 flex-1">
                <div>В слое «{l.name}»: {l.items.length}</div>
                <div className="truncate text-muted-foreground">{l.items.slice(0, 3).map((c) => c.name).join(', ')}{l.items.length > 3 ? '…' : ''}</div>
              </div>
              <Button size="sm" variant="outline" className="shrink-0" onClick={() => p.onGoLayer(id)}
                hint={`Эти позиции ставятся в слой «${l.name}»: перейти к его редактированию`}>
                Перейти <ArrowRight />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
