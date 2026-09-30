import { useEffect, useState } from 'react'
import {
  equipmentReport, equipmentReportXlsx, listLayers, roomReport, type EquipmentReport, type Layer, type RoomReport,
} from '../api'
import { me } from '../session'

const money = (v: number | null, cur: string | null) =>
  v === null ? '—' : `${v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${cur && cur !== 'RUB' ? ` ${cur}` : ' ₽'}`

type Scope = 'project' | 'rooms' | 'all'

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

  const colName = (c: string) => rep?.projects?.find((p) => p.id === c)?.name ?? c
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal report-modal" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Спецификация оборудования">
        <header>
          <h2>Спецификация оборудования</h2>
          {scope !== 'all' && layers.length > 1 && (
            <select className="report-layer" value={layer} onChange={(e) => setLayer(e.target.value)} aria-label="Слой">
              <option value="">Все слои</option>
              {layers.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          )}
          <div className="seg-toggle" role="group">
            <button className={scope === 'project' ? 'on' : ''} onClick={() => setScope('project')}>По этажам</button>
            <button className={scope === 'rooms' ? 'on' : ''} onClick={() => setScope('rooms')}>По помещениям</button>
            {!me?.guest && <button className={scope === 'all' ? 'on' : ''} onClick={() => setScope('all')}>Все проекты</button>}
          </div>
          <button className="ghost" onClick={onClose} aria-label="Закрыть">✕</button>
        </header>
        <div className="modal-body">
          {err && <p className="error">{err}</p>}
          {!cur && <p className="hint">Загрузка…</p>}
          {empty && <p className="hint">Оборудование ещё не расставлено.</p>}
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
                    <td className="r"><b>{Object.entries(rep.totals).map(([c, v]) => money(v, c)).join(' + ') || '—'}</b></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          {rooms && rooms.rooms.length > 0 && (
            <div className="report-scroll">
              <table className="report">
                <thead>
                  <tr><th>Наименование</th><th>Артикул</th><th className="r">Кол-во</th><th className="r">Цена</th><th className="r">Сумма</th></tr>
                </thead>
                {rooms.rooms.map((g, gi) => (
                  <tbody key={gi}>
                    <tr className="group">
                      <td colSpan={5}>
                        <b>{g.room}</b>{g.area ? <span className="hint"> · {g.area.toFixed(1)} м²</span> : null}
                        <small>{[rooms.many_drawings ? g.drawing : '', g.floor].filter(Boolean).join(' · ')}</small>
                      </td>
                    </tr>
                    {g.items.map((r) => (
                      <tr key={r.item}>
                        <td><b>{r.name}</b><small>{r.category}</small></td>
                        <td>{r.article}</td>
                        <td className="r">{r.qty}</td>
                        <td className="r">{money(r.price, r.currency)}</td>
                        <td className="r">{money(r.sum, r.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                ))}
                <tfoot>
                  <tr>
                    <td><b>Итого по проекту</b></td><td />
                    <td className="r"><b>{rooms.qty}</b></td><td />
                    <td className="r"><b>{Object.entries(rooms.totals).map(([c, v]) => money(v, c)).join(' + ') || '—'}</b></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          {rep && rep.unpriced > 0 && <p className="hint">Без цены: {rep.unpriced} поз. — не вошли в сумму. Цены задаются в каталоге оборудования.</p>}
        </div>
        <footer>
          <a className={`button primary${empty || !cur ? ' disabled' : ''}`} href={xlsx} download>Скачать XLSX</a>
        </footer>
      </div>
    </div>
  )
}
