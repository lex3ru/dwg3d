import { useMemo, useState } from 'react'
import type { FloorMeta, PlacedItem } from '../api'
import { CATALOG, CATEGORIES, catalogError, catalogItem, type CatalogItem } from '../furniture/catalog'
import { ISSUE_LABEL, camParams, itemElev, itemSize, roomAt, type Issue, type PlanIndex, type RoomCover } from '../furniture/geom'
import { Icon } from './icons'

interface Props {
  floor: FloorMeta | null
  items: PlacedItem[]                   // on this floor
  plan: PlanIndex | null
  issues: Map<string, Issue[]>
  selected: string | null
  placing: CatalogItem | null
  showZones: boolean
  canUndo: boolean
  roomCover: RoomCover[]
  camViews: boolean
  onZones: (v: boolean) => void
  onCamViews: (v: boolean) => void
  onPick: (c: CatalogItem, drag: boolean) => void
  onSelect: (id: string | null) => void
  onUpdate: (id: string, patch: Partial<PlacedItem>) => void
  onRotate: (id: string, by: number) => void
  onDuplicate: (id: string) => void
  onRow: (id: string, count: number, gap: number) => void
  onDelete: (id: string) => void
  onUndo: () => void
  onClose: () => void
  /** the model is being rebuilt: changes are not accepted */
  locked: boolean
  unplaced: NonNullable<import('../api').ViewSettings['furniture_unplaced']>
  onUnplaced: (ids: string[], toFloor: string | null) => void
}

const pct = (v: number) => `${Math.round(v * 100)}%`
const catColor = (id: string) => CATEGORIES.find((c) => c.id === id)?.color ?? '#868e96'
const cm = (m: number) => Math.round(m * 100)

/** Top view of an item: its footprint with the front edge marked. */
function Symbol({ c }: { c: CatalogItem }) {
  const k = 30 / Math.max(c.w, c.d, 0.3)
  const w = Math.max(4, c.w * k), d = Math.max(4, c.d * k)
  const x = (36 - w) / 2, y = (36 - d) / 2
  const col = catColor(c.cat)
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" aria-hidden>
      {c.kind === 'zone' || ['plant', 'bin', 'stool', 'extinguisher', 'iv'].includes(c.kind)
        ? <ellipse cx="18" cy="18" rx={w / 2} ry={d / 2} fill={`${col}22`} stroke={col} strokeWidth="1.5" />
        : <rect x={x} y={y} width={w} height={d} rx="1.5" fill={`${col}22`} stroke={col} strokeWidth="1.5" />}
      <line x1={x + 1} x2={x + w - 1} y1={y + d} y2={y + d} stroke={col} strokeWidth="3" />
    </svg>
  )
}

function NumField({ label, value, onChange, min = 1, max = 5000 }: { label: string; value: number; onChange: (v: number) => void; min?: number; max?: number }) {
  const [text, setText] = useState<string | null>(null)
  const commit = () => {
    if (text == null) return
    const v = Number(text.replace(',', '.'))
    if (Number.isFinite(v) && v >= min && v <= max) onChange(v)
    setText(null)
  }
  return (
    <label className="fp-num">{label}
      <input inputMode="decimal" value={text ?? String(value)} onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') { commit(); (e.target as HTMLInputElement).blur() } else if (e.key === 'Escape') setText(null) }} />
    </label>
  )
}

/** Catalog of furniture and equipment, the selected item's card and the
 * list of items placed on the floor (with their issues). */
export default function FurniturePanel(p: Props) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState<string>('all')
  const [row, setRow] = useState<{ n: number; gap: number } | null>(null)
  const found = useMemo(() => {
    const s = q.trim().toLowerCase()
    return CATALOG.filter((c) => (cat === 'all' || c.cat === cat) &&
      (!s || `${c.name} ${c.tags ?? ''}`.toLowerCase().includes(s)))
  }, [q, cat])
  const sel = p.items.find((i) => i.id === p.selected) ?? null
  const withIssues = p.items.filter((i) => p.issues.get(i.id)?.length)
  const byRoom = useMemo(() => {
    const m = new Map<string, PlacedItem[]>()
    for (const it of p.items) {
      const r = (p.plan && roomAt(p.plan, it.at)) || 'Вне помещений'
      m.set(r, [...(m.get(r) ?? []), it])
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], 'ru'))
  }, [p.items, p.plan])

  if (!p.floor) {
    return (
      <aside className="furniture-panel menu-root">
        <header><b>Мебель и оборудование</b>
          <button className="icon" onClick={p.onClose} aria-label="Закрыть"><Icon name="close" size={16} /></button></header>
        <p className="hint">Выберите этаж на лестнице слева.</p>
      </aside>
    )
  }

  const selCard = sel && (() => {
    const c = catalogItem(sel.item)
    const [w, d, h] = itemSize(sel, c)
    const iss = p.issues.get(sel.id) ?? []
    const setSize = (k: 0 | 1 | 2, v: number) => {
      const s: [number, number, number] = [w, d, h]
      s[k] = v / 100
      p.onUpdate(sel.id, { size: s })
    }
    return (
      <section className="fp-card">
        <div className="fp-card-head">
          <Symbol c={c} />
          <div><b>{c.name}</b><small>{(p.plan && roomAt(p.plan, sel.at)) || 'вне помещений'}</small></div>
          <button className="icon" onClick={() => p.onSelect(null)} aria-label="Снять выделение"><Icon name="close" size={14} /></button>
        </div>
        <div className="fp-row">
          <NumField label="Ш, см" value={cm(w)} onChange={(v) => setSize(0, v)} />
          <NumField label="Г, см" value={cm(d)} onChange={(v) => setSize(1, v)} />
          <NumField label="В, см" value={cm(h)} onChange={(v) => setSize(2, v)} />
        </div>
        {(c.elev != null || sel.elev != null) && (
          <div className="fp-row">
            <NumField label="Высота установки, см" value={cm(itemElev(sel, c))} min={0} max={2000}
              onChange={(v) => p.onUpdate(sel.id, { elev: v / 100 })} />
          </div>
        )}
        {c.cam && (() => {
          const cp = camParams(sel, c)!
          return (
            <div className="fp-row">
              <NumField label="Угол обзора, °" value={Math.round(cp.fov)} min={1} max={360} onChange={(v) => p.onUpdate(sel.id, { fov: v })} />
              <NumField label="Дальность, м" value={Math.round(cp.range * 10) / 10} min={0.5} max={300} onChange={(v) => p.onUpdate(sel.id, { range: v })} />
              <small className="fp-cam-note">распознавание лиц до {cp.ident.toFixed(1)} м</small>
            </div>
          )
        })()}
        {sel.size && <button className="link small" onClick={() => p.onUpdate(sel.id, { size: undefined })}>Размер по каталогу ({cm(c.w)}×{cm(c.d)}×{cm(c.h)})</button>}
        <div className="fp-row">
          <NumField label="Поворот, °" value={Math.round(sel.angle)} min={-360} max={360} onChange={(v) => p.onUpdate(sel.id, { angle: ((v % 360) + 360) % 360 })} />
          <div className="fp-rot">
            <button onClick={() => p.onRotate(sel.id, 90)} title="Повернуть на 90° против часовой (R)">⟲ 90°</button>
            <button onClick={() => p.onRotate(sel.id, -90)} title="Повернуть на 90° по часовой (Shift+R)">⟳ 90°</button>
            <button onClick={() => p.onRotate(sel.id, 15)} title="15° против часовой (Q)">⟲ 15°</button>
            <button onClick={() => p.onRotate(sel.id, -15)} title="15° по часовой (E)">⟳ 15°</button>
          </div>
        </div>
        <label className="fp-note">Примечание
          <input value={sel.note ?? ''} placeholder="артикул, поставщик…" maxLength={500}
            onChange={(e) => p.onUpdate(sel.id, { note: e.target.value || undefined })} />
        </label>
        {iss.length > 0 && (
          <ul className="fp-issues">
            {iss.map((x, i) => (
              <li key={i} className={x.kind === 'zone' ? 'warn' : 'err'}>
                ⚠ {ISSUE_LABEL[x.kind]}{x.with ? <>: <button className="link" onClick={() => p.onSelect(x.with!)}>{catalogItem(p.items.find((o) => o.id === x.with)?.item ?? '').name}</button></> : null}
              </li>
            ))}
          </ul>
        )}
        {row ? (
          <div className="fp-row fp-array">
            <NumField label="Штук" value={row.n} min={2} max={50} onChange={(v) => setRow({ ...row, n: Math.round(v) })} />
            <NumField label="Зазор, см" value={cm(row.gap)} min={0} max={1000} onChange={(v) => setRow({ ...row, gap: v / 100 })} />
            <button className="primary small" onClick={() => { p.onRow(sel.id, row.n, row.gap); setRow(null) }}>Создать</button>
            <button className="small" onClick={() => setRow(null)}>Отмена</button>
          </div>
        ) : (
          <div className="fp-actions">
            <button className="small" onClick={() => p.onDuplicate(sel.id)} title="Ctrl+D">Копия</button>
            <button className="small" onClick={() => setRow({ n: 3, gap: 0 })} title="Ряд одинаковых предметов вдоль ширины">Ряд…</button>
            <button className="small danger" onClick={() => p.onDelete(sel.id)} title="Delete">Удалить</button>
          </div>
        )}
      </section>
    )
  })()

  return (
    <aside className="furniture-panel menu-root">
      <header>
        <div><b>Мебель и оборудование</b><small>{p.floor.name} · {p.items.length} шт.</small></div>
        <div className="fp-head-actions">
          <button className="icon" onClick={p.onUndo} disabled={!p.canUndo} title="Отменить (Ctrl+Z)"><Icon name="reset" size={16} /></button>
          <button className="icon" onClick={p.onClose} aria-label="Закрыть"><Icon name="close" size={16} /></button>
        </div>
      </header>

      {p.locked && <p className="fp-banner">Идёт перестроение модели — расстановку можно будет менять после него.</p>}
      {p.unplaced.length > 0 && (
        <section className="fp-unplaced">
          <b>Без этажа после перестроения: {p.unplaced.length} шт.</b>
          <small>Этаж {[...new Set(p.unplaced.map((u) => `«${u._anchor?.name || u.floor}»`))].join(', ')} не найден в новой сборке.
            Координаты сохранены — предметы можно перенести на текущий этаж ({p.floor.name}).</small>
          <div className="fp-actions">
            <button className="small primary" disabled={p.locked} onClick={() => p.onUnplaced(p.unplaced.map((u) => u.id), p.floor!.id)}>Перенести на этот этаж</button>
            <button className="small danger" disabled={p.locked} onClick={() => p.onUnplaced(p.unplaced.map((u) => u.id), null)}>Удалить</button>
          </div>
        </section>
      )}

      {selCard}

      <section className="fp-catalog">
        {catalogError && <p className="hint">⚠ {catalogError}. Обновите страницу, когда сервер будет доступен.</p>}
        <div className="fp-search">
          <Icon name="search" size={15} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск в каталоге" />
        </div>
        <select value={cat} onChange={(e) => setCat(e.target.value)}>
          <option value="all">Все категории ({CATALOG.length})</option>
          {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.name} ({CATALOG.filter((x) => x.cat === c.id).length})</option>)}
        </select>
        <ul className="fp-items">
          {found.map((c) => (
            <li key={c.id} className={p.placing?.id === c.id ? 'on' : ''} title="Перетащите на план или щёлкните, затем щёлкните на плане"
              onPointerDown={(e) => { if (e.button === 0) { e.preventDefault(); p.onPick(c, true) } }}>
              <Symbol c={c} />
              <div><span>{c.name}</span><small>{cm(c.w)}×{cm(c.d)}×{cm(c.h)} см{c.elev ? ` · на высоте ${cm(c.elev)}` : ''}</small></div>
            </li>
          ))}
          {!found.length && <li className="empty">Ничего не найдено</li>}
        </ul>
      </section>

      <section className="fp-placed">
        <div className="fp-placed-head">
          <b>На этаже</b>
          <label className="fp-check"><input type="checkbox" checked={p.showZones} onChange={(e) => p.onZones(e.target.checked)} /> зоны обслуживания</label>
        </div>
        {withIssues.length > 0 && (
          <button className="fp-issue-sum" onClick={() => {
            const i = withIssues.findIndex((x) => x.id === p.selected)
            p.onSelect(withIssues[(i + 1) % withIssues.length].id)
          }}>⚠ Замечания у {withIssues.length} шт. — показать {withIssues.length > 1 ? 'следующее' : ''}</button>
        )}
        {p.items.some((i) => catalogItem(i.item).cam) && (
          <div className="fp-cctv">
            <div className="fp-placed-head">
              <b>Видеонаблюдение</b>
              <label className="fp-check"><input type="checkbox" checked={p.camViews} onChange={(e) => p.onCamViews(e.target.checked)} /> обзор камер</label>
            </div>
            <small>Доля площади помещения в поле зрения (в скобках — где различимы лица):</small>
            <ul>
              {p.roomCover.map((r, i) => (
                <li key={i} className={r.covered < 0.6 ? 'low' : ''}>
                  <span>{r.name}</span>
                  <b>{pct(r.covered)}</b> <small>({pct(r.ident)})</small>
                </li>
              ))}
            </ul>
          </div>
        )}
        {!p.items.length && <p className="hint">Пока пусто. Перетащите предмет из каталога на план этажа.</p>}
        {byRoom.map(([room, list]) => (
          <details key={room} open={list.some((x) => x.id === p.selected) || byRoom.length <= 3}>
            <summary>{room} <small>{list.length}</small></summary>
            <ul>
              {list.map((it) => (
                <li key={it.id} className={it.id === p.selected ? 'sel' : ''} onClick={() => p.onSelect(it.id)}>
                  {p.issues.get(it.id)?.length ? <i className="dot" /> : null}{catalogItem(it.item).name}
                </li>
              ))}
            </ul>
          </details>
        ))}
      </section>
    </aside>
  )
}
