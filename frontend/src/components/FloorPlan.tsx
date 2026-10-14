import { useMemo } from 'react'
import type { FloorPlanData } from '../api'
import { cn } from '../lib/utils'
import { glyph } from './glyphs'

type Ring = [number, number][]
// plan Y goes up, the screen's goes down
const path = (polygons: Ring[][]) => polygons.map(rings => rings.map(
  ring => `M${ring.map(([x, y]) => `${x.toFixed(2)} ${(-y).toFixed(2)}`).join('L')}Z`).join('')).join('')

/**
 * The plan of a floor for reading, not for editing: walls, openings, rooms by name.
 * A room can be chosen; the chosen one is highlighted.
 */
export type Dot = { id: string; x: number; y: number; title: string; tone: 'ok' | 'bad' | 'warn' | 'note'; chosen?: boolean }
/** an object standing on the floor, drawn from above to its size, turned as it stands: its type's shape names the symbol */
export type Item = {
  id: string; x: number; y: number; title: string; tone: Dot['tone']; chosen?: boolean
  /** degrees counter-clockwise; at 0 the back is towards +Y */
  angle: number
  /** width and depth, m */
  w: number; d: number
  /** the catalog type's shape (a box when unknown) */
  shape: string
}
/** a change someone proposes: a new object, one moved from somewhere, one to write off */
export type Mark = { kind: 'new' | 'move' | 'remove'; x: number; y: number; title: string; from?: { x: number; y: number } | null }

const TONE = { ok: 'text-primary', warn: 'text-warning', bad: 'text-destructive', note: 'text-muted-foreground' } as const

export function FloorPlan({ plan, selected, onSelect, dots, items, onDot, marks, onPoint, className }: {
  plan: FloorPlanData; selected?: string | null; onSelect?: (room: string) => void; className?: string
  /** points of interest: comments, places just marked */
  dots?: Dot[]; onDot?: (id: string) => void
  /** objects standing on the floor: their shapes, to size, turned as they stand */
  items?: Item[]
  /** proposed changes drawn over the objects: green — new, blue — moved (with a line from where it stands), red — written off */
  marks?: Mark[]
  /** when given, a click anywhere on the plan picks a point (plan coordinates, m) instead of a room */
  onPoint?: (x: number, y: number) => void
}) {
  const [x0, y0, x1, y1] = plan.bounds
  const pad = Math.max(x1 - x0, y1 - y0) * 0.03
  const view = `${x0 - pad} ${-y1 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`
  const walls = useMemo(() => path([...plan.walls, ...(plan.columns ?? [])]), [plan])
  const thin = useMemo(() => path(plan.partitions ?? []), [plan])
  const stairs = useMemo(() => path(plan.stairs ?? []), [plan])
  const font = Math.max(x1 - x0, y1 - y0) / 55
  return (
    <svg viewBox={view} className={cn('w-full rounded-lg border bg-card', onPoint && 'cursor-crosshair', className)} role="img" aria-label="План этажа" data-testid="plan"
      onClick={onPoint && (e => {
        const svg = e.currentTarget
        const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM()!.inverse())
        onPoint(Number(p.x.toFixed(3)), Number((-p.y).toFixed(3)))
      })}>
      {plan.rooms.map((r, i) => (
        <path key={r.id ?? i} d={path([r.poly])} fillRule="evenodd" data-room={r.id ?? undefined} data-selected={r.id === selected || undefined}
          className={cn('stroke-transparent', r.id === selected ? 'fill-primary/25' : 'fill-secondary/60',
            onSelect && !onPoint && r.id && 'cursor-pointer hover:fill-primary/15')}
          onClick={() => !onPoint && r.id && onSelect?.(r.id)}>
          <title>{r.name || 'Помещение'} · {r.area} м²</title>
        </path>
      ))}
      <path d={stairs} fillRule="evenodd" className="fill-warning/25" />
      <path d={thin} fillRule="evenodd" className="fill-muted-foreground/60" />
      <path d={walls} fillRule="evenodd" className="fill-foreground/75" />
      {plan.openings.map((o, i) => (
        <path key={i} d={path([o.poly])} fillRule="evenodd"
          className={o.kind === 'door' || o.kind === 'passage' ? 'fill-card' : 'fill-primary/50'} />
      ))}
      {plan.rooms.filter(r => r.name && r.area >= 6).map((r, i) => (
        <text key={i} x={r.label[0]} y={-r.label[1]} fontSize={font} textAnchor="middle" dominantBaseline="middle"
          className={cn('pointer-events-none fill-muted-foreground', r.id === selected && 'fill-foreground font-medium')}>
          {r.name.length > 22 ? `${r.name.slice(0, 20)}…` : r.name}
        </text>
      ))}
      {items?.map(it => {
        // a small thing (a socket, a detector) is drawn no smaller than a dot would be, keeping its proportions
        const s = Math.max(1, (font * 0.9) / Math.max(it.w, it.d, 0.01))
        const hw = (it.w * s) / 2, hd = (it.d * s) / 2, k = font * (it.chosen ? 0.12 : 0.06)
        return (
          <g key={it.id} transform={`translate(${it.x} ${-it.y}) rotate(${-it.angle})`} data-asset={it.id} data-shape={it.shape}
            className={cn(TONE[it.tone], onDot && !onPoint && 'cursor-pointer')}
            fill="currentColor" fillOpacity={it.chosen ? 0.5 : 0.22} stroke="currentColor" strokeWidth={k} strokeLinejoin="round" strokeLinecap="round"
            onClick={e => { if (!onPoint) { e.stopPropagation(); onDot?.(it.id) } }}>
            <title>{it.title}</title>
            {glyph(it.shape, hw, hd, k)}
          </g>
        )
      })}
      {dots?.map(d => (
        <circle key={d.id} cx={d.x} cy={-d.y} r={font * (d.chosen ? 0.85 : 0.6)} data-asset={d.id}
          className={cn('stroke-card', d.tone === 'bad' ? 'fill-destructive' : d.tone === 'warn' ? 'fill-warning' : d.tone === 'note' ? 'fill-muted-foreground' : 'fill-primary',
            onDot && !onPoint && 'cursor-pointer')}
          strokeWidth={font * 0.12} onClick={e => { if (!onPoint) { e.stopPropagation(); onDot?.(d.id) } }}>
          <title>{d.title}</title>
        </circle>
      ))}
      {marks?.map((m, i) => (
        <g key={`mark-${i}`} data-testid="plan-mark" data-kind={m.kind} className="pointer-events-none">
          {m.from && <line x1={m.from.x} y1={-m.from.y} x2={m.x} y2={-m.y} strokeWidth={font * 0.1} strokeDasharray={`${font * 0.3} ${font * 0.2}`} className="stroke-sky-500" />}
          <circle cx={m.x} cy={-m.y} r={font * 0.9} strokeWidth={font * 0.18} fill="none"
            className={m.kind === 'new' ? 'stroke-emerald-500' : m.kind === 'remove' ? 'stroke-destructive' : 'stroke-sky-500'}>
            <title>{m.kind === 'new' ? 'поставить: ' : m.kind === 'remove' ? 'списать: ' : 'переставить: '}{m.title}</title>
          </circle>
          {m.kind === 'remove' && <path d={`M${m.x - font * 0.5} ${-m.y - font * 0.5}L${m.x + font * 0.5} ${-m.y + font * 0.5}M${m.x - font * 0.5} ${-m.y + font * 0.5}L${m.x + font * 0.5} ${-m.y - font * 0.5}`}
            strokeWidth={font * 0.15} className="stroke-destructive" />}
        </g>
      ))}
    </svg>
  )
}
