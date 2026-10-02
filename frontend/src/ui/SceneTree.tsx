import {
  Building, ChevronDown, ChevronRight, DoorOpen, Download, ExternalLink, Eye, EyeOff, FileText, GitCompare, Layers as LayersIcon,
  Lock, LockOpen, MoreHorizontal, Pencil, PencilRuler, Plus, Search, Settings2,
} from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { listJobs, type FloorMeta, type JobSummary, type Layer, type LayerKindInfo, type Result, type RoomMeta } from '@/api'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Tip } from '@/components/ui/tooltip'
import { variantGroups } from '@/furniture/layers'
import { cn } from '@/lib/utils'
import { jobColor } from '@/state'

export interface TreeObject {
  id: string; name: string; sub: string; color?: string; floor: string; at: [number, number]; kind: 'item' | 'shape'
  layer: string
  /** the room it stands in (rooms keep their id across builds); null outside rooms or for routes across rooms */
  room: number | null
}

type GroupBy = 'layers' | 'rooms'
const GROUP_KEY = 'dwg3d.tree.group'
const readGroup = (): GroupBy => { try { return localStorage.getItem(GROUP_KEY) === 'rooms' ? 'rooms' : 'layers' } catch { return 'layers' } }

const row = 'flex w-full min-w-0 cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-sm text-foreground hover:bg-secondary'
const iconBtn = 'grid size-6 shrink-0 cursor-pointer place-items-center rounded border-0 bg-transparent p-0 text-muted-foreground hover:bg-border hover:text-foreground [&_svg]:size-3.5'

function Section({ title, icon: Icon, action, children, open, onOpen }: {
  title: string; icon: typeof Building; action?: ReactNode; children: ReactNode; open: boolean; onOpen: (v: boolean) => void
}) {
  return (
    <section className="mb-1">
      <div className="flex items-center gap-1 px-1">
        <button className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 border-0 bg-transparent px-1 py-1.5 text-left text-xs font-semibold tracking-wide text-muted-foreground uppercase hover:text-foreground"
          onClick={() => onOpen(!open)} aria-expanded={open}>
          {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          <Icon className="size-3.5" /> {title}
        </button>
        {action}
      </div>
      {open && children}
    </section>
  )
}

/**
 * The project in the left dock, one tree for everything on the plan:
 * the building (drawings, floors, rooms — the base, changed only through the
 * plan editor) and the layers on top of it (shown, locked, the one being edited).
 */
export default function SceneTree(p: {
  jobId: string
  projectId: string
  result: Result
  active: string | null
  selectedRoom: string | null
  drawingSelected: boolean
  onFloor: (id: string | null) => void
  onRoom: (f: FloorMeta, r: RoomMeta) => void
  onOpenJob: (id: string) => void
  onDrawing: () => void
  onPlan: (floorId: string) => void
  onExport: (fmt: 'dxf' | 'dwg') => void
  onFloorSettings: () => void
  // layers
  layers: Layer[]
  kinds: LayerKindInfo[]
  hidden: Set<string>
  editLayer: string | null
  editable: boolean
  onToggle: (id: string) => void
  onVariant: (id: string) => void
  onAll: (show: boolean) => void
  onLock: (l: Layer, patch: Partial<Layer>) => void
  onEdit: (id: string | null) => void
  onAddLayer: (kind: string) => void
  onCompare: () => void
  /** the objects of each layer on this drawing */
  objects: Map<string, TreeObject[]>
  selectedObject: string | null
  onObject: (layerId: string, o: TreeObject) => void
}) {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [openLayers, setOpenLayers] = useState<Set<string>>(new Set())
  const [openRooms, setOpenRooms] = useState<Set<string>>(new Set())
  const [group, setGroupState] = useState<GroupBy>(readGroup)
  const setGroup = (g: GroupBy) => { setGroupState(g); try { localStorage.setItem(GROUP_KEY, g) } catch { /* storage blocked */ } }
  // objects of the shown layers by floor and room ('-' outside rooms)
  const byRoom = useMemo(() => {
    const m = new Map<string, TreeObject[]>()
    for (const [layer, list] of p.objects) {
      if (p.hidden.has(layer)) continue
      for (const o of list) {
        const k = `${o.floor}|${o.room ?? '-'}`
        m.set(k, [...(m.get(k) ?? []), o])
      }
    }
    return m
  }, [p.objects, p.hidden])
  const toggleRoom = (k: string) => setOpenRooms((o) => { const n = new Set(o); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const objectRow = (o: TreeObject) => (
    <li key={o.id}>
      <button className={cn(row, 'py-0.5 text-xs', p.selectedObject === o.id && 'bg-accent font-medium text-accent-foreground')}
        title={p.editLayer === o.layer ? 'Выбрать' : 'Показать на плане'} onClick={() => p.onObject(o.layer, o)}>
        <i className={cn('size-2 shrink-0', o.kind === 'item' ? 'rounded-[2px]' : 'rounded-full')} style={{ background: o.color ?? '#adb5bd' }} />
        <span className="min-w-0 flex-1 truncate">{o.name}</span>
        <small className="max-w-24 shrink-0 truncate text-muted-foreground">{group === 'rooms' ? p.layers.find((l) => l.id === o.layer)?.name : o.sub}</small>
      </button>
    </li>
  )
  const toggleLayer = (id: string) => setOpenLayers((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const [sec, setSec] = useState({ building: true, layers: true })
  useEffect(() => {
    if (p.projectId) listJobs(p.projectId).then((j) => setJobs(j.filter((x) => x.status === 'done'))).catch(() => {})
  }, [p.projectId])
  const floors = useMemo(() => [...p.result.floors].sort((a, b) => b.elevation! - a.elevation!), [p.result])
  const types = useMemo(() => new Map((p.result.room_types ?? []).map((t) => [t.type, t])), [p.result])
  const s = q.trim().toLowerCase()
  const roomName = (r: RoomMeta) => r.name || types.get(r.type ?? '')?.label || 'Помещение'
  const match = (r: RoomMeta) => !s || roomName(r).toLowerCase().includes(s)
  const toggle = (id: string) => setOpen((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const groups = variantGroups(p.layers)
  const inVariants = (l: Layer) => groups.some((g) => g.some((x) => x.id === l.id))
  const kindName = (k: string) => p.kinds.find((x) => x.kind === k)?.name ?? k
  const allShown = p.layers.length > 0 && p.layers.every((l) => !p.hidden.has(l.id))
  const current = jobs.find((j) => j.id === p.jobId)
  const layersShown = !s || p.layers.some((l) => l.name.toLowerCase().includes(s))

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative shrink-0 border-b border-border p-2">
        <Search className="pointer-events-none absolute top-4 left-4 size-3.5 text-muted-foreground" />
        <div className="flex gap-1">
          <Input className="h-7 pl-7 text-xs" placeholder="Помещение, этаж или слой" value={q} onChange={(e) => setQ(e.target.value)} />
          <div role="group" aria-label="Объекты в дереве" className="flex shrink-0 rounded-md bg-secondary p-0.5">
            {([['layers', LayersIcon, 'Объекты — под своими слоями'], ['rooms', DoorOpen, 'Объекты — в помещениях, из всех показанных слоёв']] as const).map(([g, Icon, hint]) => (
              <Tip key={g} label={hint} side="bottom">
                <button aria-pressed={group === g} aria-label={hint} onClick={() => setGroup(g)}
                  className={cn('grid size-6 cursor-pointer place-items-center rounded border-0 p-0', group === g ? 'bg-card text-foreground shadow-sm' : 'bg-transparent text-muted-foreground hover:text-foreground')}>
                  <Icon className="size-3.5" />
                </button>
              </Tip>
            ))}
          </div>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-1.5">
        <Section title="Здание" icon={Building} open={sec.building} onOpen={(v) => setSec({ ...sec, building: v })}>
          {(jobs.length > 1 ? jobs : current ? [current] : []).filter(() => !s).map((j) => (
            <div key={j.id} className={cn('group flex items-center rounded-md hover:bg-secondary', j.id === p.jobId && p.drawingSelected && 'bg-accent')}>
              <button className={cn(row, 'hover:bg-transparent', j.id === p.jobId && 'font-medium')}
                onClick={() => (j.id === p.jobId ? p.onDrawing() : p.onOpenJob(j.id))}
                title={j.id === p.jobId ? 'Сводка чертежа: этажи, предупреждения, экспорт' : 'Открыть этот чертёж'}>
                <i className="size-2.5 shrink-0 rounded-full" style={{ background: jobColor(j.id) }} />
                <span className="min-w-0 flex-1 truncate">{j.name}</span>
                <small className="text-muted-foreground">{j.floors} эт.</small>
              </button>
              {j.id === p.jobId && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild><button className={cn(iconBtn, 'mr-1')} aria-label="Действия с чертежом"><MoreHorizontal /></button></DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-64">
                    <DropdownMenuItem onSelect={p.onDrawing}><FileText /> Сводка и предупреждения</DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => p.onExport('dxf')}><Download /> Сохранить DXF со слоями</DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => p.onExport('dwg')}><Download /> Сохранить DWG со слоями</DropdownMenuItem>
                    {p.editable && <DropdownMenuItem onSelect={p.onFloorSettings}><Settings2 /> Этажи и роли слоёв чертежа…</DropdownMenuItem>}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild><a href={`#/p/${p.projectId}/drawings`}><ExternalLink /> Чертежи проекта, новая ревизия</a></DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          ))}
          {!s && (
            <button className={cn(row, 'pl-5', p.active == null && 'bg-accent font-medium text-accent-foreground')} onClick={() => p.onFloor(null)}>
              <Building className="size-4 shrink-0" /> Всё здание
            </button>
          )}
          <ul className="m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-px p-0 pl-3">
            {floors.map((f) => {
              const rooms = f.rooms.filter(match)
              if (s && !rooms.length && !f.name.toLowerCase().includes(s)) return null
              const expanded = !!s || open.has(f.id) || p.active === f.id
              const isActive = p.active === f.id
              return (
                <li key={f.id}>
                  <div className={cn('group flex items-center rounded-md hover:bg-secondary', isActive && 'bg-accent')}>
                    <button aria-label={expanded ? 'Свернуть' : 'Развернуть'} className={cn(iconBtn, 'hover:bg-transparent')} onClick={() => toggle(f.id)}>
                      {expanded ? <ChevronDown /> : <ChevronRight />}
                    </button>
                    <button className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 border-0 bg-transparent py-1.5 pr-1 text-left text-sm text-foreground"
                      onClick={() => p.onFloor(f.id)}>
                      <span className="grid h-5 min-w-6 shrink-0 place-items-center rounded-full bg-secondary px-1 text-[11px] font-bold">{f.level}</span>
                      <span className={cn('min-w-0 flex-1 truncate', isActive && 'font-medium text-accent-foreground')}>{f.name}</span>
                      <small className="text-muted-foreground">{f.stats.rooms}</small>
                    </button>
                    {p.editable && (
                      <Tip label="Редактировать план этажа: стены, проёмы, помещения" side="right">
                        <button className={cn(iconBtn, 'mr-1 opacity-0 group-hover:opacity-100 focus-visible:opacity-100')} aria-label="Редактировать план этажа"
                          onClick={() => p.onPlan(f.id)}><PencilRuler /></button>
                      </Tip>
                    )}
                  </div>
                  {expanded && (
                    <ul className="m-0 mb-1 ml-6 grid list-none grid-cols-[minmax(0,1fr)] gap-px border-l border-border p-0 pl-1">
                      {rooms.map((r) => {
                        const k = `${f.id}|${r.id ?? '-'}`
                        const objs = group === 'rooms' && r.id != null ? byRoom.get(k) ?? [] : []
                        const roomOpen = openRooms.has(k) || objs.some((o) => o.id === p.selectedObject)
                        return (
                          <li key={r.node}>
                            <div className={cn('flex items-center rounded-md hover:bg-secondary', p.selectedRoom === r.node && 'bg-accent')}>
                              {group === 'rooms' && (
                                <button className={cn(iconBtn, 'hover:bg-transparent', !objs.length && 'invisible')} aria-label={roomOpen ? 'Свернуть' : 'Показать объекты'}
                                  onClick={() => toggleRoom(k)}>{roomOpen ? <ChevronDown /> : <ChevronRight />}</button>
                              )}
                              <button className={cn(row, 'py-1 text-xs hover:bg-transparent', p.selectedRoom === r.node && 'font-medium text-accent-foreground')}
                                onClick={() => p.onRoom(f, r)}>
                                <i className="size-2.5 shrink-0 rounded-[3px] border border-black/10" style={{ background: types.get(r.type ?? '')?.color ?? '#adb5bd' }} />
                                <span className="min-w-0 flex-1 truncate">{roomName(r)}</span>
                                {objs.length > 0 && <span className="rounded-full bg-secondary px-1.5 text-[10px] text-muted-foreground">{objs.length}</span>}
                                <small className="text-muted-foreground">{r.area.toFixed(0)} м²</small>
                              </button>
                            </div>
                            {roomOpen && objs.length > 0 && (
                              <ul className="m-0 mb-1 ml-5 grid list-none grid-cols-[minmax(0,1fr)] gap-px border-l border-border p-0 pl-1">{objs.map(objectRow)}</ul>
                            )}
                          </li>
                        )
                      })}
                      {!rooms.length && <li className="px-2 py-1 text-xs text-muted-foreground">Помещений нет</li>}
                      {group === 'rooms' && !s && (() => {
                        const k = `${f.id}|-`
                        const objs = byRoom.get(k) ?? []
                        if (!objs.length) return null
                        const roomOpen = openRooms.has(k)
                        return (
                          <li>
                            <div className="flex items-center rounded-md hover:bg-secondary">
                              <button className={cn(iconBtn, 'hover:bg-transparent')} aria-label={roomOpen ? 'Свернуть' : 'Показать объекты'} onClick={() => toggleRoom(k)}>
                                {roomOpen ? <ChevronDown /> : <ChevronRight />}</button>
                              <button className={cn(row, 'py-1 text-xs text-muted-foreground hover:bg-transparent')} onClick={() => toggleRoom(k)}>
                                <span className="min-w-0 flex-1 truncate">Вне помещений и между ними</span>
                                <span className="rounded-full bg-secondary px-1.5 text-[10px]">{objs.length}</span>
                              </button>
                            </div>
                            {roomOpen && <ul className="m-0 mb-1 ml-5 grid list-none grid-cols-[minmax(0,1fr)] gap-px border-l border-border p-0 pl-1">{objs.map(objectRow)}</ul>}
                          </li>
                        )
                      })()}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>
        </Section>

        {layersShown && (
          <Section title="Слои" icon={LayersIcon} open={sec.layers} onOpen={(v) => setSec({ ...sec, layers: v })}
            action={(
              <DropdownMenu>
                <DropdownMenuTrigger asChild><button className={iconBtn} aria-label="Слои: действия"><MoreHorizontal /></button></DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-60">
                  {p.layers.length > 1 && <DropdownMenuItem onSelect={() => p.onAll(!allShown)}>{allShown ? <EyeOff /> : <Eye />} {allShown ? 'Скрыть все' : 'Показать все'}</DropdownMenuItem>}
                  {groups.length > 0 && <DropdownMenuItem onSelect={p.onCompare}><GitCompare /> Сравнить варианты</DropdownMenuItem>}
                  {p.editable && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuLabel>Новый слой</DropdownMenuLabel>
                      {p.kinds.map((k) => <DropdownMenuItem key={k.kind} onSelect={() => p.onAddLayer(k.kind)}><Plus /> {k.name}</DropdownMenuItem>)}
                    </>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild><a href={`#/p/${p.projectId}/layers`}><Settings2 /> Слои проекта: имена, варианты</a></DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}>
            {!p.layers.length && (
              <p className="m-0 px-3 py-2 text-xs text-muted-foreground">
                Слоёв пока нет.{p.editable ? ' Создайте слой в меню «⋯» — мебель, камеры, маршруты, зоны, системы.' : ''}
              </p>
            )}
            <ul className="m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-px p-0">
              {p.layers.filter((l) => !s || l.name.toLowerCase().includes(s)).map((l) => {
                const off = p.hidden.has(l.id)
                const variant = inVariants(l)
                const editing = p.editLayer === l.id
                const objs = group === 'layers' ? p.objects.get(l.id) ?? [] : []
                const expanded = openLayers.has(l.id) || (editing && objs.some((o) => o.id === p.selectedObject))
                return (
                  <li key={l.id}>
                  <div className={cn('flex items-center gap-0.5 rounded-md pr-1 hover:bg-secondary', editing && 'bg-accent ring-1 ring-primary/40')}>
                    <button className={cn(iconBtn, 'hover:bg-transparent', !objs.length && 'invisible')} aria-label={expanded ? 'Свернуть' : 'Показать объекты'}
                      onClick={() => toggleLayer(l.id)}>{expanded ? <ChevronDown /> : <ChevronRight />}</button>
                    <Tip label={off ? (variant ? 'Показать этот вариант (остальные скроются)' : 'Показать слой') : 'Скрыть слой'} side="right">
                      <button className={iconBtn} aria-pressed={!off} aria-label={off ? 'Показать слой' : 'Скрыть слой'}
                        onClick={() => (variant && off ? p.onVariant(l.id) : p.onToggle(l.id))}>
                        {off ? <EyeOff /> : <Eye className="text-foreground" />}
                      </button>
                    </Tip>
                    <div className="min-w-0 flex-1 py-1 leading-tight">
                      <div className={cn('truncate text-sm', off && 'text-muted-foreground', editing && 'font-medium text-accent-foreground')}>{l.name}</div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {kindName(l.kind)}{l.count != null ? ` · ${l.count}` : ''}{variant ? ' · вариант' : ''}
                      </div>
                    </div>
                    {p.editable ? (
                      <>
                        <Tip label={l.locked ? 'Слой заблокирован — разблокировать' : 'Заблокировать: слой нельзя менять'} side="right">
                          <button className={cn(iconBtn, l.locked && 'text-foreground')} aria-pressed={l.locked} aria-label="Блокировка"
                            onClick={() => p.onLock(l, { locked: !l.locked })}>{l.locked ? <Lock /> : <LockOpen />}</button>
                        </Tip>
                        <Tip label={editing ? 'Закончить редактирование' : l.locked ? 'Слой заблокирован' : 'Редактировать слой: инструменты появятся сверху'} side="right">
                          <button className={cn(iconBtn, editing && 'bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground')}
                            aria-pressed={editing} aria-label="Редактировать слой" disabled={l.locked && !editing}
                            onClick={() => p.onEdit(editing ? null : l.id)}><Pencil /></button>
                        </Tip>
                      </>
                    ) : l.locked && <Lock className="mx-1.5 size-3.5 text-muted-foreground" />}
                  </div>
                  {expanded && objs.length > 0 && (
                    <ul className="m-0 mb-1 ml-6 grid list-none grid-cols-[minmax(0,1fr)] gap-px border-l border-border p-0 pl-1">
                      {objs.slice(0, 300).map(objectRow)}
                      {objs.length > 300 && <li className="px-2 py-1 text-xs text-muted-foreground">…и ещё {objs.length - 300}</li>}
                    </ul>
                  )}
                  </li>
                )
              })}
            </ul>
          </Section>
        )}
      </div>
      <a href={`#/p/${p.projectId}`} className="flex shrink-0 items-center gap-1.5 border-t border-border px-3 py-1.5 text-xs text-muted-foreground no-underline hover:text-foreground">
        <ExternalLink className="size-3.5" /> Проект: чертежи, слои, участники
      </a>
    </div>
  )
}

