import type { FloorMeta, Job, Result, RoomMeta } from '../api'
import { fileUrl } from '../api'
import { Icon } from './icons'

export function HelpButton({ onClick }: { onClick: () => void }) {
  return <button className="help-btn round" onClick={onClick} title="Справка по управлению"><Icon name="help" /></button>
}

const HELP: [string, [string, string][]][] = [
  ['Обзор', [
    ['ЛКМ + перетаскивание', 'вращение вокруг здания'],
    ['ПКМ / Shift + ЛКМ', 'панорама'],
    ['Колесо, щипок, «+» / «−»', 'зум'],
    ['Клик по помещению', 'карточка помещения'],
    ['Номер этажа слева', 'срез до этажа, «+» — всё здание'],
  ]],
  ['Полёт', [
    ['W A S D, стрелки', 'перемещение'],
    ['E / Пробел, Q / C', 'вверх, вниз'],
    ['Перетаскивание мышью', 'осмотр'],
    ['Колесо', 'вперёд / назад'],
    ['Shift', 'быстрее'],
  ]],
  ['Прогулка', [
    ['Клик по сцене', 'захват мыши для осмотра'],
    ['W A S D, стрелки', 'идти'],
    ['Shift', 'быстрее'],
    ['Esc', 'выйти'],
  ]],
  ['Вид 2D', [
    ['ЛКМ + перетаскивание', 'сдвиг плана'],
    ['ПКМ + перетаскивание', 'поворот'],
    ['Колесо', 'зум'],
  ]],
  ['Рулетка', [
    ['Два клика', 'расстояние'],
    ['Клики по вершинам', 'площадь; замкнуть — клик по первой точке, двойной клик или Enter'],
    ['Backspace / Esc', 'убрать точку / сбросить'],
  ]],
]

export function HelpOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div className="help-overlay" onClick={onClose}>
      <div className="help-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Справка">
        <header><h2>Управление</h2><button className="icon" onClick={onClose} aria-label="Закрыть"><Icon name="close" /></button></header>
        <div className="help-grid">
          {HELP.map(([title, rows]) => (
            <section key={title}>
              <h3>{title}</h3>
              <dl>{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}

export function RoomCard({ room, floor, result, onClose, onRoute, onFly }: {
  room: RoomMeta
  floor: FloorMeta
  result: Result
  onClose: () => void
  onRoute: (end: 'from' | 'to') => void
  onFly: () => void
}) {
  const t = result.room_types?.find((x) => x.type === (room.type ?? 'other'))
  return (
    <div className="room-card" role="dialog">
      <header>
        <b>{room.name || t?.label || 'Помещение'}</b>
        <button className="icon" onClick={onClose} aria-label="Закрыть"><Icon name="close" size={16} /></button>
      </header>
      <dl>
        <div><dt>Тип</dt><dd><i style={{ background: t?.color ?? '#ece6da' }} />{t?.label ?? 'Прочие'}</dd></div>
        <div><dt>Площадь</dt><dd>{room.area.toFixed(1)} м²</dd></div>
        <div><dt>Этаж</dt><dd>{floor.name}</dd></div>
      </dl>
      <div className="rc-actions">
        <button className="small" onClick={onFly}>Показать</button>
        <button className="small" onClick={() => onRoute('from')}>Маршрут отсюда</button>
        <button className="small" onClick={() => onRoute('to')}>Сюда</button>
      </div>
    </div>
  )
}

/** "Здание и этажи": floors with details, editor, saving, exports, warnings. */
export function BuildingPanel({ job, shown, active, running, editCount, saving, saveErr, onFloor, onEditor, onSave, onClose }: {
  job: Job
  shown: Job
  active: string | null
  running: boolean
  editCount: number
  saving: 'dxf' | 'dwg' | null
  saveErr: string | null
  onFloor: (id: string | null) => void
  onEditor: () => void
  onSave: (f: 'dxf' | 'dwg') => void
  onClose: () => void
}) {
  const r = shown.result!
  const floors = [...r.floors].sort((a, b) => b.elevation! - a.elevation!)
  const act = floors.find((f) => f.id === active)
  return (
    <aside className="building-panel menu-root">
      <header>
        <div><b>{job.filename}</b><small>{r.floors.length} этажей · {r.floors.reduce((s, f) => s + f.stats.rooms, 0)} помещений</small></div>
        <button className="icon" onClick={onClose} aria-label="Закрыть"><Icon name="close" size={16} /></button>
      </header>
      <ul className="floors">
        <li className={active == null ? 'sel' : ''} onClick={() => onFloor(null)}>
          <div className="f-name">Всё здание</div>
        </li>
        {floors.map((f) => (
          <li key={f.id} className={active === f.id ? 'sel' : ''} onClick={() => onFloor(f.id)}>
            <div className="f-name"><span className="lvl">{f.level}</span>{f.name}</div>
            <div className="f-meta">
              <span>{f.elevation! >= 0 ? '+' : ''}{f.elevation!.toFixed(2)} м</span>
              <span>h {f.height!.toFixed(2)} м</span>
              <span>{f.stats.rooms} пом.</span>
              <span>{Math.round(f.stats.footprint_m2)} м²</span>
            </div>
          </li>
        ))}
      </ul>
      <button className="secondary" disabled={running || !act} onClick={onEditor}
        title="Исправить стены, проёмы и помещения на плане этажа">
        <Icon name="edit" size={15} /> 2D-редактор: {act?.name ?? 'выберите этаж'}
      </button>
      {editCount > 0 && (
        <div className="save-drawing">
          <div className="sd-title">Чертёж с правками <span>{editCount}</span></div>
          <div className="sd-buttons">
            {(['dxf', 'dwg'] as const).map((f) => (
              <button key={f} className="small" disabled={!!saving || running} onClick={() => onSave(f)}>
                {saving === f ? 'Готовлю…' : `Сохранить ${f.toUpperCase()}`}
              </button>
            ))}
          </div>
          {saveErr && <div className="error small-err">{saveErr}</div>}
        </div>
      )}
      {r.exports && (
        <div className="exports">
          <span>Скачать модель:</span>
          {Object.entries(r.exports).map(([k, name]) => (
            <a key={k} href={fileUrl(shown.id, name, shown.build)} download>{k.toUpperCase()}</a>
          ))}
        </div>
      )}
      {r.quality?.status === 'suspect' && (
        <div className="quality-card">
          <b>Результат выглядит сомнительно</b>
          {r.quality.issues.map((w) => <p key={w}>{w}</p>)}
          <p className="hint">Проверьте роли слоёв и единицы в настройках.</p>
        </div>
      )}
      {(r.edits_unmatched ?? 0) > 0 && (
        <div className="warn-card"><p>⚠ Правки {r.edits_unmatched} этаж(ей) не применены: их лист не найден в текущем разборе.</p></div>
      )}
      {r.warnings.length > 0 && <div className="warn-card">{r.warnings.map((w) => <p key={w}>⚠ {w}</p>)}</div>}
      <div className="info">Единицы: {r.units} ({r.units_source}) · {r.triangles.toLocaleString('ru')} треуг. · {r.elapsed_s} с</div>
    </aside>
  )
}
