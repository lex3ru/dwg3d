import { LATER } from '../compat'
import {
  Armchair, Building, Cable, Cctv, ChevronDown, ChevronRight, ChevronsUpDown, Download, ExternalLink, Eye, EyeOff, FileText, Flame,
  GitCompare, KeyRound, Layers as LayersIcon, Lightbulb, Lock, LockOpen, MoreHorizontal, Pencil, PencilRuler, Plug, Plus, Route, Search,
  Settings2, SquareDashed, Wifi, type LucideIcon,
} from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { listJobs, type FloorMeta, type JobSummary, type Layer, type LayerKindInfo, type Result, type RoomMeta } from '@/scene/api'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Tip } from '@/components/ui/tooltip'
import { CATEGORIES } from '@/scene/furniture/catalog'
import { variantGroup, variantGroups } from '@/scene/furniture/layers'
import { cn } from '@/lib/utils'
import { jobColor } from '@/scene/state'

export interface TreeObject {
  id: string; name: string; sub: string; color?: string; floor: string; at: [number, number]; kind: 'item' | 'shape'
  layer: string
  /** the room it stands in (rooms keep their id across builds); null outside rooms or for routes across rooms */
  room: number | null
}

/** How a kind of layer looks in the legend: its icon and the short word that fits a chip (the full name is the hint). */
const LOOK: Record<string, { icon: LucideIcon; short: string }> = {
  furniture: { icon: Armchair, short: 'Мебель' },
  cctv: { icon: Cctv, short: 'Камеры' },
  lighting: { icon: Lightbulb, short: 'Свет' },
  wifi: { icon: Wifi, short: 'Wi-Fi' },
  fire: { icon: Flame, short: 'Сигнализация' },
  access: { icon: KeyRound, short: 'СКУД' },
  network: { icon: Plug, short: 'СКС' },
  routes: { icon: Route, short: 'Маршруты' },
  zones: { icon: SquareDashed, short: 'Зоны' },
  cables: { icon: Cable, short: 'Кабели' },
}
const VARIANT = 'variant:'
/** the variant a layer belongs to, or null for the fact */
const variantOf = (l: Layer) => (l.id.startsWith(VARIANT) ? l.id.slice(VARIANT.length).split('.')[0] : null)

const row = 'flex w-full min-w-0 cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-sm text-foreground hover:bg-secondary'
const iconBtn = 'grid size-6 shrink-0 cursor-pointer place-items-center rounded border-0 bg-transparent p-0 text-muted-foreground hover:bg-border hover:text-foreground [&_svg]:size-3.5'

function Heading({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex h-7 items-center gap-1 px-2">
      <span className="min-w-0 flex-1 truncate text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{children}</span>
      {action}
    </div>
  )
}

/**
 * The project in the left dock: the drawing on screen, the legend of what is
 * on the plan — the layers as chips with the variant shown — and the rooms of
 * the floors with the objects standing in them. The floors themselves are
 * chosen on the rail beside the plan; here they head the lists of rooms.
 */
export default function ProjectPanel(p: {
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
  /** show this variant (null — the fact) in every layer of objects at once */
  onPickVariant: (vid: string | null) => void
  onAll: (show: boolean) => void
  /** lock a layer against editing on this viewer's screen (kept in the browser) */
  onLock: (l: Layer, locked: boolean) => void
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
  const [openRooms, setOpenRooms] = useState<Set<string>>(new Set())
  const [openFloors, setOpenFloors] = useState<Set<string>>(new Set())
  useEffect(() => {
    if (p.projectId) listJobs(p.projectId).then((j) => setJobs(j.filter((x) => x.status === 'done'))).catch(() => {})
  }, [p.projectId])
  const current = jobs.find((j) => j.id === p.jobId)
  const floors = useMemo(() => [...p.result.floors].sort((a, b) => b.elevation! - a.elevation!), [p.result])
  const types = useMemo(() => new Map((p.result.room_types ?? []).map((t) => [t.type, t])), [p.result])
  const s = q.trim().toLowerCase()
  const roomName = (r: RoomMeta) => r.name || types.get(r.type ?? '')?.label || 'Помещение'

  // ---- the legend: one chip per layer of objects; of a group of variants the one on screen
  const groups = variantGroups(p.layers)
  const shown = p.layers.filter((l) => !groups.some((g) => g.some((x) => x.id === l.id)) || !p.hidden.has(l.id))
  // the variants there are, by id, named as their layers are; the one shown by the first group
  const variants = useMemo(() => {
    const m = new Map<string, string>()
    for (const l of p.layers) { const v = variantOf(l); if (v && !m.has(v)) m.set(v, l.name) }
    return [...m]
  }, [p.layers])
  const shownVariant = (() => { const l = shown.find((x) => variantOf(x)); return l ? variantOf(l) : null })()
  const allShown = shown.length > 0 && shown.every((l) => !p.hidden.has(l.id))
  const kindOf = (l: Layer) => p.kinds.find((k) => k.kind === l.kind)
  const colorOf = (l: Layer) => {
    const cat = kindOf(l)?.categories?.[0]
    return (cat && CATEGORIES.find((c) => c.id === cat)?.color) || '#868e96'
  }
  // objects on the plan: of the active floor when there is one, else of the whole drawing
  const onPlan = (l: Layer) => (p.objects.get(l.id) ?? []).filter((o) => !p.active || o.floor === p.active)
  const chip = (l: Layer) => {
    const kind = kindOf(l)
    const look = LOOK[l.kind] ?? { icon: LayersIcon, short: kind?.name ?? l.kind }
    const Icon = look.icon
    const name = kind?.name ?? l.name
    const off = p.hidden.has(l.id)
    const editing = p.editLayer === l.id
    const ofVariant = variantGroup(l) !== l.id
    const color = colorOf(l)
    const n = onPlan(l).length
    return (
      <li key={l.id} aria-label={name} className={cn('group relative flex h-9 min-w-0 items-center rounded-md border border-border bg-card pr-0.5',
        off && 'border-dashed bg-transparent', editing && 'border-primary ring-1 ring-primary/40')}>
        <Tip label={off ? `Вернуть на план: ${name}${ofVariant ? ` (вариант «${l.name}»)` : ''}; только на вашем экране`
          : `Убрать с плана: ${name}${ofVariant ? ` (вариант «${l.name}»)` : ''}; только на вашем экране, запоминается в браузере`} side="bottom">
          <button aria-pressed={!off} aria-label={`${off ? 'Показать' : 'Скрыть'} слой ${name}`}
            className={cn('flex h-full min-w-0 flex-1 cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent pl-2 text-left', off && 'text-muted-foreground')}
            onClick={() => p.onToggle(l.id)}>
            <Icon className="size-4 shrink-0" style={{ color: off ? undefined : color }} />
            {/* the short word in two columns (a wide dock), the full name in one */}
            <span className={cn('min-w-0 flex-1 truncate text-sm', editing && 'font-medium')}>
              <span className="@[300px]:hidden">{name}</span><span className="hidden @[300px]:inline">{look.short}</span>
            </span>
            <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{n || ''}</span>
          </button>
        </Tip>
        {p.editable ? (
          <>
            <Tip label={l.locked ? 'Снять замок: слой снова можно править'
              : 'Запретить себе править слой, чтобы не сдвинуть случайно; только в этом браузере'} side="bottom">
              <button className={cn(iconBtn, 'size-5', l.locked ? 'text-foreground' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100')}
                aria-pressed={l.locked} aria-label="Блокировка" onClick={() => p.onLock(l, !l.locked)}>{l.locked ? <Lock /> : <LockOpen />}</button>
            </Tip>
            <Tip label={editing ? 'Закончить правку слоя (Esc, когда ничего не выбрано)'
              : l.locked ? 'Слой закрыт для правки: сначала снимите замок'
                : ofVariant ? `Править вариант «${l.name}»: ставить из каталога, двигать, убирать; учёт не меняется`
                  : 'Править объекты слоя: ставить из каталога, двигать, поворачивать; изменения сразу уходят в учёт'} side="bottom">
              <button className={cn(iconBtn, 'size-5', editing && 'bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground')}
                aria-pressed={editing} aria-label="Редактировать слой" disabled={l.locked && !editing}
                onClick={() => p.onEdit(editing ? null : l.id)}><Pencil /></button>
            </Tip>
          </>
        ) : l.locked && (
          <Tip label="Слой только для просмотра: править его может администратор здания" side="bottom">
            <Lock className="mx-1 size-3.5 text-muted-foreground" />
          </Tip>
        )}
      </li>
    )
  }

  // ---- rooms: by floor, with the objects of the shown layers in each
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
  const flip = (set: (f: (o: Set<string>) => Set<string>) => void, k: string) =>
    set((o) => { const n = new Set(o); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const match = (r: RoomMeta) => !s || roomName(r).toLowerCase().includes(s)
  const objectRow = (o: TreeObject) => (
    <li key={o.id}>
      <Tip label={p.editLayer === o.layer ? 'Приблизить объект на плане и открыть его свойства справа'
        : 'Приблизить объект на плане; свойства открываются, когда правится его слой'} side="right">
        <button className={cn(row, 'py-0.5 text-xs', p.selectedObject === o.id && 'bg-accent font-medium text-accent-foreground')}
          onClick={() => p.onObject(o.layer, o)}>
          <i className={cn('size-2 shrink-0', o.kind === 'item' ? 'rounded-[2px]' : 'rounded-full')} style={{ background: o.color ?? '#adb5bd' }} />
          <span className="min-w-0 flex-1 truncate">{o.name}</span>
          <small className="max-w-24 shrink-0 truncate text-muted-foreground">{LOOK[p.layers.find((l) => l.id === o.layer)?.kind ?? '']?.short}</small>
        </button>
      </Tip>
    </li>
  )
  const objectsOf = (k: string, label: string, hint: string) => {
    const objs = byRoom.get(k) ?? []
    if (!objs.length) return null
    const open = openRooms.has(k) || objs.some((o) => o.id === p.selectedObject)
    return (
      <li>
        <div className="flex items-center rounded-md hover:bg-secondary">
          <Tip label={open ? 'Скрыть эти объекты' : hint} side="right">
            <button className={cn(iconBtn, 'hover:bg-transparent')} aria-label={open ? 'Свернуть' : 'Показать объекты'} onClick={() => flip(setOpenRooms, k)}>
              {open ? <ChevronDown /> : <ChevronRight />}</button>
          </Tip>
          <button className={cn(row, 'py-1 text-xs text-muted-foreground hover:bg-transparent')} onClick={() => flip(setOpenRooms, k)}>
            <span className="min-w-0 flex-1 truncate">{label}</span>
            <span className="rounded-full bg-secondary px-1.5 text-[10px]">{objs.length}</span>
          </button>
        </div>
        {open && <ul className="m-0 mb-1 ml-5 grid list-none grid-cols-[minmax(0,1fr)] gap-px border-l border-border p-0 pl-1">{objs.map(objectRow)}</ul>}
      </li>
    )
  }

  return (
    <div className="@container flex h-full min-h-0 flex-col">
      <div className="relative shrink-0 border-b border-border p-2">
        <Search className="pointer-events-none absolute top-4 left-4 size-3.5 text-muted-foreground" />
        <Tip label="Оставить в списке помещения с этим текстом в названии" side="bottom">
          <Input className="h-7 pl-7 text-xs" placeholder="Помещение или этаж" value={q} onChange={(e) => setQ(e.target.value)} />
        </Tip>
      </div>
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-1.5">
        {/* the drawing: its name opens the summary; another drawing of the building is chosen beside it */}
        <div className={cn('group mb-2 flex items-center rounded-md hover:bg-secondary', p.drawingSelected && 'bg-accent')}>
          <Tip label="Сводка чертежа справа: этажи, замечания распознавания, выгрузка DXF и DWG" side="right">
            <button className={cn(row, 'font-medium hover:bg-transparent')} onClick={p.onDrawing}>
              <i className="size-2.5 shrink-0 rounded-full" style={{ background: jobColor(p.jobId) }} />
              <span className="min-w-0 flex-1 truncate">{current?.name ?? p.result.source}</span>
              <small className="font-normal text-muted-foreground">{floors.length} эт.</small>
            </button>
          </Tip>
          {jobs.length > 1 && (
            <DropdownMenu>
              <Tip label="Другой чертёж этого здания в редакторе" side="right">
                <DropdownMenuTrigger asChild><button className={iconBtn} aria-label="Сменить чертёж"><ChevronsUpDown /></button></DropdownMenuTrigger>
              </Tip>
              <DropdownMenuContent align="start" className="w-64">
                <DropdownMenuLabel>Чертежи здания</DropdownMenuLabel>
                {jobs.map((j) => (
                  <DropdownMenuItem key={j.id} disabled={j.id === p.jobId} onSelect={() => p.onOpenJob(j.id)}>
                    <i className="size-2.5 shrink-0 rounded-full" style={{ background: jobColor(j.id) }} />
                    <span className="min-w-0 flex-1 truncate">{j.name}</span><small className="text-muted-foreground">{j.floors} эт.</small>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          <DropdownMenu>
            <Tip label="Сводка, выгрузка файла, настройка этажей и ролей слоёв CAD" side="right">
              <DropdownMenuTrigger asChild><button className={cn(iconBtn, 'mr-1')} aria-label="Действия с чертежом"><MoreHorizontal /></button></DropdownMenuTrigger>
            </Tip>
            <DropdownMenuContent align="end" className="w-64">
              <Tip label="Открыть справа этажи чертежа, файлы 3D-модели и замечания распознавания" side="left">
                <DropdownMenuItem onSelect={p.onDrawing}><FileText /> Сводка и предупреждения</DropdownMenuItem>
              </Tip>
              <Tip label="Скачать исходный чертёж с исправлениями из редактора плана и объектами учёта блоками с атрибутами" side="left">
                <DropdownMenuItem onSelect={() => p.onExport('dxf')}><Download /> Сохранить DXF с правками</DropdownMenuItem>
              </Tip>
              <Tip label="То же в формате AutoCAD: исходный чертёж с исправлениями плана и объектами учёта" side="left">
                <DropdownMenuItem onSelect={() => p.onExport('dwg')}><Download /> Сохранить DWG с правками</DropdownMenuItem>
              </Tip>
              {p.editable && (
                <Tip label="Какие листы строить, номера и высоты этажей, роли слоёв CAD; после правки модель собирается заново" side="left">
                  <DropdownMenuItem onSelect={p.onFloorSettings}><Settings2 /> Этажи и роли слоёв чертежа…</DropdownMenuItem>
                </Tip>
              )}
              <DropdownMenuSeparator />
              <Tip label="Страница здания: загрузить новый чертёж или новую версию этого, расставить этажи" side="left">
                <DropdownMenuItem asChild><a href={`#/p/${p.projectId}`}><ExternalLink /> Чертежи здания, новый файл</a></DropdownMenuItem>
              </Tip>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {LATER.layers && (
          <section className="mb-2">
            <Heading action={(
              <>
                {variants.length > 0 && (
                  <DropdownMenu>
                    <Tip label="Что показывать во всех слоях объектов: учёт как есть или вариант перестановки; только на вашем экране" side="right">
                      <DropdownMenuTrigger asChild>
                        <button className="flex h-6 max-w-36 cursor-pointer items-center gap-1 rounded-md border border-border bg-card px-1.5 text-xs font-medium text-foreground hover:bg-secondary"
                          aria-label="Показывать: факт или вариант">
                          <span className="truncate">{shownVariant ? variants.find(([v]) => v === shownVariant)?.[1] ?? 'вариант' : 'факт'}</span>
                          <ChevronsUpDown className="size-3 shrink-0 text-muted-foreground" />
                        </button>
                      </DropdownMenuTrigger>
                    </Tip>
                    <DropdownMenuContent align="end" className="w-56">
                      <DropdownMenuLabel>На плане</DropdownMenuLabel>
                      <DropdownMenuItem onSelect={() => p.onPickVariant(null)}><Building /> Факт — как на учёте</DropdownMenuItem>
                      {variants.map(([v, name]) => (
                        <Tip key={v} label="Вариант перестановки во всех слоях разом: что в нём поставлено, убрано и сдвинуто" side="left">
                          <DropdownMenuItem onSelect={() => p.onPickVariant(v)}><GitCompare /> {name}</DropdownMenuItem>
                        </Tip>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
                <DropdownMenu>
                  <Tip label="Видимость всех слоёв разом, сравнение вариантов" side="right">
                    <DropdownMenuTrigger asChild><button className={iconBtn} aria-label="Слои: действия"><MoreHorizontal /></button></DropdownMenuTrigger>
                  </Tip>
                  <DropdownMenuContent align="end" className="w-60">
                    {shown.length > 1 && (
                      <Tip label="Только на вашем экране: другим ничего не меняется, выбор запоминается в браузере" side="left">
                        <DropdownMenuItem onSelect={() => p.onAll(!allShown)}>{allShown ? <EyeOff /> : <Eye />} {allShown ? 'Скрыть все' : 'Показать все'}</DropdownMenuItem>
                      </Tip>
                    )}
                    {groups.length > 0 && (
                      <Tip label="Что добавлено, убрано и перемещено между двумя вариантами слоя, со спецификацией и суммами по ценам каталога" side="left">
                        <DropdownMenuItem onSelect={p.onCompare}><GitCompare /> Сравнить варианты</DropdownMenuItem>
                      </Tip>
                    )}
                    {p.editable && LATER.newLayers && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuLabel>Новый слой</DropdownMenuLabel>
                        {p.kinds.map((k) => (
                          <Tip key={k.kind} label="Пустой слой этого вида в проекте: его увидят все, править можно сразу" side="left">
                            <DropdownMenuItem onSelect={() => p.onAddLayer(k.kind)}><Plus /> {k.name}</DropdownMenuItem>
                          </Tip>
                        ))}
                      </>
                    )}
                    {p.editable && (
                      <>
                        <DropdownMenuSeparator />
                        <Tip label="Раздел здания «Варианты»: завести вариант размещения, сравнить с учётом и применить" side="left">
                          <DropdownMenuItem asChild><a href={`#/b/${p.projectId}/variants`}><ExternalLink /> Варианты размещения</a></DropdownMenuItem>
                        </Tip>
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            )}>На плане</Heading>
            {!shown.length && (
              <p className="m-0 px-2 py-1 text-xs text-muted-foreground">
                Слоёв пока нет.{p.editable ? ' Создайте слой в меню «⋯» — мебель, камеры, маршруты, зоны, системы.' : ''}
              </p>
            )}
            <ul className="m-0 grid list-none grid-cols-1 gap-1 p-0 px-1 @[300px]:grid-cols-2" aria-label="Слои">{shown.map(chip)}</ul>
          </section>
        )}

        <section>
          <Heading>Помещения</Heading>
          <ul className="m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-px p-0">
            {floors.map((f) => {
              const rooms = f.rooms.filter(match)
              if (s && !rooms.length && !f.name.toLowerCase().includes(s)) return null
              const isActive = p.active === f.id
              const expanded = !!s || isActive || openFloors.has(f.id)
              const area = f.rooms.reduce((a, r) => a + r.area, 0)
              return (
                <li key={f.id}>
                  <div className={cn('group flex items-center rounded-md hover:bg-secondary', isActive && 'bg-accent')}>
                    <Tip label={expanded ? 'Скрыть помещения этажа' : 'Показать помещения этажа'} side="right">
                      <button aria-label={expanded ? 'Свернуть' : 'Развернуть'} className={cn(iconBtn, 'hover:bg-transparent')} onClick={() => flip(setOpenFloors, f.id)}>
                        {expanded ? <ChevronDown /> : <ChevronRight />}
                      </button>
                    </Tip>
                    <Tip label="Сделать этаж активным: на нём смотрят план и ставят объекты (то же — на ленте этажей у плана)" side="right">
                      <button className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 border-0 bg-transparent py-1.5 pr-1 text-left text-sm text-foreground"
                        aria-pressed={isActive} onClick={() => p.onFloor(isActive ? null : f.id)}>
                        <span className={cn('grid h-5 min-w-6 shrink-0 place-items-center rounded-full px-1 text-[11px] font-bold', isActive ? 'bg-primary text-primary-foreground' : 'bg-secondary')}>{f.level ?? '·'}</span>
                        <span className={cn('min-w-0 flex-1 truncate', isActive && 'font-medium text-accent-foreground')}>{f.name}</span>
                        <small className="shrink-0 text-muted-foreground">{f.stats.rooms} пом. · {area.toFixed(0)} м²</small>
                      </button>
                    </Tip>
                    {p.editable && (
                      <Tip label="Исправить стены, проёмы и помещения в 2D-редакторе; после применения модель собирается заново" side="right">
                        <button className={cn(iconBtn, 'mr-1 opacity-0 group-hover:opacity-100 focus-visible:opacity-100')} aria-label="Редактировать план этажа"
                          onClick={() => p.onPlan(f.id)}><PencilRuler /></button>
                      </Tip>
                    )}
                  </div>
                  {expanded && (
                    <ul className="m-0 mb-1 ml-6 grid list-none grid-cols-[minmax(0,1fr)] gap-px border-l border-border p-0 pl-1">
                      {rooms.map((r) => {
                        const k = `${f.id}|${r.id ?? '-'}`
                        const objs = r.id != null ? byRoom.get(k) ?? [] : []
                        const roomOpen = openRooms.has(k) || objs.some((o) => o.id === p.selectedObject)
                        return (
                          <li key={r.node}>
                            <div className={cn('flex items-center rounded-md hover:bg-secondary', p.selectedRoom === r.node && 'bg-accent')}>
                              <Tip label={roomOpen ? 'Скрыть объекты помещения' : 'Список объектов в помещении из показанных слоёв'} side="right">
                                <button className={cn(iconBtn, 'hover:bg-transparent', !objs.length && 'invisible')} aria-label={roomOpen ? 'Свернуть' : 'Показать объекты'}
                                  onClick={() => flip(setOpenRooms, k)}>{roomOpen ? <ChevronDown /> : <ChevronRight />}</button>
                              </Tip>
                              <Tip label="Приблизить помещение; справа — его площадь, объекты и путь отсюда или сюда" side="right">
                                <button className={cn(row, 'py-1 text-xs hover:bg-transparent', p.selectedRoom === r.node && 'font-medium text-accent-foreground')}
                                  onClick={() => p.onRoom(f, r)}>
                                  <i className="size-2.5 shrink-0 rounded-[3px] border border-black/10" style={{ background: types.get(r.type ?? '')?.color ?? '#adb5bd' }} />
                                  <span className="min-w-0 flex-1 truncate">{roomName(r)}</span>
                                  {objs.length > 0 && <span className="rounded-full bg-secondary px-1.5 text-[10px] text-muted-foreground">{objs.length}</span>}
                                  <small className="text-muted-foreground">{r.area.toFixed(0)} м²</small>
                                </button>
                              </Tip>
                            </div>
                            {roomOpen && objs.length > 0 && (
                              <ul className="m-0 mb-1 ml-5 grid list-none grid-cols-[minmax(0,1fr)] gap-px border-l border-border p-0 pl-1">{objs.map(objectRow)}</ul>
                            )}
                          </li>
                        )
                      })}
                      {!rooms.length && <li className="px-2 py-1 text-xs text-muted-foreground">Помещений нет</li>}
                      {!s && objectsOf(`${f.id}|-`, 'Вне помещений и между ними', 'Список объектов вне помещений из показанных слоёв')}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      </div>
      <Tip label="Уйти из редактора на страницу здания: загрузка и версии чертежей, расстановка этажей" side="top">
        <a href={`#/p/${p.projectId}`} className="flex shrink-0 items-center gap-1.5 border-t border-border px-3 py-1.5 text-xs text-muted-foreground no-underline hover:text-foreground">
          <ExternalLink className="size-3.5" /> Здание: чертежи и этажи
        </a>
      </Tip>
    </div>
  )
}
