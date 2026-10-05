import { Armchair, Check, Eye, MapPin, MessageCirclePlus, Pencil, Route, Ruler, Spline, SquareDashed, Undo2, Waypoints, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Layer, LayerKindInfo } from '@/scene/api'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { MeasureMode, Tool } from '@/scene/state'
import type { RouteState } from './Toolbar'

function ToolBtn({ icon: Icon, label, on, onClick, hint, disabled }: { icon: LucideIcon; label: string; on?: boolean; onClick: () => void; hint?: string; disabled?: boolean }) {
  return (
    <Tip label={hint ?? label} side="bottom">
      <button aria-pressed={on} disabled={disabled} onClick={onClick}
        className={cn('inline-flex h-7 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border-0 px-2 text-xs font-medium transition-colors disabled:cursor-default disabled:opacity-40 [&_svg]:size-4',
          on ? 'bg-accent text-accent-foreground' : 'bg-transparent text-foreground hover:bg-secondary')}>
        <Icon /><span className="@max-3xl:hidden">{label}</span>
      </button>
    </Tip>
  )
}
const Sep = () => <span className="mx-1 h-5 w-px shrink-0 bg-border" />

/**
 * The bar over the scene: what you are doing now and its tools. Viewing:
 * measuring, a quick route, markers, comments. Editing a layer: that layer's
 * tools and "Done". The building itself is edited in the plan editor.
 */
export default function ContextBar(p: {
  tool: Tool
  measureMode: MeasureMode
  onTool: (t: Tool) => void
  onMeasure: (mode: MeasureMode) => void
  route: RouteState
  onClearRoute: () => void
  editable: boolean
  layers: Layer[]
  kinds: LayerKindInfo[]
  editLayer: Layer | null
  floorName: string | null
  onEdit: (id: string | null) => void
  canUndo: boolean
  onUndo: () => void
  hint: ReactNode
  /** the editing layer's own buttons (new route, zone, cable line) */
  actions?: ReactNode
}) {
  const kind = p.editLayer ? p.kinds.find((k) => k.kind === p.editLayer!.kind) : null
  const points = !!kind?.geoms.includes('point')
  const lines = !!kind && kind.geoms.some((g) => g !== 'point')
  const editableLayers = p.layers.filter((l) => !l.locked)

  if (p.editLayer) {
    return (
      <div role="toolbar" aria-label="Редактирование слоя" className="flex h-10 shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-card px-2">
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-2 py-1 text-xs font-medium text-primary-foreground">
          <Pencil className="size-3.5" /> {p.editLayer.name}{p.floorName ? ` · ${p.floorName}` : ''}
        </span>
        <Sep />
        {points && lines && (
          <>
            <ToolBtn icon={Armchair} label="Оборудование" on={p.tool === 'furniture'} onClick={() => p.onTool('furniture')} hint="Ставить оборудование из каталога" />
            <ToolBtn icon={Spline} label="Трассы" on={p.tool === 'shapes'} onClick={() => p.onTool('shapes')} hint="Рисовать кабельные трассы" />
            <Sep />
          </>
        )}
        {p.actions}
        {p.tool === 'furniture' && <ToolBtn icon={Undo2} label="Отменить" disabled={!p.canUndo} onClick={p.onUndo} hint="Отменить последнее действие (Ctrl+Z)" />}
        <span className="min-w-0 flex-1 truncate px-2 text-xs text-muted-foreground">{p.hint}</span>
        <Button size="sm" onClick={() => p.onEdit(null)}><Check /> Готово</Button>
      </div>
    )
  }
  return (
    <div role="toolbar" aria-label="Инструменты просмотра" className="flex h-10 shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-card px-2">
      <span className="inline-flex shrink-0 items-center gap-1.5 px-1.5 text-xs font-medium text-muted-foreground"><Eye className="size-3.5" /> Просмотр</span>
      <Sep />
      <ToolBtn icon={Ruler} label="Расстояние" on={p.tool === 'measure' && p.measureMode === 'length'}
        onClick={() => (p.tool === 'measure' && p.measureMode === 'length' ? p.onTool('none') : p.onMeasure('length'))} hint="Рулетка: расстояние между точками" />
      <ToolBtn icon={SquareDashed} label="Площадь" on={p.tool === 'measure' && p.measureMode === 'area'}
        onClick={() => (p.tool === 'measure' && p.measureMode === 'area' ? p.onTool('none') : p.onMeasure('area'))} hint="Площадь контура" />
      <ToolBtn icon={Route} label="Путь A→B" on={p.tool === 'route'} onClick={() => p.onTool(p.tool === 'route' ? 'none' : 'route')} hint="Кратчайший путь между двумя точками этажа" />
      {p.editable && (
        <>
          <ToolBtn icon={MapPin} label="Метка" on={p.tool === 'marker'} onClick={() => p.onTool(p.tool === 'marker' ? 'none' : 'marker')} hint="Поставить свою метку" />
          <ToolBtn icon={MessageCirclePlus} label="Комментарий" on={p.tool === 'comment'} onClick={() => p.onTool(p.tool === 'comment' ? 'none' : 'comment')} />
        </>
      )}
      <span className="min-w-0 flex-1 truncate px-2 text-xs text-muted-foreground">
        {p.tool === 'route' && (p.route.fromLabel || p.route.toLabel)
          ? <>{p.route.fromLabel || '…'} → {p.route.toLabel || '…'}{p.route.length != null && <b className="text-foreground"> · {p.route.length.toFixed(1)} м, ~{Math.max(1, Math.round(p.route.length / 1.3 / 60))} мин</b>}
            {p.route.error && <span className="text-destructive"> · {p.route.error}</span>}
            <button className="ml-2 cursor-pointer border-0 bg-transparent p-0 text-xs text-primary hover:underline" onClick={p.onClearRoute}>очистить</button></>
          : p.hint}
      </span>
      {p.editable && editableLayers.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button variant="outline" size="sm"><Pencil /> <span className="@max-3xl:hidden">Редактировать слой</span></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-64">
            <DropdownMenuLabel>Какой слой редактировать</DropdownMenuLabel>
            {editableLayers.map((l) => (
              <DropdownMenuItem key={l.id} onSelect={() => p.onEdit(l.id)}>
                {p.kinds.find((k) => k.kind === l.kind)?.geoms.includes('point') ? <Armchair /> : <Waypoints />}
                <span className="min-w-0 flex-1 truncate">{l.name}</span>
                <small className="text-muted-foreground">{p.kinds.find((k) => k.kind === l.kind)?.name}</small>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}
