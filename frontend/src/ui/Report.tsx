import { useEffect, useState } from 'react'
import { equipmentReport, equipmentReportXlsx, type EquipmentReport } from '../api'

const money = (v: number | null, cur: string | null) =>
  v === null ? '—' : `${v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${cur && cur !== 'RUB' ? ` ${cur}` : ' ₽'}`

/** Equipment specification: this building by floor, or all buildings side by side; Excel download. */
export default function Report({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [scope, setScope] = useState<'project' | 'all'>('project')
  const pid = scope === 'project' ? projectId : null
  // the answer for the scope it was asked for: a stale one is not shown while the next loads
  const [data, setData] = useState<{ pid: string | null; rep?: EquipmentReport; err?: string } | null>(null)
  useEffect(() => {
    let alive = true
    equipmentReport(pid).then((rep) => { if (alive) setData({ pid, rep }) })
      .catch((e) => { if (alive) setData({ pid, err: (e as Error).message }) })
    return () => { alive = false }
  }, [pid])
  const rep = data?.pid === pid ? data.rep ?? null : null
  const err = data?.pid === pid ? data.err ?? null : null

  const colName = (c: string) => rep?.projects?.find((p) => p.id === c)?.name ?? c
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal report-modal" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Спецификация оборудования">
        <header>
          <h2>Спецификация оборудования</h2>
          <div className="seg-toggle" role="group">
            <button className={scope === 'project' ? 'on' : ''} onClick={() => setScope('project')}>Это здание</button>
            <button className={scope === 'all' ? 'on' : ''} onClick={() => setScope('all')}>Все проекты</button>
          </div>
          <button className="ghost" onClick={onClose} aria-label="Закрыть">✕</button>
        </header>
        <div className="modal-body">
          {err && <p className="error">{err}</p>}
          {!rep && !err && <p className="hint">Загрузка…</p>}
          {rep && !rep.rows.length && <p className="hint">Оборудование ещё не расставлено.</p>}
          {rep && rep.rows.length > 0 && (
            <div className="report-scroll">
              <table className="report">
                <thead>
                  <tr>
                    <th>№</th><th>Наименование</th><th>Артикул</th><th>Поставщик</th>
                    {rep.columns.map((c) => <th key={c} className="r">{colName(c)}</th>)}
                    <th className="r">Кол-во</th><th className="r">Цена</th><th className="r">Сумма</th>
                  </tr>
                </thead>
                <tbody>
                  {rep.rows.map((r, i) => (
                    <tr key={r.item}>
                      <td>{i + 1}</td>
                      <td><b>{r.name}</b><small>{r.category}</small></td>
                      <td>{r.article}</td>
                      <td>{r.supplier}</td>
                      {rep.columns.map((c) => <td key={c} className="r">{r.by[c] ?? ''}</td>)}
                      <td className="r"><b>{r.qty}</b></td>
                      <td className="r">{money(r.price, r.currency)}</td>
                      <td className="r">{money(r.sum, r.currency)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td /><td><b>Итого</b></td><td /><td />
                    {rep.columns.map((c) => <td key={c} className="r">{rep.rows.reduce((n, r) => n + (r.by[c] ?? 0), 0)}</td>)}
                    <td className="r"><b>{rep.qty}</b></td><td />
                    <td className="r"><b>{Object.entries(rep.totals).map(([cur, v]) => money(v, cur)).join(' + ') || '—'}</b></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          {rep && rep.unpriced > 0 && <p className="hint">Без цены: {rep.unpriced} поз. — не вошли в сумму. Цены задаются в каталоге оборудования.</p>}
        </div>
        <footer>
          <a className={`button primary${rep?.rows.length ? '' : ' disabled'}`} href={equipmentReportXlsx(pid)} download>Скачать XLSX</a>
        </footer>
      </div>
    </div>
  )
}
