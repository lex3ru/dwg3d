import { FileText, History, Map as MapIcon, Pencil, QrCode } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { labelsSheet, mergeRooms, patchRoom, roomPeople, roomSheetUrl, type Me, type Room, type RoomPerson, type TreeFloor } from '../api'
import { useEvents } from '../stream'
import { Comments } from '../components/Comments'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Tip } from '../components/ui/tooltip'
import { to } from '../shell/route'

/** The card of a room: what it is and where; the administrator names it here. */
export function RoomCard({ me, building, room, floor, admin, onChanged, onPlan }: {
  me: Me; building: string; room: Room; floor: TreeFloor; admin: boolean; onChanged: () => void
  /** shown where the plan is not on screen already */
  onPlan?: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(room.name)
  const [error, setError] = useState<string | null>(null)
  const [people, setPeople] = useState<RoomPerson[]>([])
  const loadPeople = useCallback(() => { roomPeople(room.id).then(setPeople, () => setPeople([])) }, [room.id])
  useEffect(loadPeople, [loadPeople])
  useEvents(event => { if (event.type.startsWith('people.') || event.type.startsWith('access.')) loadPeople() })
  const save = (e: React.FormEvent) => {
    e.preventDefault()
    patchRoom(room, { name: name.trim() }).then(() => { setEditing(false); setError(null); onChanged() }, (ex: Error) => setError(ex.message))
  }
  return (
    <div className="grid gap-3" data-testid="room-card">
      {editing ? (
        <form onSubmit={save} className="grid gap-2">
          <Input value={name} onChange={e => setName(e.target.value)} maxLength={200} autoFocus aria-label="Название помещения" />
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" hint="Название увидят все, кому видно помещение; новые сборки чертежа его не заменят">Сохранить</Button>
            <Button type="button" size="sm" variant="ghost" hint="Оставить прежнее название" onClick={() => { setEditing(false); setName(room.name) }}>Отмена</Button>
          </div>
        </form>
      ) : (
        <div className="flex items-start gap-2">
          <h2 className="flex-1 text-base font-semibold">{room.name || 'Помещение без названия'}</h2>
          {admin && <Button variant="ghost" size="icon" aria-label="Переименовать" hint="Задать помещению своё название; новые сборки чертежа его не заменят" onClick={() => setEditing(true)}><Pencil className="size-4" /></Button>}
        </div>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
        <dt className="text-muted-foreground">Этаж</dt><dd>{floor.name || floor.level}</dd>
        <dt className="text-muted-foreground">Площадь</dt><dd>{room.area.toLocaleString('ru')} м²</dd>
        {room.number && <><dt className="text-muted-foreground">Номер</dt><dd>{room.number}</dd></>}
      </dl>
      <div className="flex flex-wrap gap-2">
        {onPlan && (
          <Button asChild variant="outline" size="sm" hint="Открыть план этажа с выделенным помещением; карточка останется рядом">
            <a href={to.plan(building, floor.id, room.id)}><MapIcon className="size-4" /> Показать на плане</a>
          </Button>
        )}
        <Button asChild variant="outline" size="sm" hint="Скачать PDF: объекты помещения с номерами, состоянием, ответственными и местом для подписи">
          <a href={roomSheetUrl(room.id)} download><FileText className="size-4" /> Ведомость</a>
        </Button>
        {admin && (
          <Button variant="outline" size="sm" hint="Скачать PDF (A4) с QR-метками всех объектов помещения — для печати и наклейки"
            onClick={() => labelsSheet({ room_id: room.id }).catch((ex: Error) => setError(ex.message))}><QrCode className="size-4" /> Метки</Button>
        )}
        {admin && (
          <Button asChild variant="outline" size="sm" hint="Лента событий только этого помещения: кто, что и когда менял"><a href={to.journal(building, { room: room.id })}><History className="size-4" /> Журнал</a></Button>
        )}
      </div>
      {admin && floor.rooms.length > 1 && (
        <label className="grid gap-1 text-sm text-muted-foreground">Объединить с соседним
          <Tip label="Сделать из двух соседних помещений одно: объекты, люди и права перейдут к этому помещению, второе будет снято">
            <select className="h-8 rounded-md border bg-card px-2 text-sm" value="" aria-label="Объединить с"
              onChange={e => {
                const other = floor.rooms.find(r => r.id === e.target.value)
                if (other && confirm(`Объединить «${room.name || 'без названия'}» и «${other.name || 'без названия'}»? Объекты, люди и права второго перейдут к первому.`)) {
                  mergeRooms(room.id, [other.id]).then(() => { setError(null); onChanged() }, (ex: Error) => setError(ex.message))
                }
              }}>
              <option value="">— помещение этого этажа —</option>
              {floor.rooms.filter(r => r.id !== room.id).map(r => <option key={r.id} value={r.id}>{r.name || 'без названия'} · {r.area} м²</option>)}
            </select>
          </Tip>
        </label>
      )}
      {error && !editing && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div data-testid="room-people">
        <h3 className="text-sm font-medium">Люди помещения{people.length > 0 && ` · ${people.length}`}</h3>
        {people.length === 0 ? <p className="text-sm text-muted-foreground">Никто не привязан.</p> : (
          <ul className="mt-1 grid gap-1 text-sm">
            {people.map(p => (
              <li key={p.id} data-person={p.full_name}>
                <div className="font-medium">{p.full_name}</div>
                <div className="text-xs text-muted-foreground">{[p.position, p.department, p.email, p.phone].filter(Boolean).join(' · ')}</div>
                {p.workplace_asset_id && <Tip label="Карточка объекта, за которым работает этот человек"><a className="text-xs text-primary" href={to.assets(building, p.workplace_asset_id)}>рабочее место</a></Tip>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="text-sm text-muted-foreground">Объекты помещения — в разделе «Объекты».</p>
      <Comments me={me} building={building} target_kind="room" target_id={room.id} admin={admin} />
    </div>
  )
}
