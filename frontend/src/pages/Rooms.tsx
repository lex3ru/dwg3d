import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { TreeFloor } from '../api'
import { cn } from '../lib/utils'
import { to } from '../shell/route'

/** The rooms of a building by floor, with a search; a chosen room opens its card. */
export function Rooms({ building, floors, selected, initialQuery }: {
  building: string; floors: TreeFloor[]; selected?: string; initialQuery?: string
}) {
  const [q, setQ] = useState(initialQuery ?? '')
  const needle = q.trim().toLowerCase()
  const shown = useMemo(() => floors
    .map(f => ({ ...f, rooms: f.rooms.filter(r => !needle || `${r.name} ${r.number ?? ''}`.toLowerCase().includes(needle)) }))
    .filter(f => f.rooms.length > 0), [floors, needle])
  const total = shown.reduce((n, f) => n + f.rooms.length, 0)
  return (
    <section>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Помещения</h1>
        <div className="relative w-64 max-w-full">
          <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Название или номер" aria-label="Поиск помещения"
            className="h-8 w-full rounded-md border bg-card pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </div>
        <span className="text-sm text-muted-foreground" data-testid="rooms-total">{total}</span>
      </div>
      {shown.length === 0 && (
        <p className="mt-6 text-sm text-muted-foreground">{needle ? 'Ничего не найдено. Проверьте название или номер.' : 'В здании пока нет помещений.'}</p>
      )}
      {shown.map(f => (
        <div key={f.id} className="mt-5">
          <h2 className="mb-1.5 text-sm font-medium text-muted-foreground">{f.name || `Этаж ${f.level ?? ''}`} · {f.rooms.length}</h2>
          <ul className="divide-y rounded-lg border bg-card text-sm" data-testid="rooms">
            {f.rooms.map(r => (
              <li key={r.id}>
                <a href={to.rooms(building, r.id)} aria-current={r.id === selected ? 'true' : undefined}
                  className={cn('flex items-center gap-3 px-3 py-2 hover:bg-secondary', r.id === selected && 'bg-accent')}>
                  <span className="min-w-0 flex-1 truncate">{r.name || <span className="text-muted-foreground">Без названия</span>}</span>
                  <span className="shrink-0 text-muted-foreground tabular-nums">{r.area.toLocaleString('ru')} м²</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}
