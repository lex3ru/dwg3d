import { Building2, FileSpreadsheet, Map as MapIcon, Monitor, Moon, Package, Settings, Sun } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { floatClass } from '@/components/ui/float'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { Result } from '../api'
import { useTheme, type Theme } from '../lib/theme'
import { can } from '../session'
import type { DayTime, Projection } from '../state'
import { Icon } from './icons'
import { useMenu } from './menuCtx'

/** Settings dialogs opened from the gear menu */
export type SettingsPane = 'floors' | 'site' | 'report' | 'catalog'

const pill = 'h-10 rounded-full border-0 bg-float shadow-md backdrop-blur'

/** Top-right group over the scene: view mode and display (passed in), 2D | 3D, map, settings. */
export function TopRight({ displayMenu, proj, onProj, map, onMap, mapAvailable, onSettings }: {
  displayMenu: ReactNode
  proj: Projection
  onProj: (p: Projection) => void
  map: boolean
  onMap: (v: boolean) => void
  mapAvailable: boolean
  onSettings: (which: SettingsPane) => void
}) {
  const { theme, setTheme } = useTheme()
  return (
    <div className="absolute top-3 right-3 z-20 flex items-center gap-1.5">
      {displayMenu}
      <div role="group" aria-label="Проекция" className={cn(floatClass, 'flex h-10 items-center rounded-full p-1')}>
        {(['2d', '3d'] as const).map((p) => (
          <Tip key={p} label={p === '2d' ? 'Вид сверху на активный этаж' : 'Перспектива'} side="bottom">
            <button aria-pressed={proj === p} onClick={() => onProj(p)}
              className={cn('h-8 cursor-pointer rounded-full border-0 px-3 text-xs font-bold transition-colors', proj === p ? 'bg-primary text-primary-foreground' : 'bg-transparent text-foreground hover:bg-secondary')}>
              {p.toUpperCase()}
            </button>
          </Tip>
        ))}
      </div>
      <Tip label={mapAvailable ? 'Подложка карты' : 'Подложка карты: сначала задайте привязку здания в настройках'} side="bottom">
        <Button variant="secondary" aria-pressed={map} className={cn(pill, 'px-3 @max-4xl:px-2.5', map && 'bg-primary text-primary-foreground hover:bg-primary/90')} onClick={() => onMap(!map)}>
          <MapIcon className="size-4" /> <span className="@max-4xl:hidden">Карта</span>
        </Button>
      </Tip>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="secondary" size="icon" aria-label="Настройки" className={cn(pill, 'size-10')}><Settings className="size-4" /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          <DropdownMenuItem onSelect={() => onSettings('floors')}><Building2 /> Этажи и роли слоёв чертежа…</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onSettings('site')}><MapIcon /> Карта и детальная модель…</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onSettings('report')}><FileSpreadsheet /> Спецификация оборудования…</DropdownMenuItem>
          {can('catalog_admin') && <DropdownMenuItem onSelect={() => onSettings('catalog')}><Package /> Каталог оборудования…</DropdownMenuItem>}
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Тема</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as Theme)}>
            <DropdownMenuRadioItem value="light"><Sun /> Светлая</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="dark"><Moon /> Тёмная</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="system"><Monitor /> Как в системе</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
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
