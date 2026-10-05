import { useMemo } from 'react'
import type { FloorPlanData } from '../api'
import { cn } from '../lib/utils'

type Ring = [number, number][]
// plan Y goes up, the screen's goes down
const path = (polygons: Ring[][]) => polygons.map(rings => rings.map(
  ring => `M${ring.map(([x, y]) => `${x.toFixed(2)} ${(-y).toFixed(2)}`).join('L')}Z`).join('')).join('')

/**
 * The plan of a floor for reading, not for editing: walls, openings, rooms by name.
 * A room can be chosen; the chosen one is highlighted.
 */
export function FloorPlan({ plan, selected, onSelect, className }: {
  plan: FloorPlanData; selected?: string | null; onSelect?: (room: string) => void; className?: string
}) {
  const [x0, y0, x1, y1] = plan.bounds
  const pad = Math.max(x1 - x0, y1 - y0) * 0.03
  const view = `${x0 - pad} ${-y1 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`
  const walls = useMemo(() => path([...plan.walls, ...(plan.columns ?? [])]), [plan])
  const thin = useMemo(() => path(plan.partitions ?? []), [plan])
  const stairs = useMemo(() => path(plan.stairs ?? []), [plan])
  const font = Math.max(x1 - x0, y1 - y0) / 55
  return (
    <svg viewBox={view} className={cn('w-full rounded-lg border bg-card', className)} role="img" aria-label="План этажа" data-testid="plan">
      {plan.rooms.map((r, i) => (
        <path key={r.id ?? i} d={path([r.poly])} fillRule="evenodd" data-room={r.id ?? undefined} data-selected={r.id === selected || undefined}
          className={cn('stroke-transparent', r.id === selected ? 'fill-primary/25' : 'fill-secondary/60',
            onSelect && r.id && 'cursor-pointer hover:fill-primary/15')}
          onClick={() => r.id && onSelect?.(r.id)}>
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
    </svg>
  )
}
