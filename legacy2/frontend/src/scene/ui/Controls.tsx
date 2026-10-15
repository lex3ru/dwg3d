import { LATER } from '../compat'
import { BookOpen, Bot, Building2, FileSpreadsheet, Map as MapIcon, Maximize, Minus, Monitor, Moon, Package, Plus, Settings, Sun, Sunset } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { floatClass } from '@/components/ui/float'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { Result } from '../api'
import { useTheme, type Theme } from '@/lib/theme'
import { can } from '../session'
import type { DayTime, Projection } from '../state'

/** Settings dialogs opened from the gear menu */
export type SettingsPane = 'floors' | 'site' | 'report' | 'catalog' | 'copilot'

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
          <Tip key={p} label={p === '2d' ? 'План одного этажа сверху, без перспективы; без выбранного этажа — этаж входа' : 'Объёмная модель в перспективе: обзор, полёт и прогулка'} side="bottom">
            <button aria-pressed={proj === p} onClick={() => onProj(p)}
              className={cn('h-8 cursor-pointer rounded-full border-0 px-3 text-xs font-bold transition-colors', proj === p ? 'bg-primary text-primary-foreground' : 'bg-transparent text-foreground hover:bg-secondary')}>
              {p.toUpperCase()}
            </button>
          </Tip>
        ))}
      </div>
      <Tip label={mapAvailable ? 'Показать или скрыть карту местности под зданием' : 'Здание ещё не привязано к карте: откроются настройки привязки'} side="bottom">
        <Button variant="secondary" aria-pressed={map} className={cn(pill, 'px-3 @max-4xl:px-2.5', map && 'bg-primary text-primary-foreground hover:bg-primary/90')} onClick={() => onMap(!map)}>
          <MapIcon className="size-4" /> <span className="@max-4xl:hidden">Карта</span>
        </Button>
      </Tip>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="secondary" size="icon" aria-label="Настройки" hint="Этажи и слои чертежа, привязка к карте, тема оформления" hintSide="bottom" className={cn(pill, 'size-10')}><Settings className="size-4" /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          <Tip label="Как делить чертёж на этажи и какие слои DWG — стены, двери, помещения; после изменения модель пересоберётся" side="left">
            <DropdownMenuItem onSelect={() => onSettings('floors')}><Building2 /> Этажи и роли слоёв чертежа…</DropdownMenuItem>
          </Tip>
          <Tip label="Название чертежа, точка и азимут здания на карте, готовая GLB-модель фасада и мебели поверх распознанной" side="left">
            <DropdownMenuItem onSelect={() => onSettings('site')}><MapIcon /> Карта и детальная модель…</DropdownMenuItem>
          </Tip>
          {LATER.reports && (
            <Tip label="Сколько какого оборудования по этажам и помещениям; выгрузка в Excel" side="left">
              <DropdownMenuItem onSelect={() => onSettings('report')}><FileSpreadsheet /> Спецификация оборудования…</DropdownMenuItem>
            </Tip>
          )}
          {LATER.catalog && can('catalog_admin') && (
            <Tip label="Позиции каталога для всех проектов: размеры, модели, артикулы, цены, 3D-модели" side="left">
              <DropdownMenuItem onSelect={() => onSettings('catalog')}><Package /> Каталог оборудования…</DropdownMenuItem>
            </Tip>
          )}
          {LATER.copilot && can('admin') && (
            <Tip label="Какая языковая модель отвечает в копилоте, её ключ и лимиты; действует для всех пользователей" side="left">
              <DropdownMenuItem onSelect={() => onSettings('copilot')}><Bot /> Копилот: модель и лимиты…</DropdownMenuItem>
            </Tip>
          )}
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

const DAY_ICON = { day: Sun, evening: Sunset, night: Moon } as const
const DAY_LABEL = { day: 'день', evening: 'вечер', night: 'ночь' }
const NEXT_DAY: Record<DayTime, DayTime> = { day: 'evening', evening: 'night', night: 'day' }
const roundBase = 'grid size-10 cursor-pointer place-items-center rounded-full p-0 text-foreground transition-colors hover:text-primary [&_svg]:size-[18px]'
/** a button inside the zoom stack */
const roundBtn = `${roundBase} border-0 bg-transparent hover:bg-secondary`
/** a button on its own */
const roundFloat = cn(floatClass, roundBase)

/** Right column: time of day, zoom in, fit the building, zoom out, legend. */
export function SideControls({ dayTime, onDayTime, onZoom, onFit, legend }: {
  dayTime: DayTime
  onDayTime: (d: DayTime) => void
  onZoom: (d: 1 | -1) => void
  onFit: () => void
  legend: ReactNode
}) {
  const Day = DAY_ICON[dayTime]
  return (
    <div className="absolute top-1/2 right-3.5 z-15 flex -translate-y-1/2 flex-col items-center gap-2.5">
      <Tip label={`Сейчас ${DAY_LABEL[dayTime]}, дальше — ${DAY_LABEL[NEXT_DAY[dayTime]]}: меняет свет сцены; вечером и ночью горит подсветка фасада`} side="left">
        <button aria-label={`Время суток: ${DAY_LABEL[dayTime]} (сменить)`} className={roundFloat} onClick={() => onDayTime(NEXT_DAY[dayTime])}><Day /></button>
      </Tip>
      <div className={cn(floatClass, 'flex flex-col rounded-full')}>
        <Tip label="Камера на шаг ближе к центру обзора, как колесо мыши; шаг задаёт скорость навигации" side="left"><button aria-label="Приблизить" className={roundBtn} onClick={() => onZoom(1)}><Plus /></button></Tip>
        <Tip label="Вернуть камеру так, чтобы в кадр вошло всё здание; в 2D — весь этаж" side="left"><button aria-label="Вписать здание" className={roundBtn} onClick={onFit}><Maximize /></button></Tip>
        <Tip label="Камера на шаг дальше от центра обзора, как колесо мыши" side="left"><button aria-label="Отдалить" className={roundBtn} onClick={() => onZoom(-1)}><Minus /></button></Tip>
      </div>
      {legend}
    </div>
  )
}

const ELEMENTS: [string, string][] = [['Стены', '#ede8de'], ['Перегородки', '#dbe3ed'], ['Двери', '#a8805c'], ['Остекление', '#8cbff2'], ['Лестницы', '#c7bdad']]
const Swatch = ({ color }: { color: string }) => <i className="size-3.5 shrink-0 rounded-[4px] border border-black/10" style={{ background: color }} />

/** Legend of room-type colours and building elements. */
export function Legend({ result, on, onToggleColors }: { result: Result; on: boolean; onToggleColors: (v: boolean) => void }) {
  const counts = new Map<string, number>()
  result.floors.forEach((f) => f.rooms.forEach((r) => counts.set(r.type ?? 'other', (counts.get(r.type ?? 'other') ?? 0) + 1)))
  const types = (result.room_types ?? []).filter((t) => counts.has(t.type))
  return (
    <Popover>
      <Tip label="Цвета типов помещений и элементов здания; там же включается окраска полов" side="left">
        <PopoverTrigger asChild>
          <button aria-label="Легенда: типы помещений" className={roundFloat}><BookOpen /></button>
        </PopoverTrigger>
      </Tip>
      <PopoverContent side="left" align="center" sideOffset={10} className="w-64 p-2">
        <div className="px-1 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Типы помещений</div>
        {types.length === 0 && <p className="m-0 px-1 py-1 text-xs text-muted-foreground">Нет данных о типах — пересоберите модель.</p>}
        <ul className="m-0 grid list-none gap-0.5 p-0">
          {types.map((t) => (
            <li key={t.type} className="flex items-center gap-2 px-1 py-0.5 text-sm">
              <Swatch color={t.color} /><span className="flex-1">{t.label}</span><small className="text-muted-foreground">{counts.get(t.type)}</small>
            </li>
          ))}
        </ul>
        <Tip label="Залить полы цветами из этого списка; настройка хранится в этом браузере" side="left">
          <label className="mt-1 flex cursor-pointer items-center gap-2 rounded-md px-1 py-1.5 text-sm hover:bg-secondary">
            <span className="flex-1">Окрашивать полы по типу</span>
            <Switch checked={on} onCheckedChange={onToggleColors} />
          </label>
        </Tip>
        <div className="px-1 pt-2 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Элементы</div>
        <ul className="m-0 grid list-none gap-0.5 p-0">
          {ELEMENTS.map(([name, color]) => <li key={name} className="flex items-center gap-2 px-1 py-0.5 text-sm"><Swatch color={color} />{name}</li>)}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
