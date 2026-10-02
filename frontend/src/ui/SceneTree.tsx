import { Building, ChevronDown, ChevronRight, ExternalLink, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { listJobs, type FloorMeta, type JobSummary, type Result, type RoomMeta } from '@/api'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { jobColor } from '@/state'

/**
 * The left dock's tree of the project: its drawings, and for the open one the
 * floors with their rooms. Choosing a floor or a room moves the scene there.
 */
export default function SceneTree(p: {
  jobId: string
  projectId: string
  result: Result
  active: string | null
  selectedRoom: string | null
  onFloor: (id: string | null) => void
  onRoom: (f: FloorMeta, r: RoomMeta) => void
  onOpenJob: (id: string) => void
}) {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<Set<string>>(new Set())
  useEffect(() => {
    if (p.projectId) listJobs(p.projectId).then((j) => setJobs(j.filter((x) => x.status === 'done'))).catch(() => {})
  }, [p.projectId])
  const floors = useMemo(() => [...p.result.floors].sort((a, b) => b.elevation! - a.elevation!), [p.result])
  const types = useMemo(() => new Map((p.result.room_types ?? []).map((t) => [t.type, t])), [p.result])
  const s = q.trim().toLowerCase()
  const roomName = (r: RoomMeta) => r.name || types.get(r.type ?? '')?.label || 'Помещение'
  const match = (r: RoomMeta) => !s || roomName(r).toLowerCase().includes(s)
  const toggle = (id: string) => setOpen((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n })
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative shrink-0 border-b border-border p-2">
        <Search className="pointer-events-none absolute top-4 left-4 size-3.5 text-muted-foreground" />
        <Input className="h-7 pl-7 text-xs" placeholder="Помещение или этаж" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5 text-sm">
        {jobs.length > 1 && !s && (
          <section className="mb-2">
            <h3 className="m-0 px-2 py-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Чертежи проекта</h3>
            <ul className="m-0 grid list-none gap-0.5 p-0">
              {jobs.map((j) => (
                <li key={j.id}>
                  <button className={cn('flex w-full cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-sm text-foreground hover:bg-secondary', j.id === p.jobId && 'bg-accent font-medium text-accent-foreground')}
                    onClick={() => j.id !== p.jobId && p.onOpenJob(j.id)}>
                    <i className="size-2.5 shrink-0 rounded-full" style={{ background: jobColor(j.id) }} />
                    <span className="min-w-0 flex-1 truncate">{j.name}</span>
                    <small className="text-muted-foreground">{j.floors} эт.</small>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        <section>
          <h3 className="m-0 px-2 py-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Этажи и помещения</h3>
          {!s && (
            <button className={cn('flex w-full cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-sm text-foreground hover:bg-secondary', p.active == null && 'bg-accent font-medium text-accent-foreground')}
              onClick={() => p.onFloor(null)}>
              <Building className="size-4 shrink-0" /> Всё здание
            </button>
          )}
          <ul className="m-0 grid list-none gap-0.5 p-0">
            {floors.map((f) => {
              const rooms = f.rooms.filter(match)
              if (s && !rooms.length && !f.name.toLowerCase().includes(s)) return null
              const expanded = !!s || open.has(f.id) || p.active === f.id
              const isActive = p.active === f.id
              return (
                <li key={f.id}>
                  <div className={cn('flex items-center rounded-md hover:bg-secondary', isActive && 'bg-accent')}>
                    <button aria-label={expanded ? 'Свернуть' : 'Развернуть'} className="grid size-6 shrink-0 cursor-pointer place-items-center border-0 bg-transparent p-0 text-muted-foreground"
                      onClick={() => toggle(f.id)}>
                      {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                    </button>
                    <button className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 border-0 bg-transparent py-1.5 pr-2 text-left text-sm text-foreground"
                      onClick={() => p.onFloor(f.id)}>
                      <span className="grid h-5 min-w-6 shrink-0 place-items-center rounded-full bg-secondary px-1 text-[11px] font-bold">{f.level}</span>
                      <span className={cn('min-w-0 flex-1 truncate', isActive && 'font-medium text-accent-foreground')}>{f.name}</span>
                      <small className="text-muted-foreground">{f.stats.rooms}</small>
                    </button>
                  </div>
                  {expanded && (
                    <ul className="m-0 mb-1 ml-6 grid list-none gap-px border-l border-border p-0 pl-1">
                      {rooms.map((r) => (
                        <li key={r.node}>
                          <button className={cn('flex w-full cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1 text-left text-xs text-foreground hover:bg-secondary', p.selectedRoom === r.node && 'bg-accent font-medium text-accent-foreground')}
                            onClick={() => p.onRoom(f, r)}>
                            <i className="size-2.5 shrink-0 rounded-[3px] border border-black/10" style={{ background: types.get(r.type ?? '')?.color ?? '#adb5bd' }} />
                            <span className="min-w-0 flex-1 truncate">{roomName(r)}</span>
                            <small className="text-muted-foreground">{r.area.toFixed(0)} м²</small>
                          </button>
                        </li>
                      ))}
                      {!rooms.length && <li className="px-2 py-1 text-xs text-muted-foreground">Помещений нет</li>}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      </div>
      <a href={`#/p/${p.projectId}`} className="flex shrink-0 items-center gap-1.5 border-t border-border px-3 py-1.5 text-xs text-muted-foreground no-underline hover:text-foreground">
        <ExternalLink className="size-3.5" /> Проект: чертежи, слои, участники
      </a>
    </div>
  )
}
