import { useEffect, useMemo, useState } from 'react'
import { compareLayers, type CompareObject, type Layer, type LayerComparison } from '../api'

const CHANGE: Record<CompareObject['change'], string> = { added: 'добавлен', removed: 'убран', moved: 'перемещён', changed: 'изменён' }
const money = (v: number | null | undefined, cur: string | null | undefined) =>
  v == null ? '—' : `${v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${cur && cur !== 'RUB' ? ` ${cur}` : ' ₽'}`
const signed = (n: number) => (n > 0 ? `+${n}` : String(n))

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
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal report-modal" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Сравнение вариантов">
        <header>
          <h2>Сравнение вариантов</h2>
          <span className="inline cmp-pick">
            <select value={a} onChange={(e) => setA(e.target.value)}>{same.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
            →
            <select value={b} onChange={(e) => setB(e.target.value)}>{same.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
          </span>
          <button className="ghost" onClick={onClose} aria-label="Закрыть">✕</button>
        </header>
        <div className="modal-body">
          {data?.err && <p className="error">{data.err}</p>}
          {!cmp && !data?.err && <p className="hint">Загрузка…</p>}
          {cmp && (
            <>
              <div className="cmp-counts">
                {(['added', 'removed', 'moved', 'changed'] as const).map((k) => (
                  <button key={k} className={`cmp-chip ${k}${filter === k ? ' on' : ''}`} onClick={() => setFilter(filter === k ? 'all' : k)}>
                    {CHANGE[k]}: <b>{cmp.counts[k]}</b>
                  </button>
                ))}
                <span className="hint">без изменений: {cmp.counts.same}</span>
              </div>
              {cmp.items.length > 0 && (
                <div className="report-scroll short">
                  <table className="report">
                    <thead><tr><th>Наименование</th><th className="r">{cmp.a.name}</th><th className="r">{cmp.b.name}</th><th className="r">Δ</th><th className="r">Сумма, Δ</th></tr></thead>
                    <tbody>
                      {cmp.items.map((r) => (
                        <tr key={r.item} className={r.delta ? '' : 'muted'}>
                          <td><b>{r.name}</b><small>{r.category}</small></td>
                          <td className="r">{r.qty_a}</td><td className="r">{r.qty_b}</td>
                          <td className={`r ${r.delta > 0 ? 'plus' : r.delta < 0 ? 'minus' : ''}`}>{r.delta ? signed(r.delta) : ''}</td>
                          <td className="r">{r.sum_a != null && r.delta ? money((r.sum_b ?? 0) - r.sum_a, r.currency) : ''}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      {Object.entries(cmp.totals).map(([cur, t]) => (
                        <tr key={cur}><td><b>Итого{cur !== 'RUB' ? `, ${cur}` : ''}</b></td><td className="r">{money(t.a, cur)}</td><td className="r">{money(t.b, cur)}</td>
                          <td /><td className={`r ${t.delta > 0 ? 'plus' : t.delta < 0 ? 'minus' : ''}`}><b>{t.delta > 0 ? '+' : ''}{money(t.delta, cur)}</b></td></tr>
                      ))}
                    </tfoot>
                  </table>
                </div>
              )}
              <h3>Изменения объектов {filter !== 'all' && <button className="link" onClick={() => setFilter('all')}>показать все</button>}</h3>
              {!objs.length && <p className="hint">Варианты совпадают.</p>}
              <ul className="rows cmp-list">
                {objs.map((o) => (
                  <li key={o.key} className="row">
                    <span className={`badge cmp-${o.change}`}>{CHANGE[o.change]}</span>
                    <div className="grow">
                      <b>{o.name}</b>
                      <small>{[o.drawing, o.floor_name, o.room].filter(Boolean).join(' · ')}{o.what.length ? ` — ${o.what.join(', ')}` : ''}</small>
                    </div>
                    {onShow && <button className="small" onClick={() => onShow(o)}>Показать</button>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
