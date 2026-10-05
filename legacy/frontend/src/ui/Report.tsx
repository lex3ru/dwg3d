import { Download } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import {
  equipmentReport, equipmentReportXlsx, listLayers, roomReport, type EquipmentReport, type Layer, type RoomReport,
} from '../api'
import { me } from '../session'

const money = (v: number | null, cur: string | null) =>
  v === null ? '—' : `${v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${cur && cur !== 'RUB' ? ` ${cur}` : ' ₽'}`

type Scope = 'project' | 'rooms' | 'all'

const TH = 'sticky top-0 z-[1] border-b border-border bg-popover px-2 py-1.5 text-left text-xs font-medium text-muted-foreground'
const TD = 'border-b border-border px-2 py-1.5 align-top'
const NUM = 'text-right tabular-nums whitespace-nowrap'
const FOOT = 'border-t-2 border-border px-2 py-1.5 align-top'

/** Name with the category underneath. */
const Named = ({ name, sub }: { name: string; sub?: string | null }) => (
  <><b className="font-medium">{name}</b>{sub && <div className="text-xs text-muted-foreground">{sub}</div>}</>
)

/** Equipment specification: this project by floor or room by room (all layers or one), or all projects side by side; Excel download. */
export default function Report({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [scope, setScope] = useState<Scope>('project')
  const [layer, setLayer] = useState<string>('')
  const [layers, setLayers] = useState<Layer[]>([])
  useEffect(() => { listLayers(projectId).then(setLayers).catch(() => {}) }, [projectId])
  const key = `${scope}|${layer}`
  // the answer for the scope it was asked for: a stale one is not shown while the next loads
  const [data, setData] = useState<{ key: string; rep?: EquipmentReport; rooms?: RoomReport; err?: string } | null>(null)
  useEffect(() => {
    let alive = true
    const lay = scope === 'all' ? null : layer || null
    const load = scope === 'rooms'
      ? roomReport(projectId, lay).then((rooms) => ({ key, rooms }))
      : equipmentReport(scope === 'project' ? projectId : null, lay).then((rep) => ({ key, rep }))
    load.then((d) => { if (alive) setData(d) }).catch((e) => { if (alive) setData({ key, err: (e as Error).message }) })
    return () => { alive = false }
  }, [key, scope, layer, projectId])
  const cur = data?.key === key ? data : null
  const rep = cur?.rep ?? null
  const rooms = cur?.rooms ?? null
  const err = cur?.err ?? null
  const empty = (rep && !rep.rows.length) || (rooms && !rooms.rooms.length)
  const xlsx = equipmentReportXlsx(scope === 'all' ? null : projectId, scope === 'rooms' ? 'room' : 'floor', scope === 'all' ? null : layer || null)
  const noDownload = !!empty || !cur

  const colName = (c: string) => rep?.projects?.find((p) => p.id === c)?.name ?? c
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-5xl gap-3" onKeyDown={(e) => e.stopPropagation()} aria-describedby={undefined}>
        <DialogHeader className="flex flex-wrap items-center gap-2 pr-8">
          <DialogTitle className="mr-auto">Спецификация оборудования</DialogTitle>
          {scope !== 'all' && layers.length > 1 && (
            <Select className="max-w-56" value={layer} onChange={(e) => setLayer(e.target.value)} aria-label="Слой">
              <option value="">Все слои</option>
              {layers.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </Select>
          )}
          <Tabs value={scope} onValueChange={(v) => setScope(v as Scope)}>
            <TabsList>
              <TabsTrigger value="project">По этажам</TabsTrigger>
              <TabsTrigger value="rooms">По помещениям</TabsTrigger>
              {!me?.guest && <TabsTrigger value="all">Все проекты</TabsTrigger>}
            </TabsList>
          </Tabs>
        </DialogHeader>
        <div className="grid max-h-[75vh] gap-2 overflow-auto text-sm">
          {err && <p className="m-0 text-destructive">{err}</p>}
          {!cur && <p className="m-0 text-muted-foreground">Загрузка…</p>}
          {empty && <p className="m-0 text-muted-foreground">Оборудование ещё не расставлено.</p>}
          {rep && rep.rows.length > 0 && (
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <th className={TH}>№</th><th className={TH}>Наименование</th><th className={TH}>Артикул</th><th className={TH}>Поставщик</th>
                  {rep.columns.map((c) => <th key={c} className={cn(TH, 'text-right')}>{colName(c)}</th>)}
                  <th className={cn(TH, 'text-right')}>Кол-во</th><th className={cn(TH, 'text-right')}>Цена</th><th className={cn(TH, 'text-right')}>Сумма</th>
                </tr>
              </thead>
              <tbody>
                {rep.rows.map((r, i) => (
                  <tr key={r.item}>
                    <td className={cn(TD, 'tabular-nums text-muted-foreground')}>{i + 1}</td>
                    <td className={TD}><Named name={r.name} sub={r.category} /></td>
                    <td className={TD}>{r.article}</td>
                    <td className={TD}>{r.supplier}</td>
                    {rep.columns.map((c) => <td key={c} className={cn(TD, NUM)}>{r.by[c] ?? ''}</td>)}
                    <td className={cn(TD, NUM, 'font-semibold')}>{r.qty}</td>
                    <td className={cn(TD, NUM)}>{money(r.price, r.currency)}</td>
                    <td className={cn(TD, NUM)}>{money(r.sum, r.currency)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td className={FOOT} /><td className={cn(FOOT, 'font-semibold')}>Итого</td><td className={FOOT} /><td className={FOOT} />
                  {rep.columns.map((c) => <td key={c} className={cn(FOOT, NUM)}>{rep.rows.reduce((n, r) => n + (r.by[c] ?? 0), 0)}</td>)}
                  <td className={cn(FOOT, NUM, 'font-semibold')}>{rep.qty}</td><td className={FOOT} />
                  <td className={cn(FOOT, NUM, 'font-semibold')}>{Object.entries(rep.totals).map(([c, v]) => money(v, c)).join(' + ') || '—'}</td>
                </tr>
              </tfoot>
            </table>
          )}
          {rooms && rooms.rooms.length > 0 && (
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <th className={TH}>Наименование</th><th className={TH}>Артикул</th>
                  <th className={cn(TH, 'text-right')}>Кол-во</th><th className={cn(TH, 'text-right')}>Цена</th><th className={cn(TH, 'text-right')}>Сумма</th>
                </tr>
              </thead>
              {rooms.rooms.map((g, gi) => (
                <tbody key={gi}>
                  <tr>
                    <td colSpan={5} className={cn(TD, 'bg-secondary pt-2.5')}>
                      <b className="font-semibold">{g.room}</b>
                      {g.area ? <span className="text-muted-foreground"> · {g.area.toFixed(1)} м²</span> : null}
                      <span className="ml-2 text-xs text-muted-foreground">{[rooms.many_drawings ? g.drawing : '', g.floor].filter(Boolean).join(' · ')}</span>
                    </td>
                  </tr>
                  {g.items.map((r) => (
                    <tr key={r.item}>
                      <td className={TD}><Named name={r.name} sub={r.category} /></td>
                      <td className={TD}>{r.article}</td>
                      <td className={cn(TD, NUM)}>{r.qty}</td>
                      <td className={cn(TD, NUM)}>{money(r.price, r.currency)}</td>
                      <td className={cn(TD, NUM)}>{money(r.sum, r.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              ))}
              <tfoot>
                <tr>
                  <td className={cn(FOOT, 'font-semibold')}>Итого по проекту</td><td className={FOOT} />
                  <td className={cn(FOOT, NUM, 'font-semibold')}>{rooms.qty}</td><td className={FOOT} />
                  <td className={cn(FOOT, NUM, 'font-semibold')}>{Object.entries(rooms.totals).map(([c, v]) => money(v, c)).join(' + ') || '—'}</td>
                </tr>
              </tfoot>
            </table>
          )}
          {rep && rep.unpriced > 0 && <p className="m-0 text-xs text-muted-foreground">Без цены: {rep.unpriced} поз. — не вошли в сумму. Цены задаются в каталоге оборудования.</p>}
        </div>
        <DialogFooter>
          <Button asChild className={cn(noDownload && 'pointer-events-none opacity-50')}>
            <a href={xlsx} download aria-disabled={noDownload || undefined} tabIndex={noDownload ? -1 : undefined}><Download /> Скачать XLSX</a>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
