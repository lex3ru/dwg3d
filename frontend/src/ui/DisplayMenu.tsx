import type { Cuts } from '../viewer/Viewer'
import { resolveFacade, type Display, type Facade, type Quality } from '../state'
import { Icon } from './icons'
import { Check, Radio } from './menu'
import { useMenu } from './menuCtx'

const Q_LABEL = { high: 'высокое', eco: 'экономное', real: 'реализм' }

/** "Отображение": view switches, 3D quality, facade lighting, layers, sections. */
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
  const m = useMenu('display')
  const facadeNow = resolveFacade(display.facade)
  return (
    <div className="menu-root">
      <button className={`tb-btn${m.isOpen ? ' on' : ''}`} onClick={m.toggle} aria-expanded={m.isOpen}>
        <Icon name="layers" /> <span className="tb-label">Отображение</span> <Icon name="chevron" size={14} />
      </button>
      {m.isOpen && (
        <div className="menu drop-right display-menu" role="menu">
          <Check on={display.xray} label="Прозрачные стены" onChange={(v) => set({ xray: v })} />
          <Check on={display.onlyActive} label="Только активный этаж" onChange={(v) => set({ onlyActive: v })} />
          <Check on={display.roomColors} label="Цвета типов помещений" onChange={(v) => set({ roomColors: v })} />
          <Check on={display.explode} label="Разнести этажи" onChange={(v) => set({ explode: v })} />
          {display.explode && (
            <label className="menu-slider">
              <span>Зазор {display.explodeGap} м</span>
              <input type="range" min={2} max={20} step={0.5} value={display.explodeGap}
                onChange={(e) => set({ explodeGap: Number(e.target.value) })} />
            </label>
          )}
          <Check on={display.highlight} label="Подсвечивать текущий этаж" onChange={(v) => set({ highlight: v })} />

          <div className="menu-title">Качество 3D</div>
          <Radio<Quality> value={display.quality} onChange={(q) => set({ quality: q })} options={[
            { id: 'auto', label: `Авто (по устройству)${display.quality === 'auto' ? ` — ${Q_LABEL[resolvedQuality]}` : ''}` },
            { id: 'high', label: 'Высокое', hint: 'Сглаживание, чёткость до 2×, контурные рёбра, тени' },
            { id: 'eco', label: 'Экономное', hint: 'Без сглаживания, рёбер и теней, простые материалы' },
            { id: 'real', label: 'Реализм: свет и тени', hint: 'Мягкие тени и освещение от окружения' },
          ]} />

          <div className="menu-title">Подсветка фасада</div>
          <Radio<Facade> value={display.facade} onChange={(f) => set({ facade: f })} options={[
            { id: 'auto', label: `Авто${display.facade === 'auto' ? ` — ${facadeNow === 'holiday' ? 'праздники' : 'будни'}` : ''}`,
              hint: 'Праздничные даты и новогодние дни — «Праздники», иначе «Будни»' },
            { id: 'weekday', label: 'Будни' },
            { id: 'holiday', label: 'Праздники' },
          ]} />
          {display.dayTime === 'day' && (
            <p className="menu-note">Подсветка видна вечером и ночью — кнопка <Icon name="sun" size={13} /> справа.</p>
          )}

          <div className="menu-title">Слои</div>
          <Check on={display.roof} label="Кровля" onChange={(v) => set({ roof: v })} />
          <Check on={display.glass} label="Остекление" onChange={(v) => set({ glass: v })} />
          <Check on={display.rooms} label="Полы помещений" onChange={(v) => set({ rooms: v })} />
          <Check on={display.labels} label="Подписи помещений" onChange={(v) => set({ labels: v })} />

          <div className="menu-title">Разрезы</div>
          <label className="cut-row">
            <input type="checkbox" checked={cuts.h.on} onChange={(e) => setCuts({ ...cuts, h: { ...cuts.h, on: e.target.checked } })} />
            <span>По высоте</span>
            <input type="range" min={yRange[0]} max={yRange[1]} step={0.05} value={cuts.h.y} disabled={!cuts.h.on}
              onChange={(e) => setCuts({ ...cuts, h: { ...cuts.h, y: Number(e.target.value) } })} />
            <span className="val">{cuts.h.y.toFixed(1)}</span>
          </label>
          <label className="cut-row">
            <input type="checkbox" checked={cuts.v.on} onChange={(e) => setCuts({ ...cuts, v: { ...cuts.v, on: e.target.checked } })} />
            <span>Вертикальный</span>
            <input type="range" min={xRange[0]} max={xRange[1]} step={0.1} value={cuts.v.x} disabled={!cuts.v.on}
              onChange={(e) => setCuts({ ...cuts, v: { ...cuts.v, x: Number(e.target.value) } })} />
            <span className="val">{cuts.v.x.toFixed(1)}</span>
          </label>
          {floorCut && <button className="menu-item" onClick={floorCut}>План-срез активного этажа (1,2 м)</button>}
        </div>
      )}
    </div>
  )
}
