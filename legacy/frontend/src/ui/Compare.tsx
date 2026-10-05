import { ArrowRight, Eye } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { compareLayers, type CompareObject, type Layer, type LayerComparison } from '../api'

const CHANGE: Record<CompareObject['change'], string> = { added: 'добавлен', removed: 'убран', moved: 'перемещён', changed: 'изменён' }
const BADGE = { added: 'success', removed: 'destructive', moved: 'warning', changed: 'accent' } as const
const money = (v: number | null | undefined, cur: string | null | undefined) =>
  v == null ? '—' : `${v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${cur && cur !== 'RUB' ? ` ${cur}` : ' ₽'}`
const signed = (n: number) => (n > 0 ? `+${n}` : String(n))
const tone = (n: number) => (n > 0 ? 'text-success' : n < 0 ? 'text-destructive' : '')

const TH = 'sticky top-0 z-[1] border-b border-border bg-popover px-2 py-1.5 text-left text-xs font-medium text-muted-foreground'
const TD = 'border-b border-border px-2 py-1.5 align-top'
const NUM = 'text-right tabular-nums whitespace-nowrap'
const FOOT = 'border-t-2 border-border px-2 py-1.5 align-top'

/** Two variants side by side: what was added, removed, moved or changed, and the specification of both. */
export default function Compare({ projectId, layers, a: a0, b: b0, onClose, onShow }: {
  projectId: string; layers: Layer[]; a: string; b: string; onClose: () => void
  /** show an object in the viewer (when on screen) */
  onShow?: (o: CompareObject) => void
}) {
  const [a, setA] = useState(a0)
  const [b, setB] = useState(b0)
  const [data, setData] = useState<{ key: string; cmp?: LayerComparison; err?: string } | null>(null)
  const [filter, setFilter] = useState<CompareObject['change'] | 'all'>('all')
  const key = `${a}|${b}`
  useEffect(() => {
    let alive = true
    compareLayers(projectId, a, b).then((cmp) => { if (alive) setData({ key, cmp }) })
      .catch((e) => { if (alive) setData({ key, err: (e as Error).message }) })
    return () => { alive = false }
  }, [projectId, a, b, key])
  const cmp = data?.key === key ? data.cmp : null
  const kind = layers.find((l) => l.id === a)?.kind
  const same = layers.filter((l) => l.kind === kind)
  const objs = useMemo(() => (cmp?.objects ?? []).filter((o) => filter === 'all' || o.change === filter), [cmp, filter])
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-5xl gap-3" onKeyDown={(e) => e.stopPropagation()} aria-describedby={undefined}>
        <DialogHeader className="flex flex-wrap items-center gap-2 pr-8">
          <DialogTitle className="mr-auto">Сравнение вариантов</DialogTitle>
          <div className="flex items-center gap-1.5">
            <Select className="max-w-56" value={a} onChange={(e) => setA(e.target.value)} aria-label="Вариант A">
              {same.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </Select>
            <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
            <Select className="max-w-56" value={b} onChange={(e) => setB(e.target.value)} aria-label="Вариант B">
              {same.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </Select>
          </div>
        </DialogHeader>
        <div className="grid max-h-[75vh] content-start gap-3 overflow-auto text-sm">
          {data?.err && <p className="m-0 text-destructive">{data.err}</p>}
          {!cmp && !data?.err && <p className="m-0 text-muted-foreground">Загрузка…</p>}
          {cmp && (
            <>
              <div className="flex flex-wrap items-center gap-1.5">
                {(['added', 'removed', 'moved', 'changed'] as const).map((k) => (
                  <Button key={k} variant="outline" size="sm" aria-pressed={filter === k}
                    className={cn('rounded-full', filter === k && 'border-primary bg-accent text-accent-foreground hover:bg-accent')}
                    onClick={() => setFilter(filter === k ? 'all' : k)}>
                    {CHANGE[k]}: <b className="tabular-nums">{cmp.counts[k]}</b>
                  </Button>
                ))}
                <span className="text-xs text-muted-foreground">без изменений: {cmp.counts.same}</span>
              </div>
              {cmp.items.length > 0 && (
                <div className="max-h-[34vh] overflow-auto">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr>
                        <th className={TH}>Наименование</th><th className={cn(TH, 'text-right')}>{cmp.a.name}</th><th className={cn(TH, 'text-right')}>{cmp.b.name}</th>
                        <th className={cn(TH, 'text-right')}>Δ</th><th className={cn(TH, 'text-right')}>Сумма, Δ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cmp.items.map((r) => (
                        <tr key={r.item} className={r.delta ? '' : 'text-muted-foreground'}>
                          <td className={TD}><b className="font-medium">{r.name}</b>{r.category && <div className="text-xs text-muted-foreground">{r.category}</div>}</td>
                          <td className={cn(TD, NUM)}>{r.qty_a}</td><td className={cn(TD, NUM)}>{r.qty_b}</td>
                          <td className={cn(TD, NUM, tone(r.delta))}>{r.delta ? signed(r.delta) : ''}</td>
                          <td className={cn(TD, NUM)}>{r.sum_a != null && r.delta ? money((r.sum_b ?? 0) - r.sum_a, r.currency) : ''}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      {Object.entries(cmp.totals).map(([cur, t]) => (
                        <tr key={cur}>
                          <td className={cn(FOOT, 'font-semibold')}>Итого{cur !== 'RUB' ? `, ${cur}` : ''}</td>
                          <td className={cn(FOOT, NUM)}>{money(t.a, cur)}</td><td className={cn(FOOT, NUM)}>{money(t.b, cur)}</td>
                          <td className={FOOT} />
                          <td className={cn(FOOT, NUM, 'font-semibold', tone(t.delta))}>{t.delta > 0 ? '+' : ''}{money(t.delta, cur)}</td>
                        </tr>
                      ))}
                    </tfoot>
                  </table>
                </div>
              )}
              <h3 className="m-0 flex items-center gap-2 text-sm font-semibold">
                Изменения объектов
                {filter !== 'all' && <Button variant="link" size="sm" className="h-auto px-0" onClick={() => setFilter('all')}>показать все</Button>}
              </h3>
              {!objs.length && <p className="m-0 text-muted-foreground">Варианты совпадают.</p>}
              <ul className="m-0 grid list-none gap-0.5 p-0">
                {objs.map((o) => (
                  <li key={o.key} className="flex items-center gap-3 rounded-md px-1 py-1.5 hover:bg-secondary/60">
                    <Badge variant={BADGE[o.change]} className="w-20 justify-center">{CHANGE[o.change]}</Badge>
                    <div className="min-w-0 flex-1">
                      <b className="font-medium">{o.name}</b>
                      <div className="text-xs text-muted-foreground">
                        {[o.drawing, o.floor_name, o.room].filter(Boolean).join(' · ')}{o.what.length ? ` — ${o.what.join(', ')}` : ''}
                      </div>
                    </div>
                    {onShow && <Button variant="outline" size="sm" onClick={() => onShow(o)}><Eye /> Показать</Button>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
