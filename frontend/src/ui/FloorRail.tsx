import { Plus } from 'lucide-react'
import type { FloorMeta } from '@/api'
import { Tip } from '@/components/ui/tooltip'
import { floatClass } from '@/components/ui/float'
import { cn } from '@/lib/utils'

const btn = 'grid size-9 shrink-0 cursor-pointer place-items-center rounded-full border-0 p-0 text-sm font-semibold transition-colors'

/** Vertical "floor ladder": top floor first, "+" shows the whole building. */
export default function FloorRail({ floors, active, onSelect }: {
  floors: FloorMeta[]        // any order
  active: string | null
  onSelect: (id: string | null) => void
}) {
  const desc = [...floors].sort((a, b) => b.elevation! - a.elevation!)
  return (
    <nav aria-label="Этажи"
      className={cn(floatClass, 'absolute top-1/2 left-3.5 z-15 flex max-h-[70%] -translate-y-1/2 flex-col items-center gap-1 rounded-full p-1')}>
      <Tip label="Всё здание" side="right">
        <button aria-label="Все этажи" aria-pressed={active == null}
          className={cn(btn, active == null ? 'bg-primary text-primary-foreground' : 'bg-transparent text-muted-foreground hover:bg-secondary hover:text-foreground')}
          onClick={() => onSelect(null)}><Plus className="size-4" /></button>
      </Tip>
      <div className="flex min-h-0 flex-col items-center gap-1 overflow-y-auto">
        {desc.map((f) => (
          <Tip key={f.id} side="right" label={`${f.name} · ${f.elevation! >= 0 ? '+' : ''}${f.elevation!.toFixed(2)} м`}>
            <button aria-label={f.name} aria-pressed={active === f.id}
              className={cn(btn, active === f.id ? 'bg-primary text-primary-foreground' : 'bg-transparent text-foreground hover:bg-secondary')}
              onClick={() => onSelect(f.id)}>
              {f.level ?? '·'}
            </button>
          </Tip>
        ))}
      </div>
    </nav>
  )
}
