import { Search } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { listAssets, STATES, type Asset, type AssetState, type TreeFloor } from '../api'
import { Badge } from '../components/ui/badge'
import { cn } from '../lib/utils'
import { to } from '../shell/route'
import { useEvents } from '../stream'

const select = 'h-8 rounded-md border bg-card px-2 text-sm'

export function StateBadge({ a }: { a: Asset }) {
  return <Badge variant={a.state === 'in_use' ? 'default' : a.state === 'faulty' ? 'destructive' : 'warning'}>{STATES[a.state]}</Badge>
}

/** The objects of a building the user may see: by number, type, state; what needs attention. */
export function Assets({ building, floors, selected }: { building: string; floors: TreeFloor[]; selected?: string }) {
  const [items, setItems] = useState<Asset[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState('')
  const [state, setState] = useState<AssetState | ''>('')
  const [attention, setAttention] = useState<'' | 'needs_fill' | 'needs_placement'>('')
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    listAssets({ building_id: building, q, state, [attention || 'x']: attention ? 'true' : undefined, limit: '300' })
      .then(r => { setItems(r.items); setTotal(r.total); setError(null) }, (e: Error) => setError(e.message))
  }, [building, q, state, attention])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('assets.')) load() })
  const room = (a: Asset) => {
    for (const f of floors) { const r = f.rooms.find(x => x.id === a.room_id); if (r) return `${f.level ?? ''} эт. · ${r.name || 'без названия'}` }
    return ''
  }
  return (
    <section>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-1 text-xl font-semibold">Объекты</h1>
        <div className="relative w-56 max-w-full">
          <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Номер или название" aria-label="Поиск объекта"
            className="h-8 w-full rounded-md border bg-card pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </div>
        <select className={select} value={state} onChange={e => setState(e.target.value as AssetState | '')} aria-label="Состояние">
          <option value="">любое состояние</option>
          {Object.entries(STATES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className={select} value={attention} onChange={e => setAttention(e.target.value as typeof attention)} aria-label="Требует внимания">
          <option value="">все</option>
          <option value="needs_fill">требует заполнения</option>
          <option value="needs_placement">требует размещения</option>
        </select>
        <span className="text-sm text-muted-foreground" data-testid="assets-total">{total}</span>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {items.length === 0 ? (
        <p className="mt-6 text-sm text-muted-foreground">
          {q || state || attention ? 'Ничего не найдено.' : 'Объектов пока нет. Их ставит на план администратор здания — в разделе «План».'}
        </p>
      ) : (
        <ul className="mt-4 divide-y rounded-lg border bg-card text-sm" data-testid="assets">
          {items.map(a => (
            <li key={a.id}>
              <a href={to.assets(building, a.id)} aria-current={a.id === selected ? 'true' : undefined} data-asset={a.inventory_no}
                className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-secondary', a.id === selected && 'bg-accent')}>
                <span className="min-w-40 flex-1"><span className="font-medium">{a.type_name}</span>
                  <span className="ml-2 text-muted-foreground">{a.inventory_no}</span></span>
                <span className="text-muted-foreground max-sm:hidden">{room(a)}</span>
                {a.needs_placement && <Badge variant="warning">разместить</Badge>}
                {a.needs_fill && <Badge variant="warning">заполнить</Badge>}
                <StateBadge a={a} />
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
