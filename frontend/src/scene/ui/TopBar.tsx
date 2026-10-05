import { ChevronDown, FolderOpen, Home, LogOut, Search, Upload } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { listJobs, type FloorMeta, type JobSummary, type Result, type RoomMeta } from '@/scene/api'
import { floatClass } from '@/components/ui/float'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { canEdit, me, signOut } from '../session'
import { jobColor } from '../state'

/**
 * Top centre: the current drawing (menu: project, its drawings) and a search
 * over rooms and drawings. On a narrow scene it moves to a row of its own.
 */
export default function TopBar({ jobId, projectId, name, result, onOpenJob, onRoom }: {
  jobId: string
  projectId: string
  name: string
  result: Result | undefined
  onOpenJob: (id: string) => void
  onRoom: (f: FloorMeta, r: RoomMeta) => void
}) {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [q, setQ] = useState('')
  const [focus, setFocus] = useState(false)
  const [cur, setCur] = useState(0)
  const [menu, setMenu] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (!menu && !focus) return
    listJobs(projectId).then((j) => setJobs(j.filter((x) => x.status === 'done'))).catch(() => {})
  }, [menu, focus, projectId])

  const typeLabel = useMemo(() => new Map((result?.room_types ?? []).map((t) => [t.type, t.label])), [result])
  const hits = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return []
    const rooms = (result?.floors ?? []).flatMap((f) => f.rooms
      .filter((r) => (r.name || '').toLowerCase().includes(s) || (typeLabel.get(r.type ?? '') ?? '').toLowerCase().includes(s))
      .map((r) => ({ kind: 'room' as const, f, r }))).slice(0, 30)
    const buildings = jobs.filter((j) => j.id !== jobId && (j.name + ' ' + j.filename).toLowerCase().includes(s)).slice(0, 8)
      .map((j) => ({ kind: 'job' as const, j }))
    return [...rooms, ...buildings]
  }, [q, result, jobs, jobId, typeLabel])
  const open = focus && hits.length > 0
  const choose = (h: (typeof hits)[number]) => {
    setQ('')
    setFocus(false)
    input.current?.blur()
    if (h.kind === 'room') onRoom(h.f, h.r)
    else onOpenJob(h.j.id)
  }
  const onKey = (e: React.KeyboardEvent) => {
    e.stopPropagation()          // typing here is not a scene shortcut
    if (e.key === 'ArrowDown') { e.preventDefault(); setCur((c) => Math.min(hits.length - 1, c + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCur((c) => Math.max(0, c - 1)) }
    else if (e.key === 'Enter' && hits[cur]) choose(hits[cur])
    else if (e.key === 'Escape') { setQ(''); input.current?.blur() }
  }
  const rooms = hits.filter((h) => h.kind === 'room')

  return (
    <div className={cn(floatClass, 'absolute z-20 flex items-center gap-1 rounded-full p-1',
      'top-14 right-3 left-3 @3xl:top-3 @3xl:right-80 @3xl:left-14 @3xl:mx-auto @3xl:max-w-lg @5xl:right-[26rem]')}>
      <DropdownMenu open={menu} onOpenChange={setMenu}>
        <DropdownMenuTrigger asChild>
          <button title="Проект и его чертежи"
            className="flex max-w-[45%] min-w-0 shrink-0 cursor-pointer items-center gap-2 rounded-full border-0 bg-secondary px-3 py-1.5 text-sm font-semibold text-foreground hover:bg-border">
            <i className="size-2.5 shrink-0 rounded-full" style={{ background: jobColor(jobId) }} />
            <span className="truncate">{name}</span>
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          <DropdownMenuItem asChild><a href={`#/p/${projectId}`}><FolderOpen /> Здание: чертежи и этажи</a></DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Чертежи здания</DropdownMenuLabel>
          {jobs.map((j) => (
            <DropdownMenuItem key={j.id} className={j.id === jobId ? 'bg-accent text-accent-foreground' : ''} onSelect={() => onOpenJob(j.id)}>
              <i className="size-2.5 shrink-0 rounded-full" style={{ background: jobColor(j.id) }} />
              <span className="min-w-0 flex-1 truncate">{j.name}</span>
              <small className="text-muted-foreground">{j.floors} эт.</small>
            </DropdownMenuItem>
          ))}
          {canEdit() && <DropdownMenuItem asChild><a href={`#/p/${projectId}`}><Upload /> Загрузить чертёж в проект…</a></DropdownMenuItem>}
          <DropdownMenuSeparator />
          <DropdownMenuItem asChild><a href="#/"><Home /> Все проекты</a></DropdownMenuItem>
          {me?.auth && !me.guest && (
            <>
              <DropdownMenuLabel className="grid"><span className="text-foreground">{me.name}</span><span>{me.login} · {me.role_name}</span></DropdownMenuLabel>
              <DropdownMenuItem onSelect={signOut}><LogOut /> Выйти</DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <div className="relative min-w-0 flex-1">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <input ref={input} value={q} placeholder="Поиск помещения или здания" role="combobox" aria-expanded={open} aria-controls="topbar-hits"
          className="h-9 w-full min-w-0 rounded-full border-0 bg-transparent py-0 pr-3 pl-9 text-sm text-foreground outline-none placeholder:text-muted-foreground"
          onFocus={() => setFocus(true)} onBlur={() => setFocus(false)} onKeyDown={onKey}
          onChange={(e) => { setQ(e.target.value); setCur(0) }} />
        {open && (
          <ul id="topbar-hits" role="listbox"
            className="absolute top-[calc(100%+0.75rem)] right-0 left-0 m-0 max-h-80 min-w-72 list-none overflow-y-auto rounded-xl border border-border bg-popover p-1 text-popover-foreground shadow-lg">
            {rooms.length > 0 && <li className="px-2 pt-1.5 pb-0.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Помещения</li>}
            {hits.map((h, i) => (
              <li key={h.kind === 'room' ? h.r.node : h.j.id} role="option" aria-selected={i === cur}
                className={cn('flex cursor-pointer flex-col rounded-lg px-2 py-1.5 text-sm', i === cur && 'bg-secondary')}
                onMouseDown={(e) => { e.preventDefault(); choose(h) }} onMouseEnter={() => setCur(i)}>
                {h.kind === 'room' ? (
                  <>
                    <b>{h.r.name || typeLabel.get(h.r.type ?? '') || 'Помещение'}</b>
                    <span className="text-xs text-muted-foreground">{h.f.name} · {h.r.area.toFixed(1)} м²</span>
                  </>
                ) : (
                  <>
                    <b className="flex items-center gap-1.5"><i className="size-2.5 rounded-full" style={{ background: jobColor(h.j.id) }} /> {h.j.name}</b>
                    <span className="text-xs text-muted-foreground">здание · {h.j.floors} этажей</span>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
