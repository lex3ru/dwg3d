import { useState } from 'react'
import { DEFAULT_SPEEDS, SPEED_STEPS, type NavMode, type Speeds } from '../state'
import { Icon } from './icons'

const TITLE: Record<NavMode, string> = { orbit: 'Обзор', fly: 'Полёт', walk: 'Прогулка' }
const HINT: Record<NavMode, string> = {
  orbit: 'Шаг зума колесом, кнопками «+» и «−» и щипком на трекпаде',
  fly: 'Перелёт клавишами WASD и стрелками, зум колесом и кнопками «+» и «−»',
  walk: 'WASD — идти, мышь — осматриваться, Shift — быстрее, Esc — выйти',
}
const fmt = (v: number) => `×${String(v).replace('.', ',')}`

function Stepper({ label, value, steps, onChange }: { label: string; value: number; steps: number[]; onChange: (v: number) => void }) {
  const i = Math.max(0, steps.findIndex((s) => s >= value - 1e-9))
  return (
    <div className="stepper">
      <span className="st-label">{label} <b>{fmt(value)}</b></span>
      <div className="st-row">
        <button onClick={() => onChange(steps[Math.max(0, i - 1)])} disabled={i === 0} aria-label="Медленнее"><Icon name="left" size={14} /></button>
        <input type="range" min={0} max={steps.length - 1} step={1} value={i} onChange={(e) => onChange(steps[Number(e.target.value)])} />
        <button onClick={() => onChange(steps[Math.min(steps.length - 1, i + 1)])} disabled={i === steps.length - 1} aria-label="Быстрее"><Icon name="right" size={14} /></button>
      </div>
    </div>
  )
}

/** Bottom-right panel of the current navigation mode: speed, hint, reset. */
export default function NavPanel({ nav, speeds, onSpeeds }: { nav: NavMode; speeds: Speeds; onSpeeds: (s: Speeds) => void }) {
  const [open, setOpen] = useState(true)
  const reset = () => onSpeeds(nav === 'walk'
    ? { ...speeds, walk: DEFAULT_SPEEDS.walk, eye: DEFAULT_SPEEDS.eye }
    : { ...speeds, [nav]: DEFAULT_SPEEDS[nav] })
  return (
    <section className={`nav-panel${open ? '' : ' collapsed'}`}>
      <header>
        <b>{TITLE[nav].toUpperCase()}</b>
        <button className="link" onClick={reset}>сброс</button>
        <button className="icon" onClick={() => setOpen(!open)} aria-label={open ? 'Свернуть' : 'Развернуть'}>
          <Icon name="chevron" size={14} className={open ? '' : 'flip'} />
        </button>
      </header>
      {open && (
        <>
          {nav === 'orbit' && <Stepper label="Скорость" value={speeds.orbit} steps={SPEED_STEPS.orbit} onChange={(v) => onSpeeds({ ...speeds, orbit: v })} />}
          {nav === 'fly' && <Stepper label="Скорость" value={speeds.fly} steps={SPEED_STEPS.fly} onChange={(v) => onSpeeds({ ...speeds, fly: v })} />}
          {nav === 'walk' && (
            <>
              <Stepper label="Скорость ходьбы" value={speeds.walk} steps={SPEED_STEPS.walk} onChange={(v) => onSpeeds({ ...speeds, walk: v })} />
              <label className="stepper">
                <span className="st-label">Высота глаз <b>{speeds.eye.toFixed(2).replace('.', ',')} м</b></span>
                <input type="range" min={1.0} max={2.0} step={0.05} value={speeds.eye} onChange={(e) => onSpeeds({ ...speeds, eye: Number(e.target.value) })} />
              </label>
            </>
          )}
          <p className="np-hint">{HINT[nav]}</p>
        </>
      )}
    </section>
  )
}
