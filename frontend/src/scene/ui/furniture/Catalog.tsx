import { Search } from 'lucide-react'
import { useState } from 'react'
import type { FloorMeta, ViewSettings } from '@/scene/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Tip } from '@/components/ui/tooltip'
import { CATALOG, CATEGORIES, catalogError, type CatalogItem } from '@/scene/furniture/catalog'
import { cn } from '@/lib/utils'
import { cm, ItemSymbol } from './parts'

/**
 * The catalog of the layer being edited (its categories only), in the left
 * dock: drag an item onto the plan, or click it and then click the plan.
 */
export default function Catalog(p: {
  /** catalog categories the layer takes; null: any */
  categories: string[] | null
  floor: FloorMeta | null
  placing: CatalogItem | null
  onPick: (c: CatalogItem, drag: boolean) => void
  locked: boolean
  unplaced: NonNullable<ViewSettings['furniture_unplaced']>
  onUnplaced: (ids: string[], toFloor: string | null) => void
}) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('all')
  const own = CATALOG.filter((c) => !p.categories || p.categories.includes(c.cat))
  const cats = CATEGORIES.filter((c) => own.some((x) => x.cat === c.id))
  const s = q.trim().toLowerCase()
  const found = own.filter((c) => (cat === 'all' || c.cat === cat) && (!s || `${c.name} ${c.tags ?? ''}`.toLowerCase().includes(s)))
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
      {p.unplaced.length > 0 && p.floor && (
        <section className="m-2 grid gap-1.5 rounded-md border border-warning/40 bg-warning/10 p-2 text-xs">
          <b>Без этажа после перестроения: {p.unplaced.length} шт.</b>
          <span className="text-muted-foreground">Этаж {[...new Set(p.unplaced.map((u) => `«${u._anchor?.name || u.floor}»`))].join(', ')} не найден в новой сборке.
            Координаты сохранены — предметы можно перенести на текущий этаж ({p.floor.name}).</span>
          <div className="flex gap-1.5">
            <Button size="sm" disabled={p.locked} onClick={() => p.onUnplaced(p.unplaced.map((u) => u.id), p.floor!.id)}
              hint={p.locked ? 'Недоступно, пока модель собирается' : `Поставить их на этаж «${p.floor.name}» с прежними координатами`}>Перенести сюда</Button>
            <Button size="sm" variant="ghost" className="text-destructive" disabled={p.locked} onClick={() => p.onUnplaced(p.unplaced.map((u) => u.id), null)}
              hint={p.locked ? 'Недоступно, пока модель собирается' : 'Убрать их из расстановки; объект учёта так не удалить — он списывается в своей карточке'}>Удалить</Button>
          </div>
        </section>
      )}
      <ul className="m-0 min-h-0 flex-1 list-none overflow-y-auto p-1">
        {found.map((c) => (
          <li key={c.id} className={cn('flex cursor-grab items-center gap-2 rounded-md px-2 py-1 select-none hover:bg-secondary', p.placing?.id === c.id && 'bg-accent text-accent-foreground')}
            onPointerDown={(e) => { if (e.button === 0 && p.floor && !p.locked) { e.preventDefault(); p.onPick(c, true) } }}>
            <ItemSymbol c={c} size={30} />
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
        {!found.length && <li className="p-3 text-center text-xs text-muted-foreground">Ничего не найдено</li>}
      </ul>
    </div>
  )
}
