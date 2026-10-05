import { FileText, Map as MapIcon, Paperclip, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addAssetFile, assetFileUrl, assetFiles, assetHistory, deleteAssetFile, getAsset, listPeople, patchAsset, peopleByIds,
  revertAsset, setAssetResponsible, setAssetState, STATES,
  type AssetCard as Card, type AssetFile, type AssetState, type HistoryEntry, type Person, type Prop, type TreeFloor,
} from '../api'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { to } from '../shell/route'
import { useEvents } from '../stream'
import { StateBadge } from './Assets'

const select = 'h-8 rounded-md border bg-card px-2 text-sm'
const ACTIONS: Record<string, string> = {
  created: 'поставлен на учёт', changed: 'изменён', moved: 'перемещён', state: 'состояние', responsible: 'ответственный',
  file_added: 'файл добавлен', file_removed: 'файл убран', retired: 'списан', reverted: 'откат', system: 'система' }
const show = (v: unknown) => (v == null || v === '' ? '—' : typeof v === 'boolean' ? (v ? 'да' : 'нет') : String(v))

/** The card of an object: the same from the list, the plan and the QR code. What one may change is a field; what not — text. */
export function AssetCard({ id, building, floors, onGone }: { id: string; building: string; floors: TreeFloor[]; onGone: () => void }) {
  const [a, setA] = useState<Card | null>(null)
  const [files, setFiles] = useState<AssetFile[]>([])
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [names, setNames] = useState<Record<string, string>>({})
  const [people, setPeople] = useState<Person[]>([])
  const [error, setError] = useState<string | null>(null)
  const picker = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    Promise.all([getAsset(id), assetFiles(id), assetHistory(id)]).then(async ([card, f, h]) => {
      setA(card); setFiles(f); setHistory(h); setError(null)
      const ids = [...new Set([card.responsible_id, ...h.map(x => x.actor.person_id)].filter((x): x is string => !!x))]
      if (ids.length) setNames(Object.fromEntries((await peopleByIds(ids)).map(p => [p.id, p.full_name])))
      if (card.can.manage) listPeople().then(setPeople, () => {})
    }, (e: Error) => { setError(e.message); onGone() })
  }, [id, onGone])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('assets.') && (event as unknown as { asset_id?: string }).asset_id === id) load() })
  const act = (work: Promise<unknown>) => work.then(load, (e: Error) => { setError(e.message); load() })

  if (!a) return <p className="text-sm text-muted-foreground" role={error ? 'alert' : undefined}>{error ?? 'Загрузка…'}</p>
  const floor = floors.find(f => f.id === a.floor_id)
  const room = floor?.rooms.find(r => r.id === a.room_id)
  const editable = (p: Prop) => (p.editable_by === 'responsible' ? a.can.edit : a.can.manage)
  return (
    <div className="grid min-w-0 gap-4 text-sm [&>*]:min-w-0" data-testid="asset-card">
      <div>
        <h2 className="text-base font-semibold">{a.type_name}</h2>
        <div className="text-muted-foreground">{a.inventory_no}{a.serial_no ? ` · зав. № ${a.serial_no}` : ''}</div>
        <div className="mt-1 text-muted-foreground">{floor?.name} · {room?.name || 'помещение без названия'}</div>
      </div>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {(a.needs_fill || a.needs_placement) && (
        <p role="status" className="rounded-md bg-warning/15 px-2.5 py-1.5 text-warning">
          {a.needs_placement ? 'Требует размещения: помещения или контейнера, где он стоял, больше нет. ' : ''}
          {a.needs_fill ? 'Требует заполнения: не все обязательные свойства заданы.' : ''}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {a.can.edit && a.state !== 'retired' ? (
          <select className={select} value={a.state} aria-label="Состояние объекта" onChange={e => act(setAssetState(a, e.target.value as AssetState))}>
            {Object.entries(STATES).filter(([k]) => k !== 'retired' || a.can.manage).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        ) : <StateBadge a={a} />}
        {a.x != null && floor && (
          <Button asChild variant="outline" size="sm"><a href={to.plan(building, floor.id, a.room_id)}><MapIcon className="size-4" /> На плане</a></Button>
        )}
      </div>
      <dl className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-x-3 gap-y-1.5 [&_input]:min-w-0 [&_select]:w-full [&_select]:min-w-0">
        <dt className="text-muted-foreground">Отвечает</dt>
        <dd>{a.can.manage ? (
          <select className={`${select} max-w-full`} value={a.responsible_id ?? ''} aria-label="Ответственный"
            onChange={e => act(setAssetResponsible(a, e.target.value || null))}>
            <option value="">не назначен</option>
            {people.map(p => <option key={p.id} value={p.id}>{p.full_name}</option>)}
            {a.responsible_id && !people.some(p => p.id === a.responsible_id) && <option value={a.responsible_id}>{names[a.responsible_id] ?? '…'}</option>}
          </select>
        ) : (a.responsible_id ? names[a.responsible_id] ?? '…' : 'не назначен')}</dd>
        {a.schema.map(p => (
          <Field key={p.key + a.version} p={p} value={a.props[p.key]} editable={editable(p) && a.state !== 'retired'}
            onSave={v => act(patchAsset(a, { props: { [p.key]: v } }))} />
        ))}
        <dt className="text-muted-foreground">Примечание</dt>
        <dd>{a.can.edit ? <Text key={a.version} value={a.note} label="Примечание" onSave={v => act(patchAsset(a, { note: v }))} /> : show(a.note)}</dd>
      </dl>
      {a.children.length > 0 && (
        <div>
          <h3 className="font-medium">Внутри</h3>
          <ul className="mt-1 grid gap-0.5">
            {a.children.map(c => <li key={c.id}><a className="text-primary" href={to.assets(building, c.id)}>{c.type_name} · {c.inventory_no}</a></li>)}
          </ul>
        </div>
      )}
      <div>
        <div className="flex items-center gap-2">
          <h3 className="font-medium">Файлы</h3>
          {a.can.edit && <Button variant="ghost" size="sm" onClick={() => picker.current?.click()}><Paperclip className="size-4" /> Приложить</Button>}
          <input ref={picker} type="file" className="hidden" accept="image/*,.pdf,.doc,.docx,.xls,.xlsx" capture={undefined} data-testid="asset-file"
            onChange={e => { const f = e.target.files?.[0]; if (f) act(addAssetFile(a.id, f)); e.target.value = '' }} />
        </div>
        {files.length === 0 ? <p className="text-muted-foreground">Фотографий и документов нет.</p> : (
          <ul className="mt-1 grid gap-1" data-testid="asset-files">
            {files.map(f => (
              <li key={f.id} className="flex items-center gap-2">
                {f.kind === 'photo'
                  ? <a href={assetFileUrl(f.id)} target="_blank" rel="noreferrer"><img src={assetFileUrl(f.id)} alt={f.name} className="size-12 rounded border object-cover" /></a>
                  : <FileText className="size-4 text-muted-foreground" />}
                <a className="min-w-0 flex-1 truncate text-primary" href={assetFileUrl(f.id)} target="_blank" rel="noreferrer">{f.name}</a>
                {a.can.edit && <Button variant="ghost" size="sm" onClick={() => act(deleteAssetFile(f.id))}>Убрать</Button>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h3 className="font-medium">История</h3>
        <ul className="mt-1 grid gap-1.5" data-testid="asset-history">
          {history.map(h => (
            <li key={h.id} className="rounded-md border px-2 py-1.5">
              <div className="flex items-center gap-2">
                <span className="flex-1">{ACTIONS[h.action] ?? h.action}</span>
                {a.can.manage && (h.action === 'changed' || h.action === 'state') && (
                  <Button variant="ghost" size="sm" title="Вернуть как было" onClick={() => act(revertAsset(a.id, h.id))}><Undo2 className="size-4" /> Откатить</Button>
                )}
              </div>
              {Object.entries(h.changes).map(([field, [was, now]]) => {
                const title = field.startsWith('props.') ? a.schema.find(p => `props.${p.key}` === field)?.title ?? field
                  : field === 'state' ? 'Состояние' : field === 'note' ? 'Примечание' : null
                const value = (v: unknown) => (field === 'state' ? STATES[v as AssetState] ?? show(v) : show(v))
                return title && <div key={field} className="text-xs">{title}: {value(was)} → {value(now)}</div>
              })}
              {h.reason && <div className="text-xs">{h.reason}</div>}
              <div className="text-xs text-muted-foreground">
                {h.actor.person_id ? names[h.actor.person_id] ?? '…' : h.actor.kind === 'service' ? 'система' : 'администратор системы'}
                {' · '}{new Date(h.at).toLocaleString('ru')}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function Text({ value, label, onSave }: { value: string; label: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value)
  return <Input className="h-8" value={v} aria-label={label} onChange={e => setV(e.target.value)}
    onBlur={() => { if (v !== value) onSave(v) }} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />
}

/** A property by the schema of the type: a field for whoever may edit it, text for the rest. */
function Field({ p, value, editable, onSave }: { p: Prop; value: unknown; editable: boolean; onSave: (v: unknown) => void }) {
  const [v, setV] = useState(value == null ? '' : String(value))
  const label = `${p.title}${p.unit ? `, ${p.unit}` : ''}`
  const commit = () => {
    const next = v === '' ? null : p.kind === 'number' ? Number(v.replace(',', '.')) : v
    if (next !== (value ?? null)) onSave(next)
  }
  let control
  if (!editable) {
    control = p.kind === 'choice' ? p.options?.find(o => o.value === value)?.title ?? show(value) : show(value)
  } else if (p.kind === 'bool') {
    control = <input type="checkbox" className="size-4 accent-primary" aria-label={label} checked={value === true} onChange={e => onSave(e.target.checked)} />
  } else if (p.kind === 'choice') {
    control = (
      <select className={`${select} max-w-full`} aria-label={label} value={v} onChange={e => onSave(e.target.value || null)}>
        <option value="">—</option>{p.options?.map(o => <option key={o.value} value={o.value}>{o.title}</option>)}
      </select>
    )
  } else {
    control = <Input className="h-8" aria-label={label} type={p.kind === 'date' ? 'date' : 'text'} inputMode={p.kind === 'number' ? 'decimal' : undefined}
      value={v} onChange={e => setV(e.target.value)} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />
  }
  return <><dt className="text-muted-foreground">{label}{p.required ? ' *' : ''}</dt><dd>{control}</dd></>
}
