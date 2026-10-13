import { Camera, FileText, History, Map as MapIcon, Move, Paperclip, Pencil, QrCode, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addAssetFile, assetFileUrl, assetFiles, assetHistory, assetLabelUrl, deleteAssetFile, getAsset, listAssets, listPeople, listTypes, moveAssetInto,
  patchAsset, peopleByIds,
  revertAsset, setAssetResponsible, setAssetState, STATES,
  type Asset, type AssetCard as Card, type AssetFile, type AssetState, type HistoryEntry, type Me, type Person, type Prop, type TreeFloor,
} from '../api'
import { Comments } from '../components/Comments'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Tip } from '../components/ui/tooltip'
import { to } from '../shell/route'
import { useEvents } from '../stream'
import { StateBadge } from './Assets'

const select = 'h-8 rounded-md border bg-card px-2 text-sm'
const ACTIONS: Record<string, string> = {
  created: 'поставлен на учёт', changed: 'изменён', moved: 'перемещён', state: 'состояние', responsible: 'ответственный',
  file_added: 'файл добавлен', file_removed: 'файл убран', retired: 'списан', reverted: 'откат', system: 'система' }
const SAVED_AT_ONCE = 'Сохраняется сразу; прежнее значение останется в истории'
const show = (v: unknown) => (v == null || v === '' ? '—' : typeof v === 'boolean' ? (v ? 'да' : 'нет') : String(v))

/** The card of an object: the same from the list, the plan and the QR code. What one may change is a field; what not — text. */
export function AssetCard({ id, me, building, floors, admin, onGone }: {
  id: string; me: Me; building: string; floors: TreeFloor[]; admin: boolean; onGone: () => void
}) {
  const [a, setA] = useState<Card | null>(null)
  const [files, setFiles] = useState<AssetFile[]>([])
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [names, setNames] = useState<Record<string, string>>({})
  const [people, setPeople] = useState<Person[]>([])
  const [boxes, setBoxes] = useState<Asset[]>([])           // containers of the building this one could stand in
  const [error, setError] = useState<string | null>(null)
  const [renumbering, setRenumbering] = useState<string | null>(null)       // the number being changed
  const [partial, setPartial] = useState(false)             // the people service did not answer: no names
  const picker = useRef<HTMLInputElement>(null)
  const camera = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    Promise.all([getAsset(id), assetFiles(id), assetHistory(id)]).then(async ([card, f, h]) => {
      setA(card); setFiles(f); setHistory(h); setError(null)
      const ids = [...new Set([card.responsible_id, ...h.map(x => x.actor.person_id)].filter((x): x is string => !!x))]
      if (ids.length) {
        try { setNames(Object.fromEntries((await peopleByIds(ids)).map(p => [p.id, p.full_name]))); setPartial(false) } catch { setPartial(true) }
      }
      if (card.can.manage) listPeople().then(setPeople, () => {})
      if (card.can.move && !card.container) {
        Promise.all([listTypes(true), listAssets({ building_id: building, limit: '500' })]).then(([types, all]) => {
          const holding = new Set(types.filter(t => t.container).map(t => t.id))
          setBoxes(all.items.filter(x => holding.has(x.type_id) && !x.container_id && x.id !== card.id))
        }, () => {})
      }
    }, (e: Error) => { setError(e.message); onGone() })
  }, [id, building, onGone])
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
        {renumbering != null ? (
          <form className="mt-1 flex items-center gap-2" onSubmit={e => {
            e.preventDefault()
            if (renumbering.trim() && renumbering.trim() !== a.inventory_no) act(patchAsset(a, { inventory_no: renumbering.trim() }).then(() => setRenumbering(null)))
            else setRenumbering(null)
          }}>
            <Input autoFocus className="h-7 w-40" value={renumbering} maxLength={60} aria-label="Новый инвентарный номер" onChange={e => setRenumbering(e.target.value)} />
            <Button type="submit" size="sm" hint="Старый номер останется в истории объекта; новый должен быть свободен во всей системе">Сохранить</Button>
            <Button type="button" size="sm" variant="ghost" hint="Оставить прежний номер" onClick={() => setRenumbering(null)}>Отмена</Button>
          </form>
        ) : (
          <div className="flex items-center gap-1 text-muted-foreground">{a.inventory_no}{a.serial_no ? ` · зав. № ${a.serial_no}` : ''}
            {a.can.manage && (
              <Button size="icon-sm" variant="ghost" aria-label="Изменить инвентарный номер" onClick={() => setRenumbering(a.inventory_no)}
                hint="Заменить номер, например сгенерированный при постановке, на настоящий из бухгалтерии; QR-метка по-прежнему откроет карточку, но напечатанный на ней номер станет старым">
                <Pencil className="size-3.5" />
              </Button>
            )}
          </div>
        )}
        <div className="mt-1 text-muted-foreground">{floor?.name} · {room?.name || 'помещение без названия'}</div>
      </div>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {partial && <p role="status" className="rounded-md bg-muted px-2.5 py-1.5 text-muted-foreground" data-testid="partial">Данные неполные: сервис людей не отвечает, имена ответственного и авторов не показаны.</p>}
      {(a.needs_fill || a.needs_placement) && (
        <p role="status" className="rounded-md bg-warning/15 px-2.5 py-1.5 text-warning">
          {a.needs_placement ? 'Требует размещения: помещения или контейнера, где он стоял, больше нет. ' : ''}
          {a.needs_fill ? 'Требует заполнения: не все обязательные свойства заданы.' : ''}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {a.can.edit && (a.state !== 'retired' || a.can.manage) ? (
          <Tip label={a.state === 'retired' ? 'Объект списан; другое состояние вернёт его на учёт; возврат запишется в историю'
            : a.can.manage ? 'Смена запишется в историю объекта; «списан» снимает его с учёта, вложенное останется в помещении без места'
              : 'Смена запишется в историю объекта; списать может только администратор здания'}>
            <select className={select} value={a.state} aria-label="Состояние объекта" onChange={e => act(setAssetState(a, e.target.value as AssetState))}>
              {Object.entries(STATES).filter(([k]) => k !== 'retired' || a.can.manage).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Tip>
        ) : <StateBadge a={a} />}
        {a.x != null && floor && (
          <Button asChild variant="outline" size="sm" hint="Открыть план этажа, выделив помещение, где стоит объект"><a href={to.plan(building, floor.id, a.room_id)}><MapIcon className="size-4" /> На плане</a></Button>
        )}
        {a.can.move && a.state !== 'retired' && floor && (
          <Button asChild variant="outline" size="sm" hint={a.portable
            ? 'Новое место — щелчком на плане, можно на другом этаже; переносной объект перемещает и ответственный'
            : 'Новое место — щелчком на плане, можно на другом этаже; вложенные объекты переедут вместе'}>
            <a href={to.move(building, floor.id, a.id)}><Move className="size-4" /> Переместить</a>
          </Button>
        )}
        <Button asChild variant="outline" size="sm" hint="Открыть QR-метку объекта для печати: PDF, наклейка 40 мм; по ней откроется эта карточка">
          <a href={assetLabelUrl(a.id)} target="_blank" rel="noreferrer"><QrCode className="size-4" /> Метка</a>
        </Button>
        {admin && (
          <Button asChild variant="outline" size="sm" hint="Журнал: все события этого объекта — кто, что и когда менял">
            <a href={to.journal(building, { asset: a.id })} aria-label="События объекта в журнале"><History className="size-4" /></a>
          </Button>
        )}
      </div>
      {a.container_id && <p className="text-muted-foreground">Стоит внутри: {boxes.find(b => b.id === a.container_id)?.type_name ?? 'другого объекта'}. «Переместить» вынет его на план.</p>}
      {a.can.move && a.state !== 'retired' && boxes.length > 0 && (
        <label className="grid gap-1 text-muted-foreground">Поставить внутрь
          <Tip label="Поместить объект в контейнер этого здания: дальше он будет переезжать вместе с ним">
            <select className={select} value={a.container_id ?? ''} aria-label="Поставить внутрь" onChange={e => { if (e.target.value) act(moveAssetInto(a, e.target.value)) }}>
              <option value="">— выберите контейнер —</option>
              {boxes.map(b => <option key={b.id} value={b.id}>{b.type_name} · {b.inventory_no}</option>)}
            </select>
          </Tip>
        </label>
      )}
      <dl className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-x-3 gap-y-1.5 [&_input]:min-w-0 [&_select]:w-full [&_select]:min-w-0">
        <dt className="text-muted-foreground">Отвечает</dt>
        <dd>{a.can.manage ? (
          <Tip label="Ответственный получает право на этот объект, прежний его теряет; смена запишется в историю">
            <select className={`${select} max-w-full`} value={a.responsible_id ?? ''} aria-label="Ответственный"
              onChange={e => act(setAssetResponsible(a, e.target.value || null))}>
              <option value="">не назначен</option>
              {people.map(p => <option key={p.id} value={p.id}>{p.full_name}</option>)}
              {a.responsible_id && !people.some(p => p.id === a.responsible_id) && <option value={a.responsible_id}>{names[a.responsible_id] ?? '…'}</option>}
            </select>
          </Tip>
        ) : (a.responsible_id ? names[a.responsible_id] ?? '…' : 'не назначен')}</dd>
        {a.schema.map(p => (
          <Field key={p.key} p={p} value={a.props[p.key]} editable={editable(p) && a.state !== 'retired'}
            onSave={v => act(patchAsset(a, { props: { [p.key]: v } }))} />
        ))}
        {a.type_props.filter(p => p.value != null && p.value !== '').map(p => (
          <Field key={`type.${p.key}`} p={p} value={p.value} editable={false} onSave={() => {}} />
        ))}
        <dt className="text-muted-foreground">Примечание</dt>
        <dd>{a.can.edit ? <Text value={a.note} label="Примечание" onSave={v => act(patchAsset(a, { note: v }))} /> : show(a.note)}</dd>
      </dl>
      {a.children.length > 0 && (
        <div>
          <h3 className="font-medium">Внутри</h3>
          <ul className="mt-1 grid gap-0.5">
            {a.children.map(c => <li key={c.id}><Tip label="Карточка вложенного объекта; он переезжает вместе с этим"><a className="text-primary" href={to.assets(building, c.id)}>{c.type_name} · {c.inventory_no}</a></Tip></li>)}
          </ul>
        </div>
      )}
      <div>
        <div className="flex items-center gap-2">
          <h3 className="font-medium">Файлы</h3>
          {a.can.edit && <Button variant="ghost" size="sm" hint="Фото или документ (PDF, Word, Excel) до 25 МБ; в истории объекта появится запись"
            onClick={() => picker.current?.click()}><Paperclip className="size-4" /> Приложить</Button>}
          {a.can.edit && <Button variant="ghost" size="sm" className="md:hidden" hint="Сфотографировать объект камерой телефона и приложить снимок к карточке"
            onClick={() => camera.current?.click()}><Camera className="size-4" /> Снять</Button>}
          <input ref={picker} type="file" className="hidden" accept="image/*,.pdf,.doc,.docx,.xls,.xlsx" data-testid="asset-file"
            onChange={e => { const f = e.target.files?.[0]; if (f) act(addAssetFile(a.id, f)); e.target.value = '' }} />
          <input ref={camera} type="file" className="hidden" accept="image/*" capture="environment" data-testid="asset-camera"
            onChange={e => { const f = e.target.files?.[0]; if (f) act(addAssetFile(a.id, f)); e.target.value = '' }} />
        </div>
        {files.length === 0 ? <p className="text-muted-foreground">Фотографий и документов нет.</p> : (
          <ul className="mt-1 grid gap-1" data-testid="asset-files">
            {files.map(f => (
              <li key={f.id} className="flex items-center gap-2">
                {f.kind === 'photo'
                  ? <Tip label="Открыть фото целиком в новой вкладке"><a href={assetFileUrl(f.id)} target="_blank" rel="noreferrer"><img src={assetFileUrl(f.id)} alt={f.name} className="size-12 rounded border object-cover" /></a></Tip>
                  : <FileText className="size-4 text-muted-foreground" />}
                <Tip label="Открыть файл в новой вкладке">
                  <a className="min-w-0 flex-1 truncate text-primary" href={assetFileUrl(f.id)} target="_blank" rel="noreferrer">{f.name}</a>
                </Tip>
                {a.can.edit && <Button variant="ghost" size="sm" hint="Удалить файл из карточки без возврата; в истории останется запись об этом"
                  onClick={() => act(deleteAssetFile(f.id))}>Убрать</Button>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <Comments me={me} building={building} target_kind="asset" target_id={a.id} admin={admin} />
      <div>
        <h3 className="font-medium">История</h3>
        <ul className="mt-1 grid gap-1.5" data-testid="asset-history">
          {history.map(h => (
            <li key={h.id} className="rounded-md border px-2 py-1.5">
              <div className="flex items-center gap-2">
                <span className="flex-1">{ACTIONS[h.action] ?? h.action}</span>
                {a.can.manage && (h.action === 'changed' || h.action === 'state') && (
                  <Button variant="ghost" size="sm" hint="Вернуть значения до этого изменения, если поля с тех пор не менялись; откат тоже запишется в историю"
                    onClick={() => act(revertAsset(a.id, h.id))}><Undo2 className="size-4" /> Откатить</Button>
                )}
              </div>
              {Object.entries(h.changes).map(([field, [was, now]]) => {
                const prop = field.startsWith('props.') ? a.schema.find(p => `props.${p.key}` === field) : undefined
                const title = field.startsWith('props.') ? prop?.title ?? field
                  : field === 'state' ? 'Состояние' : field === 'note' ? 'Примечание' : null
                // a choice in the words of its options, as the field shows it: «изношен», not «worn»
                const value = (v: unknown) => (field === 'state' ? STATES[v as AssetState] ?? show(v)
                  : prop?.options?.find(o => o.value === v)?.title ?? show(v))
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

/** What is in a field: the saved value, and as it changes — someone else's change comes in live — the new one;
 * but not while the person is typing there: what they began stays until they leave the field. */
function useDraft(saved: string) {
  const [draft, setDraft] = useState(saved)
  const [base, setBase] = useState(saved)
  const [typing, setTyping] = useState(false)
  if (saved !== base && !typing) { setBase(saved); setDraft(saved) }
  return { draft, setDraft, focus: () => setTyping(true), blur: () => setTyping(false) }
}

function Text({ value, label, onSave }: { value: string; label: string; onSave: (v: string) => void }) {
  const { draft, setDraft, focus, blur } = useDraft(value)
  return (
    <Tip label="Сохраняется по Enter или при уходе из поля; прежний текст останется в истории">
      <Input className="h-8" value={draft} aria-label={label} onChange={e => setDraft(e.target.value)} onFocus={focus}
        onBlur={() => { blur(); if (draft !== value) onSave(draft) }} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />
    </Tip>
  )
}

/** A property by the schema of the type: a field for whoever may edit it, text for the rest. */
function Field({ p, value, editable, onSave }: { p: Prop; value: unknown; editable: boolean; onSave: (v: unknown) => void }) {
  const { draft: v, setDraft: setV, focus, blur } = useDraft(value == null ? '' : String(value))
  const label = `${p.title}${p.unit ? `, ${p.unit}` : ''}`
  const commit = () => {
    blur()
    const next = v === '' ? null : p.kind === 'number' ? Number(v.replace(',', '.')) : v
    if (next !== (value ?? null)) onSave(next)
  }
  let control
  if (!editable) {
    control = p.kind === 'choice' ? p.options?.find(o => o.value === value)?.title ?? show(value) : show(value)
  } else if (p.kind === 'bool') {
    control = <Tip label={SAVED_AT_ONCE}><input type="checkbox" className="size-4 accent-primary" aria-label={label} checked={value === true} onChange={e => onSave(e.target.checked)} /></Tip>
  } else if (p.kind === 'choice') {
    control = (
      <Tip label={SAVED_AT_ONCE}>
        <select className={`${select} max-w-full`} aria-label={label} value={value == null ? '' : String(value)} onChange={e => onSave(e.target.value || null)}>
          <option value="">—</option>{p.options?.map(o => <option key={o.value} value={o.value}>{o.title}</option>)}
        </select>
      </Tip>
    )
  } else {
    control = (
      <Tip label={p.kind === 'number' ? 'Число, дробная часть — через запятую или точку; сохраняется по Enter или при уходе из поля'
        : 'Сохраняется по Enter или при уходе из поля; прежнее значение останется в истории'}>
        <Input className="h-8" aria-label={label} type={p.kind === 'date' ? 'date' : 'text'} inputMode={p.kind === 'number' ? 'decimal' : undefined}
          value={v} onChange={e => setV(e.target.value)} onFocus={focus} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />
      </Tip>
    )
  }
  return <><dt className="text-muted-foreground">{label}{p.required ? ' *' : ''}</dt><dd>{control}</dd></>
}
