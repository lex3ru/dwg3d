import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { CATEGORIES, type CatalogItem } from '@/scene/furniture/catalog'

export const catColor = (id: string) => CATEGORIES.find((c) => c.id === id)?.color ?? '#868e96'
export const cm = (m: number) => Math.round(m * 100)

/** Top view of an item: its footprint with the front edge marked. */
export function ItemSymbol({ c, size = 36 }: { c: CatalogItem; size?: number }) {
  const k = 30 / Math.max(c.w, c.d, 0.3)
  const w = Math.max(4, c.w * k), d = Math.max(4, c.d * k)
  const x = (36 - w) / 2, y = (36 - d) / 2
  const col = catColor(c.cat)
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden className="shrink-0">
      {c.kind === 'zone' || ['plant', 'bin', 'stool', 'extinguisher', 'iv'].includes(c.kind)
        ? <ellipse cx="18" cy="18" rx={w / 2} ry={d / 2} fill={`${col}22`} stroke={col} strokeWidth="1.5" />
        : <rect x={x} y={y} width={w} height={d} rx="1.5" fill={`${col}22`} stroke={col} strokeWidth="1.5" />}
      <line x1={x + 1} x2={x + w - 1} y1={y + d} y2={y + d} stroke={col} strokeWidth="3" />
    </svg>
  )
}

/** A number typed in and applied on Enter or leaving the field (an invalid one is dropped). */
export function NumField({ label, value, onChange, min = 1, max = 5000 }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number
}) {
  const [text, setText] = useState<string | null>(null)
  const commit = () => {
    if (text == null) return
    const v = Number(text.replace(',', '.'))
    if (Number.isFinite(v) && v >= min && v <= max) onChange(v)
    setText(null)
  }
  return (
    <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">{label}
      <Input className="h-7 text-sm" inputMode="decimal" value={text ?? String(value)} onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => {
          e.stopPropagation()
          if (e.key === 'Enter') { commit(); (e.target as HTMLInputElement).blur() } else if (e.key === 'Escape') setText(null)
        }} />
    </label>
  )
}
