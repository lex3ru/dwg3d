import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  addComment, assetTone, createAsset, createAssets, getAsset, getFloorPlan, getProposal, listAllAssets, numberOf, listAllTypes, listComments, listProducts, moveAsset,
  productLabel, type Product,
  type Asset, type CatalogType, type Comment, type FloorPlanData, type Me, type ProposalShow, type TreeFloor,
} from '../api'
import { CommentList } from '../components/Comments'
import { FloorPlan, type Dot, type Mark } from '../components/FloorPlan'
import { itemOf } from '../components/glyphs'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Tip } from '../components/ui/tooltip'
import { useEvents } from '../stream'
import { cn } from '../lib/utils'
import { PlanViews } from '../shell/PlanViews'
import { to } from '../shell/route'

const NOTE_HINT = 'Заметка к месту на плане: щелчок по точке, затем текст; её увидят все, кто видит план этого места'

/** The 2D plan of a floor: pick a floor, pick a room. */
export function Plan({ me, building, floors, floor, room, admin, move, proposal }: {
  me: Me; building: string; floors: TreeFloor[]; floor?: string; room?: string
  /** the object being moved: the next click on the plan is its new place */
  move?: string
  /** a proposal of the copilot: its changes are drawn over the plan */
  proposal?: string
  /** the building's administrator places objects here */
  admin?: boolean
}) {
  // the ground floor first, when there is one
  const fallback = floors.find(f => f.level === 1) ?? floors[0]
  const active = floors.find(f => f.id === floor) ?? fallback
  const [plan, setPlan] = useState<{ floor: string; data: FloorPlanData } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [drawn, setDrawn] = useState(0)                     // the plan changes: a room merged, split, a new revision
  useEffect(() => {
    if (!active) return
    let stale = false
    getFloorPlan(active.id).then(data => { if (!stale) { setPlan({ floor: active.id, data }); setError(null) } },
      (e: Error) => { if (!stale) setError(e.message) })
    return () => { stale = true }
  }, [active, drawn])
  useEvents(event => { if (event.type.startsWith('buildings.room.') || event.type === 'buildings.revision.published') setDrawn(n => n + 1) })
  // splitting a room: two points of a line across it
  // the objects standing on the floor (those the user may see)
  const [assets, setAssets] = useState<Asset[]>([])
  const activeId = active?.id
  const loadAssets = useCallback(() => {
    if (activeId) listAllAssets({ floor_id: activeId }).then(setAssets, () => setAssets([]))
  }, [activeId])
  useEffect(loadAssets, [loadAssets])
  useEvents(event => { if (event.type.startsWith('assets.')) loadAssets() })
  // placing: a type and a number, then a click on the plan
  const [types, setTypes] = useState<CatalogType[]>([])
  const [placing, setPlacing] = useState<{ type: string; number: string; product: string } | null>(null)
  // several of a kind: the points are clicked one by one, the numbers go in a row
  const [series, setSeries] = useState<{ type: string; numbered: boolean; prefix: string; start: string; width: string; points: [number, number][] } | null>(null)
  // comments to points of the floor: marks on the plan; a new one — a click, then the text
  const [notes, setNotes] = useState<Comment[]>([])
  const [noting, setNoting] = useState<{ x: number; y: number; text: string } | 'pick' | null>(null)
  const [chosenNote, setChosenNote] = useState<string | undefined>()
  const loadNotes = useCallback(() => {
    if (activeId) listComments({ building_id: building, target_kind: 'point', floor_id: activeId }).then(setNotes, () => setNotes([]))
  }, [activeId, building])
  useEffect(loadNotes, [loadNotes])
  useEvents(event => { if (event.type.startsWith('buildings.comment.')) loadNotes() })
  const sendNote = (e: React.FormEvent) => {
    e.preventDefault()
    if (!noting || noting === 'pick' || !noting.text.trim() || !active) return
    addComment({ building_id: building, target_kind: 'point', floor_id: active.id, x: noting.x, y: noting.y, body: noting.text.trim() })
      .then(() => { setNoting(null); setError(null); loadNotes() }, (ex: Error) => setError(ex.message))
  }
  // the places a proposal of the copilot would change, drawn over the objects
  const [loaded, setLoaded] = useState<{ id: string; summary: string; status: string; shows: ProposalShow[] } | null>(null)
  useEffect(() => {
    if (proposal) getProposal(proposal).then(p => setLoaded({ id: p.id, summary: p.summary, status: p.status, shows: p.shows ?? [] }), () => {})
  }, [proposal])
  const shown = proposal && loaded?.id === proposal ? loaded : null
  const marks: Mark[] = shown && active ? shown.shows.filter(s => s.floor_id === active.id && s.x != null && s.y != null).map(s => ({
    kind: s.kind, x: s.x!, y: s.y!, title: s.title, from: s.from && s.from.floor_id === active.id ? { x: s.from.x, y: s.from.y } : null })) : []
  const [fetched, setFetched] = useState<Asset | null>(null)
  useEffect(() => { if (move) getAsset(move).then(setFetched, (e: Error) => setError(e.message)) }, [move])
  const moving = fetched?.id === move ? fetched : null
  const moveTo = (x: number, y: number) => {
    if (!moving || !active) return
    moveAsset(moving, active.id, x, y).then(a => { setError(null); location.hash = to.assets(building, a.id) }, (e: Error) => setError(e.message))
  }
  const number = (s: NonNullable<typeof series>, i: number) =>
    (s.numbered ? `${s.prefix}${String((Number(s.start) || 0) + i).padStart(Number(s.width) || 1, '0')}` : 'без учёта')
  const placeSeries = () => {
    if (!series || !active) return
    if (!series.type || !series.points.length) return setError('Выберите тип и отметьте места на плане')
    createAssets({ type_id: series.type, floor_id: active.id, points: series.points,
      ...(series.numbered ? { prefix: series.prefix, start: Number(series.start) || 0, width: Number(series.width) || 1 } : {}) }).then(() => {
      setSeries(null); setError(null); loadAssets()
    }, (e: Error) => setError(e.message))
  }
  // the catalog's types, archived ones too: the size and shape of every object drawn, the active ones to place more
  useEffect(() => { listAllTypes().then(setTypes, () => {}) }, [])
  const byType = useMemo(() => new Map(types.map(t => [t.id, t])), [types])
  // the makes and models of the type being placed, to name one
  const [products, setProducts] = useState<Product[]>([])
  useEffect(() => { if (placing?.type) listProducts(placing.type).then(setProducts, () => setProducts([])); else setProducts([]) }, [placing?.type])
  const place = (x: number, y: number) => {
    if (!placing?.type || !active) return setError('Выберите тип объекта')
    createAsset({ type_id: placing.type, product_id: placing.product || null, floor_id: active.id, x, y, inventory_no: placing.number.trim() || null }).then(a => {
      setPlacing(null); setError(null); loadAssets(); location.hash = to.assets(building, a.id)
    }, (e: Error) => setError(e.message))
  }
  if (!active) return <p className="text-sm text-muted-foreground">В здании пока нет этажей.</p>
  const chosen = active.rooms.find(r => r.id === room)
  return (
    <section>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">План</h1>
        <PlanViews building={building} list={false} />
        <nav className="flex flex-wrap gap-1" aria-label="Этажи" data-testid="floor-tabs">
          {[...floors].reverse().map(f => (
            <Tip key={f.id} label={`${f.name || `Этаж ${f.level ?? ''}`}: ${move ? 'выбрать новое место объекта на этом этаже' : 'план, помещения и объекты этажа'}`}>
              <a href={move ? to.move(building, f.id, move) : to.plan(building, f.id)} aria-current={f.id === active.id ? 'true' : undefined}
                className={cn('min-w-8 rounded-md border px-2 py-1 text-center text-sm hover:bg-secondary',
                  f.id === active.id && 'border-primary bg-primary text-primary-foreground hover:bg-primary')}>
                {f.level ?? '?'}
                {/* the same number twice (a plan without its title): the start of the name tells them apart */}
                {floors.some(o => o.id !== f.id && o.level === f.level) && <span className="ml-1 text-xs opacity-80">{(f.name || '').slice(0, 14)}</span>}
              </a>
            </Tip>
          ))}
        </nav>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{active.name} · помещений: {active.rooms.length} · объектов: {assets.filter(a => a.x != null).length}</p>
      {moving && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border bg-card p-2 text-sm" data-testid="moving">
          <span>Перемещение: <b>{moving.type_name}</b> · {numberOf(moving)} — щёлкните новое место на плане (этаж можно сменить)</span>
          <Button asChild variant="ghost" size="sm" hint="Оставить объект на прежнем месте и вернуться к его карточке"><a href={to.assets(building, moving.id)}>Отмена</a></Button>
        </div>
      )}
      {admin && !move && series && (
        <div className="mt-2 flex flex-wrap items-end gap-2 rounded-lg border bg-card p-2" data-testid="series">
          <label className="grid gap-0.5 text-xs text-muted-foreground">Тип
            <Tip label="Один тип каталога для всех отмеченных мест: от него размер, свойства и 3D-модель">
              <select className="h-8 rounded-md border bg-card px-2 text-sm" value={series.type} aria-label="Тип объектов"
                onChange={e => setSeries({ ...series, type: e.target.value })}>
                <option value="">— из каталога —</option>
                {types.filter(t => t.active).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </Tip>
          </label>
          <Tip label="Снять галочку — объекты встанут на план без учёта, номера им дадут потом в карточках">
            <label className="flex items-center gap-1.5 pb-2 text-sm">
              <input type="checkbox" checked={series.numbered} aria-label="С инвентарными номерами" onChange={e => setSeries({ ...series, numbered: e.target.checked })} />
              на учёт
            </label>
          </Tip>
          {series.numbered && (
            <>
              <label className="grid gap-0.5 text-xs text-muted-foreground">Начало номера
                <Tip label="Общая часть всех номеров перед числом, например «КР-»">
                  <Input className="h-8 w-28" value={series.prefix} placeholder="КР-" onChange={e => setSeries({ ...series, prefix: e.target.value })} />
                </Tip>
              </label>
              <label className="grid gap-0.5 text-xs text-muted-foreground">С числа
                <Tip label="Число первого номера; следующие идут подряд в порядке отметок на плане">
                  <Input className="h-8 w-20" inputMode="numeric" value={series.start} onChange={e => setSeries({ ...series, start: e.target.value.replace(/\D/g, '') })} />
                </Tip>
              </label>
              <label className="grid gap-0.5 text-xs text-muted-foreground">Цифр
                <Tip label="Длина числа: недостающие цифры дополнятся нулями слева, при 4 — 0001">
                  <Input className="h-8 w-14" inputMode="numeric" value={series.width} onChange={e => setSeries({ ...series, width: e.target.value.replace(/\D/g, '') })} />
                </Tip>
              </label>
            </>
          )}
          <span className="pb-1.5 text-sm" data-testid="series-numbers">
            {series.points.length ? `отмечено ${series.points.length}: ${number(series, 0)}${series.points.length > 1 ? ` … ${number(series, series.points.length - 1)}` : ''}`
              : 'отмечайте места на плане'}
          </span>
          <Button size="sm" disabled={!series.points.length || !series.type} onClick={placeSeries}
            hint={!series.type ? 'Сначала выберите тип объектов' : !series.points.length ? 'Сначала отметьте места на плане'
              : series.numbered ? 'Поставить на учёт все отмеченные объекты с номерами подряд; если хоть один номер занят, не создастся ни один'
                : 'Поставить все отмеченные объекты на план без учёта; номера им дадут потом в карточках'}>
            Поставить {series.points.length || ''}
          </Button>
          {series.points.length > 0 && <Button variant="ghost" size="sm" hint="Снять с плана последнюю отметку; номера остальных не изменятся"
            onClick={() => setSeries({ ...series, points: series.points.slice(0, -1) })}>Убрать последнюю</Button>}
          <Button variant="ghost" size="sm" hint="Ничего не создавать и снять все отметки" onClick={() => { setSeries(null); setError(null) }}>Отмена</Button>
        </div>
      )}
      {noting && (
        <form onSubmit={sendNote} className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border bg-card p-2 text-sm" data-testid="noting">
          {noting === 'pick' ? <span>Щёлкните точку на плане, к которой относится комментарий</span> : (
            <>
              <Input className="h-8 min-w-56 flex-1" autoFocus value={noting.text} aria-label="Текст комментария" placeholder="Что здесь не так или на что обратить внимание"
                onChange={e => setNoting({ ...noting, text: e.target.value })} />
              <Button type="submit" size="sm" disabled={!noting.text.trim()}
                hint={noting.text.trim() ? 'Комментарий увидят все, кто видит план этого места; закрыть или удалить его могут автор и администратор здания' : 'Сначала напишите текст'}>
                Оставить
              </Button>
            </>
          )}
          <Button type="button" variant="ghost" size="sm" hint="Не оставлять комментарий" onClick={() => setNoting(null)}>Отмена</Button>
        </form>
      )}
      {admin && !move && !series && (placing ? (
        <div className="mt-2 flex flex-wrap items-end gap-2 rounded-lg border bg-card p-2" data-testid="placing">
          <label className="grid gap-0.5 text-xs text-muted-foreground">Тип
            <Tip label="Тип каталога: от него размер, свойства и 3D-модель объекта">
              <select className="h-8 rounded-md border bg-card px-2 text-sm" value={placing.type} aria-label="Тип объекта"
                onChange={e => setPlacing({ ...placing, type: e.target.value })}>
                <option value="">— из каталога —</option>
                {types.filter(t => t.active).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </Tip>
          </label>
          {products.length > 0 && (
            <label className="grid gap-0.5 text-xs text-muted-foreground">Марка и модель
              <Tip label="Какой именно модели объект; можно оставить «не указана» и выбрать в карточке потом">
                <select className="h-8 rounded-md border bg-card px-2 text-sm" value={placing.product} aria-label="Марка и модель"
                  onChange={e => setPlacing({ ...placing, product: e.target.value })}>
                  <option value="">не указана</option>
                  {products.map(p => <option key={p.id} value={p.id}>{productLabel(p)}</option>)}
                </select>
              </Tip>
            </label>
          )}
          <label className="grid gap-0.5 text-xs text-muted-foreground">Инвентарный номер
            <Tip label="Можно оставить пустым: объект встанет на план без учёта, на учёт его поставят из карточки. Номер не повторяется никогда: даже списанного объекта занят">
              <Input className="h-8 w-40" value={placing.number} placeholder="пусто — без учёта" onChange={e => setPlacing({ ...placing, number: e.target.value })} />
            </Tip>
          </label>
          <span className="pb-1.5 text-sm">и щёлкните место на плане</span>
          <Button variant="ghost" size="sm" hint="Ничего не ставить" onClick={() => { setPlacing(null); setError(null) }}>Отмена</Button>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button variant="outline" size="sm" hint="Поставить один объект: тип и щелчок по месту на плане; с инвентарным номером — сразу на учёт"
            onClick={() => setPlacing({ type: '', number: '', product: '' })}>Поставить объект</Button>
          <Button variant="outline" size="sm" hint="Несколько объектов одного типа: места отмечаются щелчками; на учёт с номерами подряд или без учёта"
            onClick={() => setSeries({ type: '', numbered: true, prefix: '', start: '1', width: '4', points: [] })}>Поставить несколько</Button>
          {!noting && <Button variant="outline" size="sm" hint={NOTE_HINT} onClick={() => setNoting('pick')}>Комментарий к точке</Button>}
        </div>
      ))}
      {!admin && !noting && !move && <Button className="mt-2" variant="outline" size="sm" hint={NOTE_HINT} onClick={() => setNoting('pick')}>Комментарий к точке</Button>}
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {plan?.floor !== active.id && !error && (
        <div role="status" className="mt-3 grid h-64 animate-pulse place-items-center rounded-lg border bg-card text-sm text-muted-foreground" data-testid="plan-loading">
          Загружаю план этажа…
        </div>
      )}
      {shown && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm" data-testid="plan-proposal">
          <span className="font-medium">Предложение помощника:</span>
          <span className="min-w-0 flex-1 truncate">{shown.summary}</span>
          <span className="text-xs text-muted-foreground">зелёное — поставить, синее — переставить, красное — списать или удалить{shown.status !== 'open' && ` · ${shown.status === 'applied' ? 'уже применено' : shown.status === 'rejected' ? 'отклонено' : 'устарело'}`}</span>
          <Tip label="Убрать пометки предложения с плана"><a href={to.plan(building, active.id)} className="text-primary underline underline-offset-2">скрыть</a></Tip>
        </div>
      )}
      {plan?.floor === active.id && (
        <FloorPlan plan={plan.data} selected={room} className="mt-3 max-h-[70vh]" marks={marks}
          items={assets.filter(a => a.x != null).map(a => itemOf(a, byType, { tone: assetTone(a) as Dot['tone'], chosen: a.id === move }))}
          dots={[
            ...(series?.points ?? []).map(([x, y], i) => ({ id: `new-${i}`, x, y, tone: 'warn' as const, title: number(series!, i), chosen: true })),
            ...notes.filter(n => n.x != null).map(n => ({ id: `note-${n.id}`, x: n.x!, y: n.y!, tone: 'note' as const, title: n.body, chosen: n.id === chosenNote })),
            ...(noting && noting !== 'pick' ? [{ id: 'note-new', x: noting.x, y: noting.y, tone: 'note' as const, title: 'новый комментарий', chosen: true }] : []),
          ]}
          onDot={id => { if (id.startsWith('note-')) setChosenNote(id.slice(5)); else if (!id.startsWith('new-')) location.hash = to.assets(building, id) }}
          onPoint={moving ? moveTo : series ? (x, y) => setSeries({ ...series, points: [...series.points, [x, y]] }) : placing ? place
            : noting === 'pick' ? (x, y) => setNoting({ x, y, text: '' }) : undefined}
          onSelect={id => { location.hash = to.plan(building, active.id, id) }} />
      )}
      {notes.length > 0 && (
        <div className="mt-3" data-testid="plan-notes">
          <h2 className="text-sm font-medium">Комментарии к точкам · {notes.length}</h2>
          <CommentList items={notes} me={me} admin={!!admin} onChanged={loadNotes} onError={setError} chosen={chosenNote} />
        </div>
      )}
      {/* on a phone the card is a page of its own; here: what is chosen, one tap from its card */}
      {chosen && (
        <Tip label="Карточка помещения: люди, ведомость, комментарии">
          <a href={to.rooms(building, chosen.id)} className="mt-2 flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm md:hidden">
            <span className="flex-1 font-medium">{chosen.name || 'Помещение без названия'}</span>
            <span className="text-muted-foreground">{chosen.area.toLocaleString('ru')} м²</span>
          </a>
        </Tip>
      )}
    </section>
  )
}
