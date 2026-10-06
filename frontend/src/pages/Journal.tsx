import { useCallback, useEffect, useState } from 'react'
import { listEvents, peopleByIds, STATES, type AssetState, type JournalEvent, type TreeFloor } from '../api'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Tip } from '../components/ui/tooltip'
import { to } from '../shell/route'
import { useEvents } from '../stream'

const select = 'h-8 rounded-md border bg-card px-2 text-sm'
const KINDS: [string, string][] = [['', 'все события'], ['assets.', 'объекты'], ['buildings.', 'здание и помещения'],
  ['people.', 'люди'], ['access.', 'права'], ['catalog.', 'каталог'], ['import.', 'чертежи']]
const ROLES: Record<string, string> = { viewer: 'просмотр', responsible: 'ответственный', admin: 'администратор' }
const AREAS: Record<string, string> = { building: 'здание', floor: 'этаж', room: 'помещение', asset: 'объект' }

/** What happened, in words. */
function describe(e: JournalEvent): string {
  const d = e.data
  const state = (v: unknown) => STATES[v as AssetState] ?? String(v)
  switch (e.type) {
    case 'assets.asset.created': return 'объект поставлен на учёт'
    case 'assets.asset.changed': return `объект изменён: ${Object.keys((d.changes as object) ?? {}).join(', ')}`
    case 'assets.asset.moved': return 'объект перемещён'
    case 'assets.asset.state_changed': return `состояние: ${state(d.from)} → ${state(d.to)}`
    case 'assets.asset.responsible_changed': return d.to ? 'назначен ответственный' : 'ответственный снят'
    case 'assets.asset.retired': return 'объект списан'
    case 'assets.asset.file_added': return `файл приложен: ${d.name ?? ''}`
    case 'assets.asset.file_removed': return `файл убран: ${d.name ?? ''}`
    case 'buildings.building.created': return 'здание создано'
    case 'buildings.building.changed': return 'здание изменено'
    case 'buildings.building.deleted': return 'здание удалено'
    case 'buildings.revision.published': return 'опубликована сборка чертежа'
    case 'buildings.room.changed': return `помещение изменено: ${(d.fields as string[])?.join(', ') ?? ''}`
    case 'buildings.room.retired': return 'помещения больше нет'
    case 'buildings.floor.changed': return 'этаж изменён'
    case 'buildings.comment.created': return 'оставлен комментарий'
    case 'buildings.comment.resolved': return 'комментарий закрыт'
    case 'people.person.created': return 'человек добавлен в справочник'
    case 'people.person.changed': return `запись человека изменена: ${(d.fields as string[])?.join(', ') ?? ''}`
    case 'people.person.linked': return 'учётная запись связана с человеком'
    case 'people.person.unlinked': return 'учётная запись отвязана'
    case 'people.person.left': return 'человек выбыл'
    case 'people.person.assigned': return 'человек привязан к помещению'
    case 'people.person.unassigned': return 'человек отвязан от помещения'
    case 'access.grant.created': return `право выдано: ${ROLES[d.role as string] ?? d.role} — ${AREAS[(d.scope as { kind: string })?.kind] ?? ''}`
    case 'access.grant.revoked': return `право отозвано: ${ROLES[d.role as string] ?? d.role} — ${AREAS[(d.scope as { kind: string })?.kind] ?? ''}`
    case 'access.share.created': return `выдана ссылка для просмотра — ${AREAS[(d.scope as { kind: string })?.kind] ?? ''}${d.expires_at ? `, до ${new Date(d.expires_at as string).toLocaleDateString('ru')}` : ''}`
    case 'access.share.revoked': return `ссылка отозвана — ${AREAS[(d.scope as { kind: string })?.kind] ?? ''}`
    case 'access.share.opened': return `открыта ссылка для просмотра${d.note ? ` — ${d.note}` : ''}${d.address ? ` · адрес ${d.address}` : ''}`
    case 'buildings.revision.drafted': return 'собран черновик чертежа, ждёт проверки'
    case 'buildings.revision.discarded': return 'черновик чертежа отброшен'
    case 'buildings.room.merged': return 'помещения объединены'
    case 'buildings.room.split': return 'помещение разделено'
    case 'catalog.type.created': return 'в каталоге новый тип'
    case 'catalog.type.changed': return 'тип каталога изменён'
    case 'catalog.type.archived': return 'тип каталога убран в архив'
    case 'catalog.type.restored': return 'тип каталога возвращён из архива'
    case 'catalog.property_set.changed': return 'набор свойств каталога изменён'
    case 'import.drawing.uploaded': return 'чертёж загружен'
    case 'import.drawing.renamed': return 'чертёж переименован'
    case 'import.drawing.deleted': return 'чертёж удалён'
    case 'import.build.started': return 'началась сборка чертежа'
    case 'import.build.progress': return 'сборка чертежа идёт'
    case 'import.build.finished': return 'сборка чертежа завершена'
    case 'import.build.failed': return 'сборка чертежа не удалась'
    case 'planning.variant.created': return 'создан вариант расстановки'
    case 'planning.variant.applied': return 'вариант расстановки применён'
    case 'planning.variant.deleted': return 'вариант расстановки удалён'
    default: return 'событие системы'                  // a kind the interface does not know yet; the raw name stays in the tooltip
  }
}

/** The feed of a building: who did what and when, by kind and period; narrowed to a room, an object or a person by the address. */
export function Journal({ building, floors, filter }: { building: string; floors: TreeFloor[]; filter: Record<string, string> }) {
  const [items, setItems] = useState<JournalEvent[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [names, setNames] = useState<Record<string, string>>({})
  const [kind, setKind] = useState(filter.type ?? '')
  const [from, setFrom] = useState('')
  const [to_, setTo] = useState('')
  const [room, setRoom] = useState(filter.room ?? '')
  const [error, setError] = useState<string | null>(null)
  const params = useCallback((cursor?: string) => ({
    building_id: building, room_id: room || undefined, asset_id: filter.asset, person_id: filter.person, type: kind || undefined,
    from: from ? new Date(from).toISOString() : undefined, to: to_ ? new Date(`${to_}T23:59:59`).toISOString() : undefined,
    limit: '100', cursor,
  }), [building, room, filter.asset, filter.person, kind, from, to_])
  const load = useCallback(() => {
    listEvents(params()).then(async r => {
      setItems(r.items); setNext(r.next); setError(null)
      const ids = [...new Set(r.items.flatMap(e => [e.actor.person_id, e.person_id, (e.data.to as string | null), (e.data.person_id as string)]).filter((x): x is string => !!x))]
      if (ids.length) peopleByIds(ids).then(p => setNames(n => ({ ...n, ...Object.fromEntries(p.map(x => [x.id, x.full_name])) })), () => {})
    }, (e: Error) => setError(e.message))
  }, [params])
  useEffect(load, [load])
  useEvents(() => load())
  const more = () => {
    if (!next) return
    listEvents(params(next)).then(r => { setItems(x => [...x, ...r.items]); setNext(r.next) }, (e: Error) => setError(e.message))
  }
  const where = (e: JournalEvent) => {
    for (const f of floors) { const r = f.rooms.find(x => x.id === e.room_id); if (r) return r.name || 'помещение без названия' }
    return ''
  }
  const who = (e: JournalEvent) => e.type === 'access.share.opened' ? 'гость по ссылке' : e.actor.kind === 'service' ? 'система' : e.actor.person_id ? names[e.actor.person_id] ?? '…' : 'администратор системы'
  const link = (e: JournalEvent) => e.asset_id ? to.assets(building, e.asset_id) : e.room_id ? to.rooms(building, e.room_id) : null
  return (
    <section>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-1 text-xl font-semibold">Журнал</h1>
        <Tip label="Оставить в ленте события одного рода">
          <select className={select} value={kind} onChange={e => setKind(e.target.value)} aria-label="Вид события">
            {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Tip>
        <Tip label="Только то, что случилось в одном помещении: с его объектами, людьми и им самим">
          <select className={select} value={room} onChange={e => setRoom(e.target.value)} aria-label="Помещение">
            <option value="">всё здание</option>
            {floors.flatMap(f => f.rooms.map(r => <option key={r.id} value={r.id}>{f.name || f.level} · {r.name || `без названия, ${r.area.toLocaleString('ru')} м²`}</option>))}
          </select>
        </Tip>
        <Tip label="Начало периода, день включительно; пусто — с самого начала">
          <Input type="date" className="h-8 w-40" value={from} onChange={e => setFrom(e.target.value)} aria-label="С даты" />
        </Tip>
        <Tip label="Конец периода, день включительно; пусто — до сегодня">
          <Input type="date" className="h-8 w-40" value={to_} onChange={e => setTo(e.target.value)} aria-label="По дату" />
        </Tip>
      </div>
      {(filter.asset || filter.person) && (
        <p className="mt-1 text-sm text-muted-foreground">
          {filter.asset ? 'Только события объекта. ' : ''}{filter.person ? `Только события человека${names[filter.person] ? `: ${names[filter.person]}` : ''}. ` : ''}
          <Tip label="Снять отбор по объекту или человеку: события всего здания">
            <a className="text-primary" href={to.journal(building)}>Весь журнал</a>
          </Tip>
        </p>
      )}
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {items.length === 0 ? <p className="mt-6 text-sm text-muted-foreground">Событий нет.</p> : (
        <ul className="mt-4 divide-y rounded-lg border bg-card text-sm" data-testid="journal">
          {items.map(e => {
            const href = link(e)
            return (
              <li key={e.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2" data-event={e.type} title={e.type}>
                <span className="w-36 shrink-0 text-muted-foreground tabular-nums">{new Date(e.time).toLocaleString('ru')}</span>
                <span className="min-w-48 flex-1">{href ? (
                  <Tip label={e.asset_id ? 'Карточка объекта, с которым это случилось' : 'Помещение, где это случилось'}>
                    <a className="hover:underline" href={href}>{describe(e)}</a>
                  </Tip>
                ) : describe(e)}</span>
                <span className="text-muted-foreground max-sm:hidden">{where(e)}</span>
                <span className="text-muted-foreground">{who(e)}</span>
              </li>
            )
          })}
        </ul>
      )}
      {next && <Button className="mt-3" variant="outline" size="sm" onClick={more} hint="Подгрузить следующие 100 событий, более ранние">Ещё</Button>}
    </section>
  )
}
