import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, type LucideIcon } from 'lucide-react'
import { useRef, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Tip } from '@/components/ui/tooltip'
import { MAX_WIDTH, MIN_WIDTH, type DockState } from './useDockState'

export interface DockTab { id: string; label: string; icon: LucideIcon; badge?: number | string; /** what the tab is for */ hint?: string }

/**
 * A panel at the left or right edge of the viewer. Open: tabs and the content,
 * a drag handle on the inner edge for the width. Closed: a narrow rail of tab
 * icons. On a narrow screen it floats over the scene instead of taking room.
 */
export default function Dock({ side, label, tabs, tab, onTab, state, children }: {
  side: 'left' | 'right'
  label: string
  tabs: DockTab[]
  tab: string
  onTab: (id: string) => void
  state: DockState
  children: ReactNode
}) {
  const drag = useRef<{ x: number; w: number } | null>(null)
  const left = side === 'left'
  const onDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, w: state.width }
  }
  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    const dx = e.clientX - drag.current.x
    state.setWidth(drag.current.w + (left ? dx : -dx))
  }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      const grow = (e.key === 'ArrowRight') === left
      state.setWidth(state.width + (grow ? 20 : -20))
    }
  }
  const Open = left ? PanelLeftOpen : PanelRightOpen
  const Close = left ? PanelLeftClose : PanelRightClose
  const active = tabs.find((t) => t.id === tab) ?? tabs[0]

  if (!state.open) {
    return (
      <aside aria-label={label} className={cn('z-20 flex w-11 shrink-0 flex-col items-center gap-1 bg-card py-2 text-foreground max-md:hidden', left ? 'border-r' : 'border-l', 'border-border')}>
        <Tip label={`Развернуть панель «${label}»; клавиша ${left ? '[' : ']'}`} side={left ? 'right' : 'left'}>
          <button className="grid size-8 cursor-pointer place-items-center rounded-md border-0 bg-transparent p-0 text-muted-foreground hover:bg-secondary hover:text-foreground"
            aria-label={`Открыть: ${label}`} onClick={() => state.setOpen(true)}><Open className="size-4" /></button>
        </Tip>
        <div className="my-1 h-px w-6 bg-border" />
        {tabs.map((t) => (
          <Tip key={t.id} label={t.hint ? `${t.label} — ${t.hint.charAt(0).toLowerCase()}${t.hint.slice(1)}` : `Развернуть панель на вкладке «${t.label}»`} side={left ? 'right' : 'left'}>
            <button aria-label={t.label}
              className="relative grid size-8 cursor-pointer place-items-center rounded-md border-0 bg-transparent p-0 text-muted-foreground hover:bg-secondary hover:text-foreground"
              onClick={() => { onTab(t.id); state.setOpen(true) }}>
              <t.icon className="size-4" />
              {t.badge ? <span className="absolute -top-0.5 -right-0.5 min-w-3.5 rounded-full bg-destructive px-1 text-[9px] leading-3.5 text-white">{t.badge}</span> : null}
            </button>
          </Tip>
        ))}
      </aside>
    )
  }
  return (
    <aside aria-label={label} style={{ width: state.width }}
      className={cn('relative z-30 flex shrink-0 flex-col border-border bg-card text-foreground max-md:absolute max-md:inset-y-0 max-md:max-w-[92vw] max-md:shadow-xl', left ? 'border-r max-md:left-0' : 'border-l max-md:right-0')}>
      <Tip label="Тянуть мышью или стрелками ← →; ширина запомнится в этом браузере" side={left ? 'right' : 'left'}>
        <div role="separator" aria-orientation="vertical" aria-label="Ширина панели" aria-valuemin={MIN_WIDTH} aria-valuemax={MAX_WIDTH} aria-valuenow={state.width} tabIndex={0}
          className={cn('absolute inset-y-0 z-10 w-1.5 cursor-col-resize touch-none transition-colors hover:bg-primary/40 focus-visible:bg-primary/60 focus-visible:outline-none max-md:hidden', left ? '-right-0.5' : '-left-0.5')}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => { drag.current = null }} onKeyDown={onKey} />
      </Tip>
      <div role="tablist" aria-label={label} className="flex shrink-0 items-center gap-0.5 border-b border-border px-1.5 py-1.5">
        {tabs.map((t) => (
          <Tip key={t.id} label={t.hint ?? (t.id !== active.id ? t.label : null)} side="bottom">
            <button role="tab" aria-selected={t.id === active.id} aria-label={t.label}
              className={cn('relative inline-flex h-7 min-w-0 cursor-pointer items-center gap-1.5 rounded-md border-0 px-2 text-xs font-medium transition-colors',
                t.id === active.id ? 'bg-accent text-accent-foreground' : 'bg-transparent text-muted-foreground hover:bg-secondary hover:text-foreground')}
              onClick={() => onTab(t.id)}>
              <t.icon className="size-3.5 shrink-0" />
              <span className={cn('truncate', t.id !== active.id && 'max-lg:hidden')}>{t.label}</span>
              {t.badge ? <span className="rounded-full bg-destructive px-1 text-[9px] leading-3.5 text-white">{t.badge}</span> : null}
            </button>
          </Tip>
        ))}
        <span className="flex-1" />
        <Tip label={`Оставить узкую полосу значков и освободить место сцене; клавиша ${left ? '[' : ']'}`} side={left ? 'right' : 'left'}>
          <button aria-label="Свернуть панель" className="grid size-7 cursor-pointer place-items-center rounded-md border-0 bg-transparent p-0 text-muted-foreground hover:bg-secondary hover:text-foreground"
            onClick={() => state.setOpen(false)}><Close className="size-4" /></button>
        </Tip>
      </div>
      <div className="dock-body min-h-0 flex-1 overflow-y-auto">{children}</div>
    </aside>
  )
}
