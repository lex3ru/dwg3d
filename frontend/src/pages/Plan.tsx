import { useEffect, useState } from 'react'
import { getFloorPlan, type FloorPlanData, type TreeFloor } from '../api'
import { FloorPlan } from '../components/FloorPlan'
import { cn } from '../lib/utils'
import { to } from '../shell/route'

/** The 2D plan of a floor: pick a floor, pick a room. */
export function Plan({ building, floors, floor, room }: { building: string; floors: TreeFloor[]; floor?: string; room?: string }) {
  // the ground floor first, when there is one
  const fallback = floors.find(f => f.level === 1) ?? floors[0]
  const active = floors.find(f => f.id === floor) ?? fallback
  const [plan, setPlan] = useState<{ floor: string; data: FloorPlanData } | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!active) return
    let stale = false
    getFloorPlan(active.id).then(data => { if (!stale) { setPlan({ floor: active.id, data }); setError(null) } },
      (e: Error) => { if (!stale) setError(e.message) })
    return () => { stale = true }
  }, [active])
  if (!active) return <p className="text-sm text-muted-foreground">В здании пока нет этажей.</p>
  const chosen = active.rooms.find(r => r.id === room)
  return (
    <section>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">План</h1>
        <nav className="flex flex-wrap gap-1" aria-label="Этажи" data-testid="floor-tabs">
          {[...floors].reverse().map(f => (
            <a key={f.id} href={to.plan(building, f.id)} title={f.name} aria-current={f.id === active.id ? 'true' : undefined}
              className={cn('min-w-8 rounded-md border px-2 py-1 text-center text-sm hover:bg-secondary',
                f.id === active.id && 'border-primary bg-primary text-primary-foreground hover:bg-primary')}>
              {f.level ?? '?'}
            </a>
          ))}
        </nav>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{active.name} · помещений: {active.rooms.length}</p>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {plan?.floor === active.id && (
        <FloorPlan plan={plan.data} selected={room} className="mt-3 max-h-[70vh]"
          onSelect={id => { location.hash = to.plan(building, active.id, id) }} />
      )}
      {/* on a phone the card is a page of its own; here: what is chosen, one tap from its card */}
      {chosen && (
        <a href={to.rooms(building, chosen.id)} className="mt-2 flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm md:hidden">
          <span className="flex-1 font-medium">{chosen.name || 'Помещение без названия'}</span>
          <span className="text-muted-foreground">{chosen.area.toLocaleString('ru')} м²</span>
        </a>
      )}
    </section>
  )
}
