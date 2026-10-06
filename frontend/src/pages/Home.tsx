import { AlertTriangle, CheckCircle2, ChevronRight, DoorOpen, FileStack, Layers, Map as MapIcon, QrCode, Search } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { getCabinet, listAssets, listPlaced, listVariants, type Asset, type Building, type Cabinet, type Me, type TreeFloor } from '../api'
import { Button } from '../components/ui/button'
import { Tip } from '../components/ui/tooltip'
import { to } from '../shell/route'
import { useEvents } from '../stream'
import { NeedsMark, StateBadge } from './Assets'

/** What in the building needs the administrator's hand, counted, each with the way to it. */
type Task = { key: string; count: number; label: string; href: string; hint: string }

function useTasks(building: string, on: boolean): Task[] | null {
  const [tasks, setTasks] = useState<Task[] | null>(null)
  const load = useCallback(() => {
    if (!on) return
    const total = (params: Record<string, string>) =>
      listAssets({ building_id: building, limit: '1', ...params }).then(r => r.total, () => 0)
    Promise.all([
      total({ needs_placement: 'true' }), total({ needs_fill: 'true' }), total({ state: 'faulty' }),
      listPlaced(building).then(d => d.filter(x => x.revision?.status === 'draft').length, () => 0),
      listVariants(building).then(v => v.filter(x => x.status === 'draft' && x.stale).length, () => 0),
    ]).then(([place, fill, faulty, drafts, stale]) => setTasks([
      { key: 'place', count: place, label: 'Объекты без места', href: to.assetsWhere(building, { attention: 'needs_placement' }),
        hint: 'Их помещение снято новой сборкой чертежа или списан контейнер, где они лежали: поставьте их на план заново' },
      { key: 'fill', count: fill, label: 'Объекты с незаполненными свойствами', href: to.assetsWhere(building, { attention: 'needs_fill' }),
        hint: 'Не заполнены обязательные свойства их типа или значение не того вида: откройте карточку и поправьте' },
      { key: 'faulty', count: faulty, label: 'Неисправные объекты', href: to.assetsWhere(building, { state: 'faulty' }),
        hint: 'Отмечены неисправными: отправьте в ремонт, почините или спишите' },
      { key: 'drafts', count: drafts, label: 'Сборки чертежей ждут проверки', href: to.drawings(building),
        hint: 'Новая сборка снимет помещения: проверьте сопоставление и опубликуйте или отбросьте её' },
      { key: 'stale', count: stale, label: 'Устаревшие варианты', href: to.variants(building),
        hint: 'После их составления объекты изменились в учёте: при применении часть операций будет отклонена' },
    ].filter(t => t.count > 0)))
  }, [building, on])
  useEffect(load, [load])
  useEvents(event => { if (/^(assets|buildings|import|planning)\./.test(event.type)) load() })
  return tasks
}

/** «Обзор» of a building, where one starts: for its administrator what needs their hand, for anyone their
 * rooms and the objects they answer for and what of it needs attention; a search and the QR scanner. */
export function Home({ me, building, floors, admin }: { me: Me; building: Building; floors: TreeFloor[]; admin: boolean }) {
  const rooms = floors.reduce((n, f) => n + f.rooms.length, 0)
  const area = floors.reduce((n, f) => n + f.rooms.reduce((a, r) => a + r.area, 0), 0)
  const [cabinet, setCabinet] = useState<Cabinet | null>(null)
  const tasks = useTasks(building.id, admin && floors.length > 0)
  const [q, setQ] = useState('')
  const load = useCallback(() => { getCabinet(building.id).then(setCabinet, () => setCabinet(null)) }, [building.id])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('assets.') || event.type.startsWith('access.')) load() })
  const stat = (label: string, value: string, href: string, Icon: typeof Layers, hint: string) => (
    <Tip label={hint}>
      <a href={href} className="rounded-lg border bg-card p-4 hover:border-primary">
        <div className="flex items-center gap-1.5 text-sm text-muted-foreground"><Icon className="size-4" /> {label}</div>
        <div className="mt-1 text-2xl font-medium">{value}</div>
      </a>
    </Tip>
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
            {a.needs_placement && <NeedsMark need="placement"><span className="text-xs text-warning">разместить</span></NeedsMark>}
            {a.needs_fill && <NeedsMark need="fill"><span className="text-xs text-warning">заполнить</span></NeedsMark>}
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
            {admin ? <>Загрузите поэтажные планы в разделе <Tip label="Загрузить DWG или DXF: из них соберутся этажи и помещения"><a className="text-primary" href={to.drawings(building.id)}>«Чертежи»</a></Tip>.</>
              : 'Администратор здания ещё не загрузил чертежи.'}
          </p>
        </div>
      ) : (
        <>
          <form className="flex flex-wrap gap-2" role="search" onSubmit={e => { e.preventDefault(); location.hash = to.assets(building.id, undefined, q.trim()) }}>
            <div className="relative min-w-48 flex-1">
              <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
              <Tip label="Ищется и по заводскому номеру; Enter откроет найденное в разделе «Объекты»">
                <input value={q} onChange={e => setQ(e.target.value)} placeholder="Инвентарный номер или название" aria-label="Найти объект"
                  className="h-8 w-full rounded-md border bg-card pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
              </Tip>
            </div>
            <Button type="submit" size="sm" variant="outline" hint="Открыть раздел «Объекты» с подходящими по номеру или названию">Найти</Button>
            <Button asChild size="sm" variant="outline" hint="Прочитать метку на объекте камерой и открыть его карточку; код можно ввести и вручную"><a href={to.scan}><QrCode className="size-4" /> Сканировать QR</a></Button>
          </form>
          <div className="grid gap-3 sm:grid-cols-3" data-testid="summary">
            {stat('Этажи', String(floors.length), to.plan(building.id), Layers, 'Открыть поэтажный план здания')}
            {stat('Помещения', String(rooms), to.rooms(building.id), DoorOpen, 'Открыть список помещений по этажам')}
            {stat('Площадь помещений', `${Math.round(area).toLocaleString('ru')} м²`, to.plan(building.id), MapIcon,
              'Сумма площадей всех помещений по чертежам; открыть план')}
          </div>
          {admin && tasks && (
            <div>
              <h2 className="mb-1.5 text-sm font-medium">Задачи по зданию</h2>
              {tasks.length === 0 ? (
                <p className="flex items-center gap-1.5 text-sm text-muted-foreground" data-testid="tasks"><CheckCircle2 className="size-4 text-success" /> Всё в порядке: ничего не ждёт ваших действий</p>
              ) : (
                <ul className="divide-y rounded-lg border bg-card text-sm" data-testid="tasks">
                  {tasks.map(t => (
                    <li key={t.key}>
                      <Tip label={t.hint}>
                        <a href={t.href} data-task={t.key} className="flex items-center gap-3 px-3 py-2 hover:bg-secondary">
                          <AlertTriangle className="size-4 shrink-0 text-warning" />
                          <span className="flex-1">{t.label}</span>
                          <span className="font-medium">{t.count}</span>
                          <ChevronRight className="size-4 text-muted-foreground" />
                        </a>
                      </Tip>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {!admin && cabinet && cabinet.attention.length > 0 && (
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
        <Tip label="Загрузка поэтажных планов DWG/DXF, их сборка в этажи и помещения, проверка новых сборок">
          <a href={to.drawings(building.id)} className="inline-flex items-center gap-1.5 text-sm text-primary">
            <FileStack className="size-4" /> Чертежи здания
          </a>
        </Tip>
      )}
    </section>
  )
}
