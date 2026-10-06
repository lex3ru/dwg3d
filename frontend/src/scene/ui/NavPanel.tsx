import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { floatClass } from '@/components/ui/float'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { DEFAULT_SPEEDS, SPEED_STEPS, type NavMode, type Speeds } from '../state'

const TITLE: Record<NavMode, string> = { orbit: 'Обзор', fly: 'Полёт', walk: 'Прогулка' }
const HINT: Record<NavMode, string> = {
  orbit: 'Шаг зума колесом, кнопками «+» и «−» и щипком на трекпаде',
  fly: 'Перелёт клавишами WASD и стрелками, зум колесом и кнопками «+» и «−»',
  walk: 'WASD — идти, мышь — осматриваться, Shift — быстрее, Esc — выйти',
}
const fmt = (v: number) => `×${String(v).replace('.', ',')}`
const step = 'grid size-6 shrink-0 cursor-pointer place-items-center rounded-md border-0 bg-transparent p-0 text-muted-foreground hover:bg-secondary hover:text-foreground disabled:cursor-default disabled:opacity-40'

function Stepper({ label, hint, value, steps, onChange }: { label: string; hint: string; value: number; steps: number[]; onChange: (v: number) => void }) {
  const i = Math.max(0, steps.findIndex((s) => s >= value - 1e-9))
  return (
    <div className="grid gap-1">
      <span className="text-xs text-muted-foreground">{label} <b className="text-foreground">{fmt(value)}</b></span>
      <div className="flex items-center gap-1">
        <button className={step} onClick={() => onChange(steps[Math.max(0, i - 1)])} disabled={i === 0} aria-label="Медленнее"><ChevronLeft className="size-4" /></button>
        <Tip label={hint}>
          <input type="range" className="min-w-0 flex-1 accent-primary" min={0} max={steps.length - 1} step={1} value={i} aria-label={label}
            onChange={(e) => onChange(steps[Number(e.target.value)])} />
        </Tip>
        <button className={step} onClick={() => onChange(steps[Math.min(steps.length - 1, i + 1)])} disabled={i === steps.length - 1} aria-label="Быстрее"><ChevronRight className="size-4" /></button>
      </div>
    </div>
  )
}

/** Bottom-right panel of the current navigation mode: speed, hint, reset. Starts collapsed; the choice is kept. */
export default function NavPanel({ nav, speeds, onSpeeds }: { nav: NavMode; speeds: Speeds; onSpeeds: (s: Speeds) => void }) {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem('dwg3d.navpanel') === '1' } catch { return false } })
  const toggle = () => {
    try { localStorage.setItem('dwg3d.navpanel', open ? '0' : '1') } catch { /* storage blocked */ }
    setOpen(!open)
  }
  const reset = () => onSpeeds(nav === 'walk'
    ? { ...speeds, walk: DEFAULT_SPEEDS.walk, eye: DEFAULT_SPEEDS.eye }
    : { ...speeds, [nav]: DEFAULT_SPEEDS[nav] })
  return (
    <section aria-label={`Навигация: ${TITLE[nav]}`}
      className={cn(floatClass, 'absolute right-3.5 bottom-3.5 z-18 rounded-xl px-3 py-2 text-xs select-none @max-3xl:hidden', open ? 'w-64' : 'w-auto')}>
      <header className="flex items-center gap-2">
        <b className="flex-1 text-[11px] tracking-[0.08em] uppercase">{TITLE[nav]}</b>
        <Tip label={nav === 'walk' ? 'Вернуть исходные скорость ходьбы и высоту глаз' : 'Вернуть исходную скорость этого режима'}>
          <button className="cursor-pointer border-0 bg-transparent p-0 text-xs text-primary hover:underline" onClick={reset}>сброс</button>
        </Tip>
        <Tip label={open ? 'Спрятать настройки скорости' : 'Скорость камеры и клавиши управления; выбор запомнится в этом браузере'}>
          <button className={step} onClick={toggle} aria-expanded={open} aria-label={open ? 'Свернуть' : 'Развернуть'}>
            {open ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
          </button>
        </Tip>
      </header>
      {open && (
        <div className="mt-2 grid gap-2">
          {nav === 'orbit' && <Stepper label="Скорость" hint="Шаг зума колесом и кнопками «+» и «−»" value={speeds.orbit} steps={SPEED_STEPS.orbit} onChange={(v) => onSpeeds({ ...speeds, orbit: v })} />}
          {nav === 'fly' && <Stepper label="Скорость" hint="Скорость перелёта клавишами и шаг колеса" value={speeds.fly} steps={SPEED_STEPS.fly} onChange={(v) => onSpeeds({ ...speeds, fly: v })} />}
          {nav === 'walk' && (
            <>
              <Stepper label="Скорость ходьбы" hint="Как быстро идёт камера от первого лица; Shift — быстрее" value={speeds.walk} steps={SPEED_STEPS.walk} onChange={(v) => onSpeeds({ ...speeds, walk: v })} />
              <Tip label="Высота камеры над полом на прогулке">
              <label className="grid gap-1">
                <span className="text-xs text-muted-foreground">Высота глаз <b className="text-foreground">{speeds.eye.toFixed(2).replace('.', ',')} м</b></span>
                <input type="range" className="accent-primary" min={1.0} max={2.0} step={0.05} value={speeds.eye} onChange={(e) => onSpeeds({ ...speeds, eye: Number(e.target.value) })} />
              </label>
              </Tip>
            </>
          )}
          <p className="m-0 text-[11px] leading-snug text-muted-foreground">{HINT[nav]}</p>
        </div>
      )}
    </section>
  )
}
