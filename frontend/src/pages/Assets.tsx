import { FileSpreadsheet, QrCode, Search, Upload } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, assetsReportUrl, importAssets, labelsSheet, listAssets, STATES, type Asset, type AssetState, type TreeFloor } from '../api'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { cn } from '../lib/utils'
import { to } from '../shell/route'
import { useEvents } from '../stream'

const select = 'h-8 rounded-md border bg-card px-2 text-sm'

export function StateBadge({ a }: { a: Asset }) {
  return <Badge variant={a.state === 'in_use' ? 'default' : a.state === 'faulty' ? 'destructive' : 'warning'}>{STATES[a.state]}</Badge>
}

/** The objects of a building the user may see: by number, type, state; what needs attention. */
export function Assets({ building, floors, selected, admin, initialQuery }: {
  building: string; floors: TreeFloor[]; selected?: string
  /** the building's administrator loads objects from a file and prints labels */
  admin?: boolean
  initialQuery?: string
}) {
  const picker = useRef<HTMLInputElement>(null)
  const [report, setReport] = useState<{ created: number } | { refused: string; rows: string[] } | null>(null)
  const [items, setItems] = useState<Asset[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState(initialQuery ?? '')
  const [state, setState] = useState<AssetState | ''>('')
  const [attention, setAttention] = useState<'' | 'needs_fill' | 'needs_placement'>('')
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    listAssets({ building_id: building, q, state, [attention || 'x']: attention ? 'true' : undefined, limit: '300' })
      .then(r => { setItems(r.items); setTotal(r.total); setError(null) }, (e: Error) => setError(e.message))
  }, [building, q, state, attention])
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
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Номер или название" aria-label="Поиск объекта"
            className="h-8 w-full rounded-md border bg-card pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </div>
        <select className={select} value={state} onChange={e => setState(e.target.value as AssetState | '')} aria-label="Состояние">
          <option value="">любое состояние</option>
          {Object.entries(STATES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className={select} value={attention} onChange={e => setAttention(e.target.value as typeof attention)} aria-label="Требует внимания">
          <option value="">все</option>
          <option value="needs_fill">требует заполнения</option>
          <option value="needs_placement">требует размещения</option>
        </select>
        <span className="text-sm text-muted-foreground" data-testid="assets-total">{total}</span>
        <Button asChild size="sm" variant="outline" title="Список по текущему фильтру, свойства отдельными столбцами">
          <a href={assetsReportUrl({ building_id: building, q, state, [attention || 'x']: attention ? 'true' : undefined })} download><FileSpreadsheet className="size-4" /> В Excel</a>
        </Button>
        {admin && (
          <>
            <Button size="sm" variant="outline" onClick={() => picker.current?.click()}><Upload className="size-4" /> Из Excel</Button>
            <Button size="sm" variant="outline" title="Лист QR-меток всех объектов здания (PDF, A4)"
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
          Excel: столбцы Тип, Инвентарный номер, Серийный номер, Этаж, X, Y, Примечание. Этаж — номер или название, X и Y — точка на плане этажа в метрах. Загружается всё или ничего.
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
          {q || state || attention ? 'Ничего не найдено.' : 'Объектов пока нет. Их ставит на план администратор здания — в разделе «План».'}
        </p>
      ) : (
        <ul className="mt-4 divide-y rounded-lg border bg-card text-sm" data-testid="assets">
          {items.map(a => (
            <li key={a.id}>
              <a href={to.assets(building, a.id)} aria-current={a.id === selected ? 'true' : undefined} data-asset={a.inventory_no}
                className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-secondary', a.id === selected && 'bg-accent')}>
                <span className="min-w-40 flex-1"><span className="font-medium">{a.type_name}</span>
                  <span className="ml-2 text-muted-foreground">{a.inventory_no}</span></span>
                <span className="text-muted-foreground max-sm:hidden">{room(a)}</span>
                {a.needs_placement && <Badge variant="warning">разместить</Badge>}
                {a.needs_fill && <Badge variant="warning">заполнить</Badge>}
                <StateBadge a={a} />
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
