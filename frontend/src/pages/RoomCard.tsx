import { FileText, Map as MapIcon, Pencil, QrCode } from 'lucide-react'
import { useState } from 'react'
import { labelsSheet, patchRoom, roomSheetUrl, type Me, type Room, type TreeFloor } from '../api'
import { Comments } from '../components/Comments'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
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
            <Button type="submit" size="sm">Сохранить</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => { setEditing(false); setName(room.name) }}>Отмена</Button>
          </div>
        </form>
      ) : (
        <div className="flex items-start gap-2">
          <h2 className="flex-1 text-base font-semibold">{room.name || 'Помещение без названия'}</h2>
          {admin && <Button variant="ghost" size="icon" title="Переименовать" onClick={() => setEditing(true)}><Pencil className="size-4" /></Button>}
        </div>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
        <dt className="text-muted-foreground">Этаж</dt><dd>{floor.name || floor.level}</dd>
        <dt className="text-muted-foreground">Площадь</dt><dd>{room.area.toLocaleString('ru')} м²</dd>
        {room.number && <><dt className="text-muted-foreground">Номер</dt><dd>{room.number}</dd></>}
      </dl>
      <div className="flex flex-wrap gap-2">
        {onPlan && (
          <Button asChild variant="outline" size="sm">
            <a href={to.plan(building, floor.id, room.id)}><MapIcon className="size-4" /> Показать на плане</a>
          </Button>
        )}
        <Button asChild variant="outline" size="sm" title="Объекты помещения с местом для подписи (PDF)">
          <a href={roomSheetUrl(room.id)} download><FileText className="size-4" /> Ведомость</a>
        </Button>
        {admin && (
          <Button variant="outline" size="sm" title="Лист QR-меток объектов помещения (PDF, A4)"
            onClick={() => labelsSheet({ room_id: room.id }).catch((ex: Error) => setError(ex.message))}><QrCode className="size-4" /> Метки</Button>
        )}
      </div>
      {error && !editing && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <p className="text-sm text-muted-foreground">Объекты помещения — в разделе «Объекты»; люди помещения появятся на следующем этапе.</p>
      <Comments me={me} building={building} target_kind="room" target_id={room.id} admin={admin} />
    </div>
  )
}
