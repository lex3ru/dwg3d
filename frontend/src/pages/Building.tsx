import { Box, FileDown, RefreshCw, Trash2, Upload } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  drawingWithObjects,
  deleteDrawing, getBuilding, getTree, listDrawings, listPlaced, patchFloor, placeDrawing, rebuildDrawing, uploadDrawing, uploadDrawingFile,
  type Building as BuildingInfo, type Drawing, type PlacedDrawing, type Placement, type TreeFloor,
} from '../api'
import { RevisionReview } from '../components/RevisionReview'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Tip } from '../components/ui/tooltip'
import { useEvents } from '../stream'

const STATUS: Record<string, [string, 'default' | 'accent' | 'success' | 'destructive']> = {
  queued: ['в очереди', 'default'], running: ['обрабатывается', 'accent'], done: ['готов', 'success'], error: ['ошибка', 'destructive'],
}
const size = (n: number | null) => (n == null ? '' : n > 1e6 ? `${(n / 1e6).toFixed(1)} МБ` : `${Math.ceil(n / 1e3)} КБ`)

/** One building: its drawings (upload, state of the build, opening in the viewer), floors and rooms. */
export function Building({ id, review }: { id: string; review?: string }) {
  const [building, setBuilding] = useState<BuildingInfo | null>(null)
  const [drawings, setDrawings] = useState<Drawing[]>([])
  const [placed, setPlaced] = useState<PlacedDrawing[]>([])
  const [floors, setFloors] = useState<TreeFloor[]>([])
  const [live, setLive] = useState<Record<string, { progress: number; message: string }>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [reviewing, setReviewing] = useState<string | null>(review ?? null)
  const picker = useRef<HTMLInputElement>(null)
  const target = useRef<string | null>(null)        // the drawing a picked file is a new version of

  const load = useCallback(() =>
    Promise.all([getBuilding(id), listDrawings(id), listPlaced(id), getTree(id)]).then(([b, d, p, f]) => {
      setBuilding(b); setDrawings(d); setPlaced(p); setFloors(f); setError(null)
    }, (e: Error) => setError(e.message)), [id])
  useEffect(() => { load() }, [load])
  useEvents(event => {
    if (event.type === 'import.build.progress') {
      const d = event.data as { drawing_id: string; progress: number; message: string }
      setLive(l => ({ ...l, [d.drawing_id]: { progress: d.progress, message: d.message } }))
    } else if (event.type.startsWith('import.') || event.type.startsWith('buildings.')) load()
  })

  const act = (work: Promise<unknown>) => {
    setBusy(true)
    // the reload clears the error, so a refusal is shown after it
    let refused: string | null = null
    work.catch((e: Error) => { refused = e.message }).then(load).then(() => setError(refused)).finally(() => setBusy(false))
  }
  const picked = (files: FileList | null) => {
    const file = files?.[0]
    if (!file) return
    act(target.current
      ? uploadDrawingFile(target.current, file).then(d => { if (d.unchanged) throw new Error('Это тот же файл — чертёж не изменился') })
      : uploadDrawing(id, file))
    if (picker.current) picker.current.value = ''
  }
  const pick = (drawing: string | null) => { target.current = drawing; picker.current?.click() }

  if (!building) return <p className="text-sm text-muted-foreground">{error ?? 'Загрузка…'}</p>
  const rooms = floors.reduce((n, f) => n + f.rooms.length, 0)
  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">{building.name}</h1>
        {building.address && <p className="text-sm text-muted-foreground">{building.address}</p>}
        {floors.length > 0 && <p className="mt-1 text-sm text-muted-foreground" data-testid="totals">Этажей: {floors.length} · помещений: {rooms}</p>}
      </div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

      <div>
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold">Чертежи</h2>
          <Button size="sm" onClick={() => pick(null)} disabled={busy}
            hint="Добавить в здание план в формате DWG или DXF: он соберётся в этажи и помещения"><Upload className="size-4" /> Загрузить чертёж</Button>
          <input ref={picker} type="file" accept=".dwg,.dxf" className="hidden" data-testid="file"
            onChange={e => picked(e.target.files)} />
        </div>
        {drawings.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">Загрузите поэтажные планы здания в формате DWG или DXF — одним файлом или по файлу на этаж или корпус.</p>
        ) : (
          <ul className="mt-3 divide-y rounded-lg border bg-card" data-testid="drawings">
            {drawings.map(d => {
              const b = d.build
              const place = placed.find(p => p.id === d.id)
              const shown = place?.build_id
              const revision = place?.revision
              // a build that would retire rooms waits for the administrator; one discarded is not waited for
              const draft = revision?.status === 'draft' && revision.n === b?.n ? revision : null
              const decided = !!b && !!revision && revision.n >= b.n
              // built, but the building follows the event and may be a moment behind
              const publishing = b?.status === 'done' && shown !== b.id && !decided
              const [label, tone] = publishing ? STATUS.running : STATUS[b?.status ?? 'queued']
              const running = b?.status === 'queued' || b?.status === 'running' || publishing
              const now = live[d.id]
              const progress = publishing ? 0.99 : b?.status === 'running' ? (now?.progress ?? b.progress) : 0
              return (
                <li key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5" data-drawing={d.name}
                  data-status={publishing ? 'running' : b?.status}>
                  <div className="min-w-40 flex-1">
                    <div className="font-medium">{d.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {size(d.size)}{d.file_n && d.file_n > 1 ? ` · файл ${d.file_n}` : ''}{b ? ` · сборка ${b.n}` : ''}
                    </div>
                    {running && (
                      <div className="mt-1.5">
                        <div className="h-1.5 w-full max-w-xs overflow-hidden rounded bg-secondary" role="progressbar"
                          aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
                          <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
                        </div>
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {publishing ? 'Публикация' : b?.status === 'running' ? (now?.message ?? b.message) : 'В очереди'}
                        </div>
                      </div>
                    )}
                    {b?.status === 'error' && <div role="alert" className="mt-1 text-sm text-destructive">{b.error}</div>}
                    {draft && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm" data-testid="draft">
                        <Tip label="Сборка снимет помещения, поэтому здание её не показывает, пока администратор не решит"><Badge variant="warning">сборка {draft.n} ждёт проверки</Badge></Tip>
                        <span className="text-muted-foreground">снимет помещений: {draft.summary.retired ?? 0}</span>
                        <Button size="sm" variant="outline" onClick={() => setReviewing(reviewing === draft.id ? null : draft.id)}
                          hint={reviewing === draft.id ? 'Свернуть разбор; сборка так и будет ждать решения'
                            : 'Сверить помещения сборки с прежними и решить: опубликовать её или отбросить'}>
                          {reviewing === draft.id ? 'Скрыть' : 'Проверить'}
                        </Button>
                      </div>
                    )}
                    {revision?.status === 'discarded' && b && revision.n === b.n && (
                      <div className="mt-1 text-xs text-muted-foreground">Сборка {b.n} отброшена — показана опубликованная</div>
                    )}
                    {place && shown && placed.length > 1 && (
                      <PlacementForm key={place.version} value={place.placement} disabled={busy}
                        onSave={v => act(placeDrawing(id, place, v))} />
                    )}
                  </div>
                  <Tip label="Состояние последней сборки: из готовой здание берёт этажи, помещения и 3D-модель"><Badge variant={tone}>{label}</Badge></Tip>
                  {shown && (
                    <Button asChild size="sm" hint="3D и план чертежа в редакторе: помещения, объекты, слои инженерных систем"><a href={`#/f/${d.id}`}><Box className="size-4" /> Открыть</a></Button>
                  )}
                  {shown && (
                    <Button variant="outline" size="sm" disabled={busy || running}
                      hint="Скачать DXF этого чертежа, где объекты учёта стоят блоками с атрибутами: номер, состояние, ответственный, помещение"
                      onClick={() => act(drawingWithObjects(id, d.id, 'dxf'))}>
                      <FileDown className="size-4" /> <span className="max-sm:hidden">С объектами</span>
                    </Button>
                  )}
                  <Button variant="outline" size="sm" disabled={busy || running} onClick={() => pick(d.id)}
                    hint="Заменить файл чертежа исправленным: начнётся новая сборка; недоступно, пока идёт текущая">
                    <Upload className="size-4" /> <span className="max-sm:hidden">Новый файл</span>
                  </Button>
                  <Button variant="ghost" size="icon" disabled={busy || running} aria-label="Собрать заново"
                    hint="Повторить сборку из того же файла с текущими настройками и правками редактора; недоступно, пока идёт сборка" onClick={() => act(rebuildDrawing(d.id))}>
                    <RefreshCw className="size-4" />
                  </Button>
                  <Button variant="ghost" size="icon" disabled={busy} aria-label="Удалить чертёж"
                    hint="Удалить чертёж вместе с его сборками; этажи и помещения из него будут сняты"
                    onClick={() => { if (confirm(`Удалить чертёж «${d.name}»? Его этажи и помещения будут сняты.`)) act(deleteDrawing(d.id)) }}>
                    <Trash2 className="size-4" />
                  </Button>
                  {draft && reviewing === draft.id && (
                    <div className="basis-full"><RevisionReview id={draft.id} onDone={() => { setReviewing(null); load() }} /></div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {floors.length > 0 && (
        <div>
          <h2 className="text-base font-semibold">Этажи</h2>
          <ul className="mt-3 divide-y rounded-lg border bg-card text-sm" data-testid="floors">
            {floors.map(f => (
              <FloorRow key={f.id + f.version} floor={f} drawing={drawings.length > 1 ? drawings.find(d => d.id === f.drawing_id)?.name : undefined}
                twin={floors.find(o => o.id !== f.id && o.level != null && o.level === f.level)} onSaved={load} />
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

const FIELDS: [keyof Placement, string, string][] = [
  ['dx', 'Сдвиг X, м', 'На сколько метров сдвинуть чертёж вправо по плану; влево — с минусом'],
  ['dy', 'Сдвиг Y, м', 'На сколько метров сдвинуть чертёж вверх по плану; вниз — с минусом'],
  ['dz', 'Высота, м', 'На сколько метров поднять весь чертёж; опустить — с минусом'],
  ['rotation', 'Поворот, °', 'Градусы против часовой стрелки, от −360 до 360'],
]

/** Where the drawing stands in the building, relative to the others (shown when there are several). */
function PlacementForm({ value, disabled, onSave }: { value: Placement; disabled: boolean; onSave: (v: Placement) => void }) {
  const [draft, setDraft] = useState(() => Object.fromEntries(FIELDS.map(([k]) => [k, String(value[k])])) as Record<keyof Placement, string>)
  const parsed = Object.fromEntries(FIELDS.map(([k]) => [k, Number(draft[k].replace(',', '.'))])) as Placement
  const valid = FIELDS.every(([k]) => draft[k].trim() !== '' && Number.isFinite(parsed[k])) && Math.abs(parsed.rotation) <= 360
  const changed = FIELDS.some(([k]) => parsed[k] !== value[k])
  return (
    <form className="mt-2 flex flex-wrap items-end gap-2" data-testid="placement"
      onSubmit={e => { e.preventDefault(); if (valid && changed) onSave(parsed) }}>
      <span className="w-full text-xs text-muted-foreground">Положение в здании</span>
      {FIELDS.map(([k, label, hint]) => (
        <label key={k} className="grid gap-0.5 text-xs text-muted-foreground">{label}
          <Tip label={hint}>
            <Input className="h-7 w-24 text-xs" inputMode="decimal" value={draft[k]} aria-label={label}
              onChange={e => setDraft({ ...draft, [k]: e.target.value })} />
          </Tip>
        </label>
      ))}
      <Button type="submit" size="sm" variant="outline" disabled={disabled || !valid || !changed}
        hint={!valid ? 'Переставить чертёж в здании; сначала исправьте числа — поворот не больше 360°'
          : !changed ? 'Переставить чертёж в здании; доступно, когда значения изменены'
            : 'Переставить чертёж: его этажи встанут на новое место в 3D-модели здания относительно других чертежей'}>Сохранить</Button>
    </form>
  )
}

/** A floor of the building: its number and name, which can be given by hand — a plan converted from a PDF or a
 * scan has no title written on it, and the import calls such a floor «Этаж (c0)», number 1. */
function FloorRow({ floor, drawing, twin, onSaved }: {
  floor: TreeFloor; drawing?: string
  /** another floor with the same number: the plan cannot tell them apart */
  twin?: TreeFloor
  onSaved: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [level, setLevel] = useState(String(floor.level ?? ''))
  const [name, setName] = useState(floor.name)
  const [error, setError] = useState<string | null>(null)
  const save = (e: React.FormEvent) => {
    e.preventDefault()
    const n = Number(level)
    if (level.trim() === '' || !Number.isInteger(n)) { setError('Номер — целое число, подвал — с минусом'); return }
    patchFloor(floor, { level: n, name: name.trim() || undefined }).then(() => { setEditing(false); setError(null); onSaved() },
      (ex: Error) => setError(ex.message))
  }
  if (editing) return (
    <li className="px-3 py-2" data-floor={floor.id}>
      <form onSubmit={save} className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-xs text-muted-foreground">№
          <Tip label="Номер этажа: по нему этажи идут по порядку и подписываются на плане; подвал — с минусом">
            <Input className="h-8 w-20" inputMode="numeric" value={level} aria-label="Номер этажа" onChange={e => setLevel(e.target.value)} />
          </Tip>
        </label>
        <label className="grid min-w-48 flex-1 gap-1 text-xs text-muted-foreground">Название
          <Input className="h-8" value={name} maxLength={200} aria-label="Название этажа" onChange={e => setName(e.target.value)} />
        </label>
        <Button type="submit" size="sm" hint="Новые сборки чертежа номер и название больше не поменяют">Сохранить</Button>
        <Button type="button" size="sm" variant="ghost" hint="Оставить как было" onClick={() => { setEditing(false); setError(null) }}>Отмена</Button>
      </form>
      {error && <p role="alert" className="mt-1 text-sm text-destructive">{error}</p>}
    </li>
  )
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2" data-floor={floor.id}>
      <span className="grid h-6 min-w-8 place-items-center rounded-md bg-secondary px-1.5 text-xs font-semibold">{floor.level ?? '?'}</span>
      <span className="min-w-40 flex-1">{floor.name || `Этаж ${floor.level ?? ''}`}
        {drawing && <span className="ml-2 text-xs text-muted-foreground">{drawing}</span>}</span>
      {twin && (
        <Tip label={`Тот же номер, что у «${twin.name || 'без названия'}»: на плане их не различить; задайте этажу его настоящий номер`}>
          <Badge variant="warning" data-testid="floor-twin">номер повторяется</Badge>
        </Tip>
      )}
      <span className="text-muted-foreground">помещений: {floor.rooms.length}</span>
      <Button size="sm" variant="ghost" hint="Задать номер и название этажа, если чертёж их не подписал; новые сборки их не поменяют"
        onClick={() => setEditing(true)}>Изменить</Button>
    </li>
  )
}
