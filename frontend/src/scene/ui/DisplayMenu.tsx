import { ChevronDown, Layers2, Sun } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { Cuts } from '../viewer/Viewer'
import { resolveFacade, type Display, type Facade, type Quality } from '../state'

const Q_LABEL = { high: 'высокое', eco: 'экономное', real: 'реализм' }

const Title = ({ children }: { children: ReactNode }) => (
  <div className="px-2 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase first:pt-1">{children}</div>
)
function Toggle({ on, label, hint, onChange }: { on: boolean; label: string; hint?: string; onChange: (v: boolean) => void }) {
  return (
    <Tip label={hint} side="left">
      <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-secondary">
        <span className="flex-1">{label}</span>
        <Switch checked={on} onCheckedChange={onChange} />
      </label>
    </Tip>
  )
}
function Choice<T extends string>({ value, options, onChange }: { value: T; options: { id: T; label: string; hint?: string }[]; onChange: (v: T) => void }) {
  return (
    <div role="radiogroup" className="grid gap-0.5">
      {options.map((o) => (
        <Tip key={o.id} label={o.hint} side="left">
          <button role="radio" aria-checked={value === o.id} onClick={() => onChange(o.id)}
            className={cn('flex cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-sm text-foreground hover:bg-secondary', value === o.id && 'text-primary')}>
            <span className={cn('grid size-3.5 place-items-center rounded-full border', value === o.id ? 'border-primary' : 'border-input')}>
              {value === o.id && <span className="size-1.5 rounded-full bg-primary" />}
            </span>
            {o.label}
          </button>
        </Tip>
      ))}
    </div>
  )
}
function Cut({ on, label, hint, min, max, step, value, onOn, onValue }: {
  on: boolean; label: string; hint: string; min: number; max: number; step: number; value: number; onOn: (v: boolean) => void; onValue: (v: number) => void
}) {
  return (
    <Tip label={hint} side="left">
    <div className="grid grid-cols-[auto_1fr_2.5rem] items-center gap-2 px-2 py-1 text-sm">
      <Switch checked={on} onCheckedChange={onOn} aria-label={label} />
      <span className="grid gap-1"><span className="text-xs text-muted-foreground">{label}</span>
        <input type="range" className="w-full accent-primary" min={min} max={max} step={step} value={value} disabled={!on} onChange={(e) => onValue(Number(e.target.value))} />
      </span>
      <span className="text-right text-xs tabular-nums text-muted-foreground">{value.toFixed(1)}</span>
    </div>
    </Tip>
  )
}

/** "Отображение": what of the model is drawn, 3D quality, facade lighting, sections. */
export default function DisplayMenu({ display, set, resolvedQuality, cuts, setCuts, yRange, xRange, floorCut }: {
  display: Display
  set: (patch: Partial<Display>) => void
  resolvedQuality: 'high' | 'eco' | 'real'
  cuts: Cuts
  setCuts: (c: Cuts) => void
  yRange: [number, number]
  xRange: [number, number]
  floorCut: (() => void) | null
}) {
  const facadeNow = resolveFacade(display.facade)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="secondary" aria-label="Отображение" className="h-10 gap-1.5 rounded-full border-0 bg-float px-3 shadow-md backdrop-blur @max-4xl:px-2.5"
          hint="Что видно в модели, качество 3D, подсветка фасада и разрезы; настройки хранятся в этом браузере" hintSide="bottom">
          <Layers2 className="size-4" /> <span className="@max-4xl:hidden">Отображение</span> <ChevronDown className="size-3.5 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80" onKeyDown={(e) => e.stopPropagation()}>
        <Title>Здание</Title>
        <Toggle on={display.xray} label="Прозрачные стены" hint="Стены и колонны полупрозрачные: видно помещения и оборудование за ними" onChange={(v) => set({ xray: v })} />
        <Toggle on={display.onlyActive} label="Только активный этаж" hint="При выбранном этаже скрыть все остальные, а не только верхние" onChange={(v) => set({ onlyActive: v })} />
        <Toggle on={display.highlight} label="Приглушать другие этажи" hint="Выбранный этаж ярче, остальные бледнее" onChange={(v) => set({ highlight: v })} />
        <Toggle on={display.roomColors} label="Цвета типов помещений" hint="Полы окрашены по типу помещения, как в легенде справа" onChange={(v) => set({ roomColors: v })} />
        <Toggle on={display.explode} label="Разнести этажи" hint="Раздвинуть этажи по высоте, чтобы видеть каждый; только в 3D и не на прогулке" onChange={(v) => set({ explode: v })} />
        {display.explode && (
          <Tip label="Расстояние между разнесёнными этажами" side="left">
            <label className="grid gap-1 px-2 pb-1 text-xs text-muted-foreground">Зазор {display.explodeGap} м
              <input type="range" className="accent-primary" min={2} max={20} step={0.5} value={display.explodeGap} onChange={(e) => set({ explodeGap: Number(e.target.value) })} />
            </label>
          </Tip>
        )}
        <Toggle on={display.roof} label="Кровля" hint="Крыша над зданием в 3D, когда этаж не выбран" onChange={(v) => set({ roof: v })} />
        <Toggle on={display.glass} label="Остекление" hint="Стёкла окон и витражей; без них проёмы пустые" onChange={(v) => set({ glass: v })} />
        <Toggle on={display.rooms} label="Полы помещений" hint="Заливка полов внутри помещений; без неё видны стены и плиты" onChange={(v) => set({ rooms: v })} />
        <Toggle on={display.labels} label="Подписи помещений" hint="Названия помещений в сцене; у разнесённых этажей — и их названия" onChange={(v) => set({ labels: v })} />

        <Title>Разрезы</Title>
        <Cut on={cuts.h.on} label="По высоте, м" hint="Срезать всё выше заданной отметки, чтобы заглянуть внутрь" min={yRange[0]} max={yRange[1]} step={0.05} value={cuts.h.y}
          onOn={(v) => setCuts({ ...cuts, h: { ...cuts.h, on: v } })} onValue={(v) => setCuts({ ...cuts, h: { ...cuts.h, y: v } })} />
        <Cut on={cuts.v.on} label="Вертикальный, м" hint="Рассечь здание вертикальной плоскостью; ползунок сдвигает её по оси X" min={xRange[0]} max={xRange[1]} step={0.1} value={cuts.v.x}
          onOn={(v) => setCuts({ ...cuts, v: { ...cuts.v, on: v } })} onValue={(v) => setCuts({ ...cuts, v: { ...cuts.v, x: v } })} />
        {floorCut && <Button variant="ghost" size="sm" className="mx-1 my-0.5" hint="Срезать модель на 1,2 м над полом выбранного этажа, как на архитектурном плане" hintSide="left" onClick={floorCut}>План-срез активного этажа (1,2 м)</Button>}

        <Title>Качество 3D</Title>
        <Choice<Quality> value={display.quality} onChange={(q) => set({ quality: q })} options={[
          { id: 'auto', label: `Авто (по устройству)${display.quality === 'auto' ? ` — ${Q_LABEL[resolvedQuality]}` : ''}`, hint: 'Качество подбирается под возможности этого устройства' },
          { id: 'high', label: 'Высокое', hint: 'Сглаживание, чёткость до 2×, контурные рёбра и тени' },
          { id: 'eco', label: 'Экономное', hint: 'Без сглаживания, рёбер и теней, простые материалы: для слабых устройств' },
          { id: 'real', label: 'Реализм: свет и тени', hint: 'Мягкие тени и освещение от окружения' },
        ]} />

        <Title>Подсветка фасада</Title>
        <Choice<Facade> value={display.facade} onChange={(f) => set({ facade: f })} options={[
          { id: 'auto', label: `Авто${display.facade === 'auto' ? ` — ${facadeNow === 'holiday' ? 'праздники' : 'будни'}` : ''}`,
            hint: 'В праздничные даты и новогодние дни — «Праздники», иначе «Будни»' },
          { id: 'weekday', label: 'Будни', hint: 'Тёплый свет в окнах и мягкий контур здания вечером и ночью' },
          { id: 'holiday', label: 'Праздники', hint: 'Разноцветные окна и яркий переливающийся контур вечером и ночью' },
        ]} />
        {display.dayTime === 'day' && (
          <p className="m-0 flex items-center gap-1 px-2 py-1.5 text-xs text-muted-foreground">Видна вечером и ночью — кнопка <Sun className="size-3.5" /> справа.</p>
        )}
      </PopoverContent>
    </Popover>
  )
}
