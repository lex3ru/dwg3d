import type { ReactNode } from 'react'
import type { Result } from '../api'
import { useTheme, type Theme } from '../lib/theme'
import { can } from '../session'
import type { DayTime, Projection } from '../state'
import { Icon } from './icons'
import { useMenu } from './menuCtx'

/** Settings dialogs opened from the gear menu */
export type SettingsPane = 'floors' | 'site' | 'report' | 'catalog'

/** Top-right group: ruler, display menu (passed in), 2D | 3D, map, settings. */
export function TopRight({ displayMenu, proj, onProj, map, onMap, mapAvailable, onSettings }: {
  displayMenu: ReactNode
  proj: Projection
  onProj: (p: Projection) => void
  map: boolean
  onMap: (v: boolean) => void
  mapAvailable: boolean
  onSettings: (which: SettingsPane) => void
}) {
  const gear = useMenu('gear')
  const { theme, setTheme } = useTheme()
  const NEXT: Record<Theme, Theme> = { light: 'dark', dark: 'system', system: 'light' }
  const THEME_NAME: Record<Theme, string> = { light: 'светлая', dark: 'тёмная', system: 'как в системе' }
  return (
    <div className="top-right">
      {displayMenu}
      <div className="seg-toggle" role="group" aria-label="Проекция">
        {(['2d', '3d'] as const).map((p) => (
          <button key={p} className={proj === p ? 'on' : ''} onClick={() => onProj(p)}
            title={p === '2d' ? 'Вид сверху на активный этаж' : 'Перспектива'}>{p.toUpperCase()}</button>
        ))}
      </div>
      <button className={`tb-btn${map ? ' on' : ''}`} onClick={() => onMap(!map)}
        title={mapAvailable ? 'Подложка карты' : 'Подложка карты: сначала задайте привязку здания в настройках'}>
        <Icon name="map" /> <span className="tb-label">Карта</span>
      </button>
      <div className="menu-root">
        <button className={`tb-btn${gear.isOpen ? ' on' : ''}`} onClick={gear.toggle} title="Настройки"><Icon name="gear" /></button>
        {gear.isOpen && (
          <div className="menu drop-right" role="menu">
            <button className="menu-item" onClick={() => { gear.close(); onSettings('floors') }}>Этажи и слои…</button>
            <button className="menu-item" onClick={() => { gear.close(); onSettings('site') }}>Карта и детальная модель…</button>
            <button className="menu-item" onClick={() => { gear.close(); onSettings('report') }}>Спецификация оборудования…</button>
            {can('catalog_admin') && (
              <button className="menu-item" onClick={() => { gear.close(); onSettings('catalog') }}>Каталог оборудования…</button>
            )}
            <button className="menu-item" onClick={() => setTheme(NEXT[theme])}>Тема: {THEME_NAME[theme]}</button>
          </div>
        )}
      </div>
    </div>
  )
}

const DAY_ICON = { day: 'sun', evening: 'sunset', night: 'moon' } as const
const DAY_LABEL = { day: 'день', evening: 'вечер', night: 'ночь' }
const NEXT_DAY: Record<DayTime, DayTime> = { day: 'evening', evening: 'night', night: 'day' }

/** Right column: time of day, zoom in, fit the building, zoom out, legend. */
export function SideControls({ dayTime, onDayTime, onZoom, onFit, legend }: {
  dayTime: DayTime
  onDayTime: (d: DayTime) => void
  onZoom: (d: 1 | -1) => void
  onFit: () => void
  legend: ReactNode
}) {
  return (
    <div className="side-controls">
      <button className="round" onClick={() => onDayTime(NEXT_DAY[dayTime])}
        title={`Время суток: ${DAY_LABEL[dayTime]} (сменить)`}><Icon name={DAY_ICON[dayTime]} /></button>
      <div className="stack">
        <button className="round" onClick={() => onZoom(1)} title="Приблизить"><Icon name="plus" /></button>
        <button className="round" onClick={onFit} title="Вписать здание"><Icon name="fit" /></button>
        <button className="round" onClick={() => onZoom(-1)} title="Отдалить"><Icon name="minus" /></button>
      </div>
      {legend}
    </div>
  )
}

/** Legend of room-type colours (library button). */
export function Legend({ result, on, onToggleColors }: { result: Result; on: boolean; onToggleColors: (v: boolean) => void }) {
  const m = useMenu('legend')
  const counts = new Map<string, number>()
  result.floors.forEach((f) => f.rooms.forEach((r) => counts.set(r.type ?? 'other', (counts.get(r.type ?? 'other') ?? 0) + 1)))
  const types = (result.room_types ?? []).filter((t) => counts.has(t.type))
  return (
    <div className="menu-root">
      <button className={`round${m.isOpen ? ' on' : ''}`} onClick={m.toggle} title="Легенда: типы помещений"><Icon name="book" /></button>
      {m.isOpen && (
        <div className="menu drop-side legend-menu" role="dialog">
          <div className="menu-title">Типы помещений</div>
          {types.length === 0 && <p className="menu-note">Нет данных о типах — пересоберите модель.</p>}
          {types.map((t) => (
            <div key={t.type} className="legend-row">
              <i style={{ background: t.color }} /><span>{t.label}</span><small>{counts.get(t.type)}</small>
            </div>
          ))}
          <label className="legend-toggle">
            <input type="checkbox" checked={on} onChange={(e) => onToggleColors(e.target.checked)} /> Окрашивать полы по типу
          </label>
          <div className="menu-title">Элементы</div>
          <div className="legend-row"><i style={{ background: '#ede8de' }} /><span>Стены</span></div>
          <div className="legend-row"><i style={{ background: '#dbe3ed' }} /><span>Перегородки</span></div>
          <div className="legend-row"><i style={{ background: '#a8805c' }} /><span>Двери</span></div>
          <div className="legend-row"><i style={{ background: '#8cbff2' }} /><span>Остекление</span></div>
          <div className="legend-row"><i style={{ background: '#c7bdad' }} /><span>Лестницы</span></div>
        </div>
      )}
    </div>
  )
}
