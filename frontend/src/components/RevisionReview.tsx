import { useCallback, useEffect, useState } from 'react'
import { discardRevision, getRevision, matchRoom, publishRevision, type Revision, type RevisionRoom } from '../api'
import { cn } from '../lib/utils'
import { Badge } from './ui/badge'
import { Button } from './ui/button'

const CHANGE: Record<string, string> = { new: 'новое', name: 'переименовано', outline: 'другой контур', returned: 'возвращено' }
const select = 'h-7 max-w-full rounded-md border bg-card px-1 text-xs'

/** A new build of a drawing that would retire rooms waits here: what is new, changed, gone; which known
 * room each room of the build continues — corrected by hand; then published or discarded. */
export function RevisionReview({ id, onDone }: { id: string; onDone: () => void }) {
  const [r, setR] = useState<Revision | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => { getRevision(id).then(setR, (e: Error) => setError(e.message)) }, [id])
  useEffect(load, [load])
  const act = (work: Promise<Revision>, done = false) => {
    setBusy(true)
    work.then(next => { setError(null); if (done) onDone(); else setR(next) }, (e: Error) => setError(e.message)).finally(() => setBusy(false))
  }
  if (!r) return <p className="text-sm text-muted-foreground">{error ?? 'Загрузка…'}</p>
  const d = r.differences
  if (!d) return <p className="text-sm text-muted-foreground">Ревизия уже {r.status === 'published' ? 'опубликована' : 'отброшена'}.</p>
  const floorName = (fid: string | null, cand: string) => d.floors.find(f => f.candidate === cand)?.name || (fid ? 'этаж' : 'новый этаж')
  const byFloor = new Map<string, RevisionRoom[]>()
  for (const room of d.rooms) byFloor.set(room.candidate, [...(byFloor.get(room.candidate) ?? []), room])
  return (
    <div className="mt-2 grid gap-3 rounded-lg border bg-background p-3 text-sm" data-testid="revision">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Сборка {r.n}: различия с опубликованным</span>
        <Badge variant="accent">новых {d.count.new}</Badge>
        <Badge variant="accent">изменено {d.count.changed}</Badge>
        <Badge variant={d.count.retired ? 'destructive' : 'accent'}>будет снято {d.count.retired}</Badge>
        {!!d.count.merged && <Badge variant="accent">объединится {d.count.merged}</Badge>}
        <span className="text-muted-foreground">без изменений {d.count.same}</span>
      </div>
      <p className="text-muted-foreground">
        Пока ревизия не опубликована, здание прежнее. Объекты снятых помещений получат отметку «требует размещения»;
        объекты остальных останутся в своих помещениях по точкам, права и привязки людей — при помещениях.
      </p>
      {(r.warnings ?? []).length > 0 && (
        <ul className="rounded-md bg-warning/15 px-2.5 py-1.5 text-warning">{r.warnings!.map(w => <li key={w}>{w}</li>)}</ul>
      )}
      {[...byFloor].map(([cand, rooms]) => {
        const fid = rooms[0].floor_id
        const choices = fid ? d.choices[fid] ?? [] : []
        return (
          <div key={cand}>
            <h4 className="text-xs font-medium text-muted-foreground">{floorName(fid, cand)}</h4>
            <ul className="mt-1 divide-y rounded-md border">
              {rooms.map(room => (
                <li key={room.idx} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1.5" data-match={`${cand}/${room.idx}`}>
                  <span className="min-w-40 flex-1">{room.name || <span className="text-muted-foreground">без названия</span>}
                    <span className="ml-2 text-muted-foreground">{room.area} м²</span></span>
                  {room.changes.map(c => <Badge key={c} variant={c === 'new' ? 'warning' : 'accent'}>{CHANGE[c] ?? c}</Badge>)}
                  <label className="flex items-center gap-1 text-xs text-muted-foreground">продолжает
                    <select className={cn(select, !room.auto && 'border-primary')} value={room.room_id ?? ''} disabled={busy}
                      aria-label="Продолжает помещение" onChange={e => act(matchRoom(r.id, cand, room.idx, e.target.value || null))}>
                      <option value="">— новое помещение —</option>
                      {choices.map(c => <option key={c.id} value={c.id}>{c.name || 'без названия'} · {c.area} м²</option>)}
                    </select>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
      {d.retired.length > 0 && (
        <div data-testid="retired">
          <h4 className="text-xs font-medium text-destructive">Будут сняты</h4>
          <ul className="mt-1 grid gap-0.5">
            {d.retired.map(x => <li key={x.id}>{x.name || 'без названия'} · {x.area} м²</li>)}
          </ul>
        </div>
      )}
      {!!d.merged?.length && (
        <div data-testid="merged">
          <h4 className="text-xs font-medium">Войдут в соседние помещения (перегородка убрана)</h4>
          <ul className="mt-1 grid gap-0.5">
            {d.merged.map(x => <li key={x.id}>{x.name || 'без названия'} · {x.area} м² → {x.into_name || 'без названия'}</li>)}
          </ul>
        </div>
      )}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" disabled={busy} onClick={() => act(publishRevision(r.id), true)}>Опубликовать</Button>
        <Button size="sm" variant="ghost" disabled={busy}
          onClick={() => { if (confirm('Отбросить сборку? Здание останется прежним.')) act(discardRevision(r.id), true) }}>Отбросить</Button>
      </div>
    </div>
  )
}
