import { Copy, Link2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createGrant, createShare, listGrants, listPeople, listShares, peopleByIds, revokeGrant, revokeShare,
  type Building, type Grant, type Person, type Role, type Share, type TreeFloor,
} from '../api'
import { useConfirm } from '../components/confirm'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Tip } from '../components/ui/tooltip'
import { useEvents } from '../stream'
import { until } from '../lib/utils'

const ROLES: Record<Role, string> = { viewer: 'просмотр', responsible: 'ответственный', admin: 'администратор' }
const select = 'h-8 rounded-md border bg-card px-2 text-sm'

/** Who may do what in the building: rights are given to people of the directory, for an area. */
export function Access({ building, floors }: { building: Building; floors: TreeFloor[] }) {
  const [grants, setGrants] = useState<Grant[]>([])
  const [names, setNames] = useState<Record<string, string>>({})
  const [people, setPeople] = useState<Person[]>([])
  const [error, setError] = useState<string | null>(null)
  const [person, setPerson] = useState('')
  const [role, setRole] = useState<Role>('viewer')
  const [scope, setScope] = useState('building')            // 'building' | a floor id | a room id

  const load = useCallback(() => {
    listGrants(building.id).then(async g => {
      setGrants(g)
      const known = await peopleByIds([...new Set(g.map(x => x.person_id))])
      setNames(Object.fromEntries(known.map(p => [p.id, p.full_name])))
      setError(null)
    }, (e: Error) => setError(e.message))
  }, [building.id])
  useEffect(load, [load])
  useEffect(() => { listPeople().then(setPeople, () => {}) }, [])
  useEvents(event => { if (event.type.startsWith('access.')) load() })

  const areas = useMemo(() => {
    const out = new Map<string, { kind: 'building' | 'floor' | 'room'; label: string }>([['building', { kind: 'building', label: 'всё здание' }]])
    for (const f of floors) {
      out.set(f.id, { kind: 'floor', label: f.name || `этаж ${f.level}` })
      for (const r of f.rooms) out.set(r.id, { kind: 'room', label: `${f.name || f.level} · ${r.name || 'без названия'} (${r.area} м²)` })
    }
    return out
  }, [floors])
  const areaName = (g: Grant) => (g.scope.kind === 'building' ? 'всё здание' : areas.get(g.scope.id)?.label ?? 'область снята')

  const give = (e: React.FormEvent) => {
    e.preventDefault()
    const area = areas.get(scope)!
    createGrant({ person_id: person, role, building_id: building.id, scope: { kind: area.kind, id: scope === 'building' ? building.id : scope } })
      .then(() => { setPerson(''); load() }, (ex: Error) => setError(ex.message))
  }

  return (
    <section>
      <h1 className="text-xl font-semibold">Доступ</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
        Право на область действует на всё внутри неё. Любое право в здании открывает его план; объекты и люди видны только в своих помещениях.
      </p>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      <form onSubmit={give} className="mt-4 flex flex-wrap items-end gap-2 rounded-lg border bg-card p-3" data-testid="grant-form">
        <label className="grid gap-1 text-xs text-muted-foreground">Кому
          <Tip label="Права даются человеку из справочника, а не учётной записи; нет в списке — добавьте в разделе «Люди»">
            <select className={select} value={person} onChange={e => setPerson(e.target.value)} required aria-label="Кому">
              <option value="">— человек из справочника —</option>
              {people.map(p => <option key={p.id} value={p.id}>{p.full_name}{p.position ? ` — ${p.position}` : ''}</option>)}
            </select>
          </Tip>
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">Что может
          <Tip label="Просмотр — только видеть; ответственный — править свойства, состояние и файлы объектов; администратор — всё в области">
            <select className={select} value={role} onChange={e => setRole(e.target.value as Role)} aria-label="Что может">
              {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Tip>
        </label>
        <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">Где
          <Tip label="Право действует на всё внутри области: на этаже — во всех его помещениях">
            <select className={`${select} max-w-64`} value={scope} onChange={e => setScope(e.target.value)} aria-label="Где">
              {[...areas].map(([id, a]) => <option key={id} value={id}>{a.kind === 'room' ? `  ${a.label}` : a.label}</option>)}
            </select>
          </Tip>
        </label>
        <Button type="submit" size="sm" disabled={!person}
          hint="Право начнёт действовать сразу, запись о нём попадёт в журнал; сначала выберите человека">Выдать</Button>
      </form>
      {grants.length === 0 ? (
        <p className="mt-5 text-sm text-muted-foreground">Прав в этом здании пока никому не выдано.</p>
      ) : (
        <ul className="mt-4 divide-y rounded-lg border bg-card text-sm" data-testid="grants">
          {grants.map(g => (
            <li key={g.id} className="flex flex-wrap items-center gap-3 px-3 py-2" data-grant={names[g.person_id] ?? ''}>
              <span className="min-w-40 flex-1 font-medium">{names[g.person_id] ?? '…'}</span>
              <span>{ROLES[g.role]}</span>
              <span className="text-muted-foreground">{areaName(g)}</span>
              <Button variant="ghost" size="sm" onClick={() => revokeGrant(g.id).then(load, (ex: Error) => setError(ex.message))}
                hint="Человек сразу потеряет это право в этой области; запись останется в журнале">Отозвать</Button>
            </li>
          ))}
        </ul>
      )}
      <Shares building={building} floors={floors} />
    </section>
  )
}

const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, '0')
const day = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
/** The end of a day, local time, with its offset: «2026-10-13T23:59:59+03:00». */
function endOfDay(date: string) {
  const offset = -new Date(`${date}T23:59:59`).getTimezoneOffset()
  return `${date}T23:59:59${offset < 0 ? '-' : '+'}${pad(offset / 60)}:${pad(offset % 60)}`
}
/** 1 раз, 2 раза, 5 раз, 11 раз, 21 раз. */
const times = (n: number) => `${n} ${n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'раза' : 'раз'}`
const STATE: Record<Share['state'], [string, 'success' | 'default' | 'warning']> = {
  active: ['действует', 'success'], revoked: ['отозвана', 'default'], expired: ['истекла', 'warning'] }
const STATE_HINT: Record<Share['state'], string> = {
  active: 'По ссылке можно смотреть до указанного дня', revoked: 'Ссылку отозвали: она больше не открывается',
  expired: 'Срок вышел: ссылка больше не открывается' }

/** Links for viewing without an account: whoever has one sees the building, a floor or a room until a date. */
function Shares({ building, floors }: { building: Building; floors: TreeFloor[] }) {
  const [items, setItems] = useState<Share[]>([])
  const [error, setError] = useState<string | null>(null)
  const [kind, setKind] = useState<Share['scope']['kind']>('building')
  const [floor, setFloor] = useState('')
  const [room, setRoom] = useState('')
  const [today] = useState(() => day(new Date()))
  const [date, setDate] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 7); return day(d) })
  const [note, setNote] = useState('')
  // the link just given: shown once, it is kept nowhere
  const [made, setMade] = useState<{ url: string; note: string } | null>(null)
  const [copied, setCopied] = useState<'copied' | 'selected' | null>(null)
  const field = useRef<HTMLInputElement>(null)
  const [ask, dialog] = useConfirm()

  const load = useCallback(() => {
    listShares(building.id).then(s => { setItems(s); setError(null) }, (e: Error) => setError(e.message))
  }, [building.id])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('access.share.')) load() })

  const what = (s: Share) => {
    if (s.scope.kind === 'building') return building.name
    const f = floors.find(x => x.id === (s.scope.kind === 'floor' ? s.scope.id : s.floor_id))
    if (s.scope.kind === 'floor') return f ? f.name || `этаж ${f.level}` : 'этажа больше нет'
    const r = f?.rooms.find(x => x.id === s.scope.id)
    return r ? `${f!.name || f!.level} · ${r.name || 'без названия'}` : 'помещения больше нет'
  }
  const rooms = floors.find(f => f.id === floor)?.rooms ?? []
  const ready = kind === 'building' || (kind === 'floor' && !!floor) || (kind === 'room' && !!floor && !!room)

  const give = (e: React.FormEvent) => {
    e.preventDefault()
    if (!ready) return
    createShare({
      building_id: building.id, note: note.trim(), expires_at: endOfDay(date),
      scope: { kind, id: kind === 'building' ? building.id : kind === 'floor' ? floor : room },
      floor_id: kind === 'building' ? null : floor,
    }).then(s => { setMade({ url: s.url, note: s.note }); setCopied(null); setNote(''); load() }, (ex: Error) => setError(ex.message))
  }
  const selectLink = () => { field.current?.focus(); field.current?.select(); setCopied('selected') }
  // the clipboard is there only on a secure page (https, localhost); elsewhere the text is selected for Ctrl+C
  const copy = () => {
    if (!made) return
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(made.url).then(() => setCopied('copied'), selectLink)
    else selectLink()
  }
  const revoke = async (s: Share) => {
    if (!await ask({ title: 'Отозвать ссылку?', text: `${what(s)}${s.note ? ` — ${s.note}` : ''}. Кто смотрит по ней сейчас, увидит, что просмотр закончился; открыть её снова будет нельзя.`,
      confirm: 'Отозвать', danger: true })) return
    revokeShare(s.id).then(load, (ex: Error) => setError(ex.message))
  }

  return (
    <div className="mt-8">
      {dialog}
      <h2 className="text-lg font-semibold">Ссылки для просмотра</h2>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
        По ссылке смотрят без учётной записи: план, 3D-модель и объекты — без людей, журнала и комментариев. Ссылка действует до конца выбранного дня, пока её не отозвали.
      </p>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      <form onSubmit={give} className="mt-3 flex flex-wrap items-end gap-2 rounded-lg border bg-card p-3" data-testid="share-form">
        <label className="grid gap-1 text-xs text-muted-foreground">Что показать
          <Tip label="Какую часть здания увидит гость: план, 3D-модель и объекты только в ней">
            <select className={select} value={kind} aria-label="Что показать"
              onChange={e => { setKind(e.target.value as Share['scope']['kind']); setRoom('') }}>
              <option value="building">всё здание</option>
              <option value="floor">этаж</option>
              <option value="room">помещение</option>
            </select>
          </Tip>
        </label>
        {kind !== 'building' && (
          <label className="grid gap-1 text-xs text-muted-foreground">Этаж
            <Tip label={kind === 'room' ? 'Этаж, на котором помещение: его план откроется гостю' : 'Этаж, который увидит гость'}>
              <select className={select} value={floor} required aria-label="Этаж" onChange={e => { setFloor(e.target.value); setRoom('') }}>
                <option value="">— этаж —</option>
                {floors.map(f => <option key={f.id} value={f.id}>{f.name || `этаж ${f.level}`}</option>)}
              </select>
            </Tip>
          </label>
        )}
        {kind === 'room' && (
          <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">Помещение
            <Tip label="Гостю покажут план этажа с этим помещением и только его объекты; список откроется, когда выбран этаж">
              <select className={`${select} max-w-64`} value={room} required disabled={!floor} aria-label="Помещение" onChange={e => setRoom(e.target.value)}>
                <option value="">{floor ? '— помещение —' : 'сначала этаж'}</option>
                {rooms.map(r => <option key={r.id} value={r.id}>{r.name || 'без названия'} ({r.area} м²)</option>)}
              </select>
            </Tip>
          </label>
        )}
        <label className="grid gap-1 text-xs text-muted-foreground">До какого дня
          <Tip label="Ссылка действует до конца этого дня по местному времени; отозвать её можно раньше">
            <Input type="date" className="h-8 w-40" value={date} min={today} required aria-label="До какого дня" onChange={e => setDate(e.target.value)} />
          </Tip>
        </label>
        <label className="grid min-w-48 flex-1 gap-1 text-xs text-muted-foreground">Для кого
          <Tip label="Пометка для себя: видна в списке ссылок и в журнале, когда по ссылке заходят; гость её не видит">
            <Input className="h-8" value={note} maxLength={200} placeholder="например, подрядчик" aria-label="Для кого" onChange={e => setNote(e.target.value)} />
          </Tip>
        </label>
        <Button type="submit" size="sm" disabled={!ready || !date}
          hint="Ссылка, по которой посмотрят выбранную часть здания без учётной записи; её покажут один раз"><Link2 className="size-4" />Выдать ссылку</Button>
      </form>
      {made && (
        <div className="mt-3 grid gap-2 rounded-lg border border-primary/40 bg-card p-3 text-sm" data-testid="share-made">
          <p>Ссылка{made.note ? ` (${made.note})` : ''} — <b>показывается один раз</b>: скопируйте и отправьте её сейчас, потом её не будет видно.</p>
          <div className="flex flex-wrap gap-2">
            <Tip label="Отправьте её тому, кто будет смотреть: после скрытия её не будет видно нигде">
              <Input ref={field} readOnly value={made.url} className="h-8 min-w-0 flex-1 font-mono text-xs" aria-label="Ссылка" data-testid="share-link"
                onFocus={e => e.currentTarget.select()} />
            </Tip>
            <Button type="button" size="sm" onClick={copy}
              hint="Положить ссылку в буфер обмена; где буфер недоступен, она выделится для Ctrl+C"><Copy className="size-4" />Копировать</Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setMade(null)}
              hint="Убрать ссылку с экрана; показать её снова будет нельзя — только выдать новую">Скрыть</Button>
          </div>
          {copied && <p className="text-xs text-muted-foreground">{copied === 'copied' ? 'Скопировано.' : 'Ссылка выделена — нажмите Ctrl+C (на телефоне — «Копировать» в меню).'}</p>}
        </div>
      )}
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">Ссылок пока не выдано.</p>
      ) : (
        <ul className="mt-3 divide-y rounded-lg border bg-card text-sm" data-testid="shares">
          {items.map(s => (
            <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2" data-share={s.note} data-state={s.state}>
              <span className="min-w-40 flex-1">
                <span className="font-medium">{what(s)}</span>
                {s.note && <span className="ml-2 text-muted-foreground">{s.note}</span>}
              </span>
              <span className="text-muted-foreground">до {until(s.expires_at)}</span>
              <Tip label={STATE_HINT[s.state]}><Badge variant={STATE[s.state][1]}>{STATE[s.state][0]}</Badge></Tip>
              <span className="text-muted-foreground">
                {s.opened ? `открыта ${times(s.opened)}${s.last_opened_at ? `, последний — ${new Date(s.last_opened_at).toLocaleString('ru')}` : ''}` : 'ещё не открывали'}
              </span>
              {s.state === 'active' && (
                <Button variant="ghost" size="sm" onClick={() => void revoke(s)}
                  hint="Ссылка сразу перестанет открываться, даже у того, кто смотрит по ней сейчас; вернуть её нельзя">Отозвать</Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
