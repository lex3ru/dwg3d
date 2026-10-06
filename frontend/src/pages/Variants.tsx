import { GitBranch, Play, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  applyVariant, compareWithFact, createVariant, deleteVariant, getVariant, listVariants, numberAdded,
  type Comparison, type Variant,
} from '../api'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { cn } from '../lib/utils'
import { showingVariant } from '../scene/systems'
import { to } from '../shell/route'
import { useEvents } from '../stream'

const select = 'h-8 rounded-md border bg-card px-2 text-sm'
const OP: Record<string, string> = { add: 'поставить', move: 'переместить', change: 'изменить', remove: 'убрать' }
const CHANGE: Record<string, string> = { added: 'добавлен', removed: 'убран', moved: 'перемещён', changed: 'изменён' }
const money = (v: number | undefined | null, cur = 'RUB') =>
  v == null ? '—' : `${v.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ${cur === 'RUB' ? '₽' : cur}`
const signed = (n: number) => (n > 0 ? `+${n}` : String(n))

/** Variants of placing objects: made here or in the editor, compared with the fact, priced, applied. */
export function Variants({ building, selected, editor }: { building: string; selected?: string; editor: string | null }) {
  const [items, setItems] = useState<Variant[]>([])
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [base, setBase] = useState('')
  const load = useCallback(() => { listVariants(building).then(v => { setItems(v); setError(null) }, (e: Error) => setError(e.message)) }, [building])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('planning.') || event.type.startsWith('assets.')) load() })
  const make = (e: React.FormEvent) => {
    e.preventDefault()
    createVariant(building, name.trim(), base || null).then(v => { setName(''); load(); location.hash = to.variants(building, v.id) },
      (ex: Error) => setError(ex.message))
  }
  return (
    <section>
      <h1 className="text-xl font-semibold">Варианты расстановки</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
        Вариант — предполагаемые перестановки, новые и убранные объекты; пока он не применён, учёт прежний. Правится в редакторе:
        слой «Объекты учёта» показывает факт или выбранный вариант.
      </p>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      <form onSubmit={make} className="mt-4 flex flex-wrap items-end gap-2 rounded-lg border bg-card p-3" data-testid="variant-form">
        <label className="grid gap-1 text-xs text-muted-foreground">Название
          <Input className="h-8 w-56" value={name} onChange={e => setName(e.target.value)} aria-label="Название варианта" />
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">От чего
          <select className={select} value={base} onChange={e => setBase(e.target.value)} aria-label="Основа варианта">
            <option value="">от факта</option>
            {items.filter(v => v.status === 'draft').map(v => <option key={v.id} value={v.id}>копия «{v.name}»</option>)}
          </select>
        </label>
        <Button type="submit" size="sm" disabled={!name.trim()}><GitBranch className="size-4" /> Создать вариант</Button>
      </form>
      {items.length === 0 ? <p className="mt-6 text-sm text-muted-foreground">Вариантов пока нет.</p> : (
        <ul className="mt-4 divide-y rounded-lg border bg-card text-sm" data-testid="variants">
          {items.map(v => (
            <li key={v.id}>
              <a href={to.variants(building, v.id)} data-variant={v.name} aria-current={v.id === selected ? 'true' : undefined}
                className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-secondary', v.id === selected && 'bg-accent')}>
                <span className="min-w-40 flex-1 font-medium">{v.name}</span>
                <span className="text-muted-foreground">
                  {Object.entries(v.counts).filter(([, n]) => n).map(([k, n]) => `${OP[k]}: ${n}`).join(' · ') || 'без изменений'}
                </span>
                {v.status === 'applied' && <Badge variant="success">применён</Badge>}
                {v.stale && v.status === 'draft' && <Badge variant="warning">устарел</Badge>}
              </a>
            </li>
          ))}
        </ul>
      )}
      {selected && <VariantCard key={selected} id={selected} building={building} editor={editor} onChanged={load} />}
    </section>
  )
}

function VariantCard({ id, building, editor, onChanged }: { id: string; building: string; editor: string | null; onChanged: () => void }) {
  const [v, setV] = useState<Variant | null>(null)
  const [cmp, setCmp] = useState<Comparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => {
    Promise.all([getVariant(id), compareWithFact(building, id)]).then(([x, c]) => { setV(x); setCmp(c); setError(null) },
      (e: Error) => setError(e.message))
  }, [id, building])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('assets.') || event.type.startsWith('planning.')) load() })
  if (!v || !cmp) return <p className="mt-4 text-sm text-muted-foreground">{error ?? 'Загрузка…'}</p>
  const open = () => {
    // the editor remembers which variant of the layer it shows: this one, being edited
    try {
      const key = `dwg3d.layers.${building}`
      const saved = JSON.parse(localStorage.getItem(key) ?? '{}')
      localStorage.setItem(key, JSON.stringify({ ...saved, active: `variant:${v.id}`, variants: { ...saved.variants, ...showingVariant(v.id) } }))
    } catch { /* private mode: the editor opens on the fact */ }
    if (editor) location.hash = to.editor(editor)
  }
  const apply = () => {
    if (!confirm(`Применить «${v.name}»? Операции выполнятся в учёте от вашего имени, с записями в истории объектов.`)) return
    setBusy(true)
    applyVariant(v.id).then(() => { load(); onChanged() }, (e: Error) => setError(e.message)).finally(() => setBusy(false))
  }
  const unnumbered = (v.ops ?? []).filter(o => o.op === 'add' && !o.data.inventory_no)
  const conflicts = (v.ops ?? []).filter(o => o.conflict)
  return (
    <div className="mt-5 grid gap-4 rounded-lg border bg-card p-4 text-sm" data-testid="variant-card">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="flex-1 text-base font-semibold">{v.name}</h2>
        {v.status === 'draft' && editor && <Button size="sm" variant="outline" onClick={open}>Открыть в редакторе</Button>}
        {v.status === 'draft' && <Button size="sm" disabled={busy || !(v.ops ?? []).length} onClick={apply}><Play className="size-4" /> Применить</Button>}
        <Button size="sm" variant="ghost" title="Удалить вариант" onClick={() => {
          if (confirm(`Удалить вариант «${v.name}»?`)) deleteVariant(v.id).then(() => { onChanged(); location.hash = to.variants(building) }, (e: Error) => setError(e.message))
        }}><Trash2 className="size-4" /></Button>
      </div>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {v.stale && v.status === 'draft' && (
        <div role="status" className="rounded-md bg-warning/15 px-2.5 py-1.5 text-warning" data-testid="stale">
          Вариант устарел: учёт изменился после него ({[...new Set(v.stale_reasons.map(r => r.what))].join(', ')}).
          {conflicts.length > 0 && ` Не выполнятся операций: ${conflicts.length} — их объекты изменены; поправьте их в редакторе заново.`}
        </div>
      )}
      {v.last_result && (
        <div className="rounded-md border px-2.5 py-1.5" data-testid="apply-result">
          Применение {new Date(v.last_result.at).toLocaleString('ru')}: выполнено {v.last_result.applied.length}, отклонено {v.last_result.refused.length}
          {v.last_result.refused.length > 0 && (
            <ul className="mt-1 text-destructive">
              {v.last_result.refused.map(r => <li key={r.op_id}>{OP[r.op]}: {r.reason}</li>)}
            </ul>
          )}
        </div>
      )}
      {unnumbered.length > 0 && v.status === 'draft' && (
        <div data-testid="numbers">
          <h3 className="font-medium">Инвентарные номера новых объектов</h3>
          <p className="text-muted-foreground">Без номера объект не будет поставлен при применении.</p>
          <ul className="mt-1 grid gap-1">
            {unnumbered.map(o => <Numbering key={o.id} variant={v.id} op={o.id} onDone={load}
              name={cmp.objects.find(x => x.op_id === o.id)?.name ?? 'новый объект'} />)}
          </ul>
        </div>
      )}
      <div>
        <h3 className="font-medium">Отличия от факта</h3>
        <p className="text-muted-foreground" data-testid="counts">
          добавлено {cmp.counts.added} · убрано {cmp.counts.removed} · перемещено {cmp.counts.moved} · изменено {cmp.counts.changed}
        </p>
        <ul className="mt-1 grid gap-0.5" data-testid="changes">
          {cmp.objects.map(o => (
            <li key={o.key}><Badge variant={o.change === 'added' ? 'success' : o.change === 'removed' ? 'destructive' : 'warning'}>{CHANGE[o.change]}</Badge>
              {' '}{o.name}{o.inventory_no ? ` · ${o.inventory_no}` : ''}{o.what.length ? ` (${o.what.join(', ')})` : ''}</li>
          ))}
        </ul>
      </div>
      <div className="overflow-x-auto">
        <h3 className="font-medium">Спецификация</h3>
        <table className="mt-1 w-full text-sm" data-testid="spec">
          <thead><tr className="text-left text-xs text-muted-foreground">
            <th className="py-1">Тип</th><th className="text-right">Факт</th><th className="text-right">Вариант</th><th className="text-right">Разница</th>
            <th className="text-right">Цена</th><th className="text-right">Сумма варианта</th></tr></thead>
          <tbody>
            {cmp.items.map(i => (
              <tr key={i.type_id} className="border-t" data-type={i.name}>
                <td className="py-1">{i.name}</td><td className="text-right tabular-nums">{i.qty_a}</td><td className="text-right tabular-nums">{i.qty_b}</td>
                <td className="text-right tabular-nums">{signed(i.delta)}</td><td className="text-right tabular-nums">{money(i.price, i.currency)}</td>
                <td className="text-right tabular-nums">{money(i.sum_b, i.currency)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            {Object.entries(cmp.totals).map(([cur, t]) => (
              <tr key={cur} className="border-t font-medium" data-testid="total">
                <td className="py-1" colSpan={5}>Итого: факт {money(t.a, cur)}, разница {t.delta > 0 ? '+' : ''}{money(t.delta, cur)}</td>
                <td className="text-right tabular-nums">{money(t.b, cur)}</td>
              </tr>
            ))}
          </tfoot>
        </table>
      </div>
    </div>
  )
}

function Numbering({ variant, op, name, onDone }: { variant: string; op: string; name: string; onDone: () => void }) {
  const [n, setN] = useState('')
  return (
    <li className="flex flex-wrap items-center gap-2">
      <span className="min-w-40">{name}</span>
      <Input className="h-8 w-40" value={n} onChange={e => setN(e.target.value)} aria-label={`Номер: ${name}`} placeholder="инвентарный номер" />
      <Button size="sm" variant="outline" disabled={!n.trim()} onClick={() => { void numberAdded(variant, op, n.trim()).then(onDone) }}>Задать</Button>
    </li>
  )
}
