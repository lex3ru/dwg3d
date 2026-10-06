import { AlertTriangle, DoorOpen, FileStack, Layers, Map as MapIcon, QrCode, Search } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { getCabinet, type Asset, type Building, type Cabinet, type Me, type TreeFloor } from '../api'
import { Button } from '../components/ui/button'
import { to } from '../shell/route'
import { useEvents } from '../stream'
import { StateBadge } from './Assets'

/** «Кабинет» of a building: what needs attention, my rooms, the objects I answer for, a search and the QR scanner. */
export function Home({ me, building, floors, admin }: { me: Me; building: Building; floors: TreeFloor[]; admin: boolean }) {
  const rooms = floors.reduce((n, f) => n + f.rooms.length, 0)
  const area = floors.reduce((n, f) => n + f.rooms.reduce((a, r) => a + r.area, 0), 0)
  const [cabinet, setCabinet] = useState<Cabinet | null>(null)
  const [q, setQ] = useState('')
  const load = useCallback(() => { getCabinet(building.id).then(setCabinet, () => setCabinet(null)) }, [building.id])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('assets.') || event.type.startsWith('access.')) load() })
  const stat = (label: string, value: string, href: string, Icon: typeof Layers) => (
    <a href={href} className="rounded-lg border bg-card p-4 hover:border-primary">
      <div className="flex items-center gap-1.5 text-sm text-muted-foreground"><Icon className="size-4" /> {label}</div>
      <div className="mt-1 text-2xl font-medium">{value}</div>
    </a>
  )
  const place = (a: Asset) => {
    for (const f of floors) { const r = f.rooms.find(x => x.id === a.room_id); if (r) return `${f.level ?? ''} эт. · ${r.name || 'без названия'}` }
    return ''
  }
  const list = (items: Asset[], testid: string) => (
    <ul className="divide-y rounded-lg border bg-card text-sm" data-testid={testid}>
      {items.map(a => (
        <li key={a.id}>
          <a href={to.assets(building.id, a.id)} data-asset={a.inventory_no} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-secondary">
            <span className="min-w-40 flex-1"><span className="font-medium">{a.type_name}</span><span className="ml-2 text-muted-foreground">{a.inventory_no}</span></span>
            <span className="text-muted-foreground max-sm:hidden">{place(a)}</span>
            {a.needs_placement && <span className="text-xs text-warning">разместить</span>}
            {a.needs_fill && <span className="text-xs text-warning">заполнить</span>}
            <StateBadge a={a} />
          </a>
        </li>
      ))}
    </ul>
  )
  return (
    <section className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">{building.name}</h1>
        {building.address && <p className="text-sm text-muted-foreground">{building.address}</p>}
      </div>
      {floors.length === 0 ? (
        <div className="rounded-lg border border-dashed bg-card px-6 py-12 text-center">
          <p className="font-medium">В здании пока нет этажей</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
            {admin ? <>Загрузите поэтажные планы в разделе <a className="text-primary" href={to.drawings(building.id)}>«Чертежи»</a>.</>
              : 'Администратор здания ещё не загрузил чертежи.'}
          </p>
        </div>
      ) : (
        <>
          <form className="flex flex-wrap gap-2" role="search" onSubmit={e => { e.preventDefault(); location.hash = to.assets(building.id, undefined, q.trim()) }}>
            <div className="relative min-w-48 flex-1">
              <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
              <input value={q} onChange={e => setQ(e.target.value)} placeholder="Инвентарный номер или название" aria-label="Найти объект"
                className="h-8 w-full rounded-md border bg-card pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
            </div>
            <Button type="submit" size="sm" variant="outline">Найти</Button>
            <Button asChild size="sm" variant="outline"><a href={to.scan}><QrCode className="size-4" /> Сканировать QR</a></Button>
          </form>
          <div className="grid gap-3 sm:grid-cols-3" data-testid="summary">
            {stat('Этажи', String(floors.length), to.plan(building.id), Layers)}
            {stat('Помещения', String(rooms), to.rooms(building.id), DoorOpen)}
            {stat('Площадь помещений', `${Math.round(area).toLocaleString('ru')} м²`, to.plan(building.id), MapIcon)}
          </div>
          {cabinet && cabinet.attention.length > 0 && (
            <div>
              <h2 className="mb-1.5 flex items-center gap-1.5 text-sm font-medium"><AlertTriangle className="size-4 text-warning" /> Требует внимания · {cabinet.attention.length}</h2>
              {list(cabinet.attention, 'attention')}
            </div>
          )}
          {cabinet && !cabinet.whole && (
            <div>
              <h2 className="mb-1.5 text-sm font-medium">Мои помещения · {cabinet.rooms.length}</h2>
              {cabinet.rooms.length === 0 ? <p className="text-sm text-muted-foreground">Прав на помещения пока нет.</p> : (
                <ul className="divide-y rounded-lg border bg-card text-sm" data-testid="my-rooms">
                  {cabinet.rooms.map(r => (
                    <li key={r.id}>
                      <a href={to.rooms(building.id, r.id)} className="flex items-center gap-3 px-3 py-2 hover:bg-secondary">
                        <span className="min-w-0 flex-1 truncate">{r.name || <span className="text-muted-foreground">Без названия</span>}</span>
                        <span className="shrink-0 text-muted-foreground">{r.floor_name}</span>
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {cabinet && cabinet.person_id && (
            <div>
              <h2 className="mb-1.5 text-sm font-medium">Объекты, за которые я отвечаю · {cabinet.mine.length}</h2>
              {cabinet.mine.length === 0 ? <p className="text-sm text-muted-foreground">Пока ни одного.</p> : list(cabinet.mine, 'mine')}
            </div>
          )}
          {cabinet && cabinet.partial.length > 0 && (
            <p role="status" className="text-sm text-muted-foreground">Часть данных недоступна: не отвечает {cabinet.partial.join(', ')}.</p>
          )}
          {!cabinet && <p className="text-sm text-muted-foreground">{me.person ? 'Загрузка…' : ''}</p>}
        </>
      )}
      {admin && floors.length > 0 && (
        <a href={to.drawings(building.id)} className="inline-flex items-center gap-1.5 text-sm text-primary">
          <FileStack className="size-4" /> Чертежи здания
        </a>
      )}
    </section>
  )
}
