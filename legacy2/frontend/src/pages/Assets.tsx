import { FileSpreadsheet, QrCode, Search, Upload } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'
import { ApiError, assetsReportUrl, importAssets, labelsSheet, listAssets, numberOf, STATES, type Asset, type AssetState, type TreeFloor } from '../api'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Tip } from '../components/ui/tooltip'
import { cn } from '../lib/utils'
import { to } from '../shell/route'
import { useEvents } from '../stream'

const select = 'h-8 rounded-md border bg-card px-2 text-sm'

/** What a state means for the object (the hint of its badge). */
const STATE_HINTS: Record<AssetState, string> = {
  in_use: 'Объект исправен и используется',
  faulty: 'Объект сломан и ждёт ремонта или списания',
  in_repair: 'Объект отдан в ремонт',
  in_storage: 'Объект убран на хранение и не используется',
  retired: 'Объект снят с учёта: свойства не меняются, вернуть его может только администратор здания',
}
const NEEDS_HINTS = {
  placement: 'Помещения или контейнера, где стоял объект, больше нет: ему нужно новое место',
  fill: 'Заданы не все обязательные свойства объекта',
}

/** A mark of attention (lists, the cabinet) with what it means. */
export function NeedsMark({ need, children }: { need: keyof typeof NEEDS_HINTS; children: ReactElement }) {
  return <Tip label={NEEDS_HINTS[need]}>{children}</Tip>
}

export function StateBadge({ a }: { a: Asset }) {
  return <Tip label={STATE_HINTS[a.state]}><Badge variant={a.state === 'in_use' ? 'default' : a.state === 'faulty' ? 'destructive' : 'warning'}>{STATES[a.state]}</Badge></Tip>
}

/** The objects of a building the user may see: by number, type, state; what needs attention. */
export function Assets({ building, floors, selected, admin, initialQuery, initialState, initialAttention }: {
  building: string; floors: TreeFloor[]; selected?: string
  /** the building's administrator loads objects from a file and prints labels */
  admin?: boolean
  initialQuery?: string
  /** filters given by the address (from «Обзор»): a state, objects needing a place or filling in */
  initialState?: string
  initialAttention?: string
}) {
  const picker = useRef<HTMLInputElement>(null)
  const [report, setReport] = useState<{ created: number } | { refused: string; rows: string[] } | null>(null)
  const [items, setItems] = useState<Asset[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState(initialQuery ?? '')
  const [state, setState] = useState<AssetState | ''>(initialState && initialState in STATES ? initialState as AssetState : '')
  const [attention, setAttention] = useState<'' | 'needs_fill' | 'needs_placement'>(
    initialAttention === 'needs_fill' || initialAttention === 'needs_placement' ? initialAttention : '')
  const [accounted, setAccounted] = useState<'' | 'true' | 'false'>('')     // on the books, off them, either
  const [error, setError] = useState<string | null>(null)
  const filter = { building_id: building, q, state, accounted, [attention || 'x']: attention ? 'true' : undefined }
  const load = useCallback(() => {
    listAssets({ ...filter, limit: '300' })
      .then(r => { setItems(r.items); setTotal(r.total); setError(null) }, (e: Error) => setError(e.message))
  }, [building, q, state, attention, accounted])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('assets.')) load() })
  const room = (a: Asset) => {
    for (const f of floors) { const r = f.rooms.find(x => x.id === a.room_id); if (r) return `${f.level ?? ''} эт. · ${r.name || 'без названия'}` }
    return ''
  }
  return (
    <section>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-1 text-xl font-semibold">Объекты</h1>
        <div className="relative w-56 max-w-full">
          <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
          <Tip label="Часть названия типа, инвентарного или заводского номера; список сужается по мере ввода">
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Номер или название" aria-label="Поиск объекта"
              className="h-8 w-full rounded-md border bg-card pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </Tip>
        </div>
        <Tip label="Оставить в списке объекты в выбранном состоянии; списанные видны, только если выбрать «списан»">
          <select className={select} value={state} onChange={e => setState(e.target.value as AssetState | '')} aria-label="Состояние">
            <option value="">любое состояние</option>
            {Object.entries(STATES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Tip>
        <Tip label="На учёте — с инвентарным номером; без учёта — стоят на плане, номера нет: такие можно удалить, а на учёт поставить из карточки">
          <select className={select} value={accounted} onChange={e => setAccounted(e.target.value as typeof accounted)} aria-label="Учёт">
            <option value="">на учёте и без</option>
            <option value="true">на учёте</option>
            <option value="false">без учёта</option>
          </select>
        </Tip>
        <Tip label="Объекты без обязательных свойств или потерявшие место: их помещение или контейнер исчезли">
          <select className={select} value={attention} onChange={e => setAttention(e.target.value as typeof attention)} aria-label="Требует внимания">
            <option value="">все</option>
            <option value="needs_fill">требует заполнения</option>
            <option value="needs_placement">требует размещения</option>
          </select>
        </Tip>
        <Tip label="Сколько объектов подходит под отбор; список показывает первые 300">
          <span className="text-sm text-muted-foreground" data-testid="assets-total">{total}</span>
        </Tip>
        <Button asChild size="sm" variant="outline" hint="Скачать список объектов по текущему фильтру, свойства — отдельными столбцами">
          <a href={assetsReportUrl(filter)} download><FileSpreadsheet className="size-4" /> В Excel</a>
        </Button>
        {admin && (
          <>
            <Button size="sm" variant="outline" hint="Добавить объекты из файла .xlsx (столбцы — ниже): при ошибке в любой строке не добавится ни один"
              onClick={() => picker.current?.click()}><Upload className="size-4" /> Из Excel</Button>
            <Button size="sm" variant="outline" hint="Скачать PDF (A4) с QR-метками всех объектов здания — для печати и наклейки"
              onClick={() => labelsSheet({ building_id: building }).catch((ex: Error) => setError(ex.message))}><QrCode className="size-4" /> Метки</Button>
            <input ref={picker} type="file" accept=".xlsx" className="hidden" data-testid="assets-file"
              onChange={e => {
                const file = e.target.files?.[0]
                if (file) {
                  importAssets(building, file).then(r => { setReport(r); load() },
                    (ex: Error) => setReport({ refused: ex.message, rows: ex instanceof ApiError ? ex.rows : [] }))
                }
                e.target.value = ''
              }} />
          </>
        )}
      </div>
      {admin && (
        <p className="mt-1 text-sm text-muted-foreground">
          Excel: столбцы Тип, Инвентарный номер, Серийный номер, Этаж, X, Y, Примечание. Этаж — номер или название, X и Y — точка на плане этажа в метрах; пустой номер — объект без учёта. Загружается всё или ничего.
        </p>
      )}
      {report && (
        <div className="mt-3 rounded-lg border bg-card p-3 text-sm" data-testid="assets-report">
          {'created' in report ? `Добавлено объектов: ${report.created}` : (
            <>
              <p className="text-destructive">Файл не загружен: {report.refused}</p>
              {report.rows.length > 0 && <ul className="mt-1 text-destructive">{report.rows.map(r => <li key={r}>{r}</li>)}</ul>}
            </>
          )}
        </div>
      )}
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {items.length === 0 ? (
        <p className="mt-6 text-sm text-muted-foreground">
          {q || state || attention || accounted ? 'Ничего не найдено.' : 'Объектов пока нет. Их ставит на план администратор здания — в разделе «План».'}
        </p>
      ) : (
        <ul className="mt-4 divide-y rounded-lg border bg-card text-sm" data-testid="assets">
          {items.map(a => (
            <li key={a.id}>
              <a href={to.assets(building, a.id)} aria-current={a.id === selected ? 'true' : undefined} data-asset={a.inventory_no ?? a.id}
                className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-secondary', a.id === selected && 'bg-accent')}>
                <span className="min-w-40 flex-1"><span className="font-medium">{a.type_name}</span>
                  {a.product_name && <span className="ml-2 text-muted-foreground">{a.product_name}</span>}
                  <span className={cn('ml-2 text-muted-foreground', !a.inventory_no && 'italic')}>{numberOf(a)}</span></span>
                <span className="text-muted-foreground max-sm:hidden">{room(a)}</span>
                {a.needs_placement && <NeedsMark need="placement"><Badge variant="warning">разместить</Badge></NeedsMark>}
                {a.needs_fill && <NeedsMark need="fill"><Badge variant="warning">заполнить</Badge></NeedsMark>}
                <StateBadge a={a} />
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
