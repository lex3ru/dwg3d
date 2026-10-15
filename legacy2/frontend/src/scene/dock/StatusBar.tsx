import { LATER } from '../compat'
import { AlertTriangle, Loader2 } from 'lucide-react'
import type { Projection, NavMode } from '@/scene/state'
import { Tip } from '@/components/ui/tooltip'

const NAV: Record<NavMode, string> = { orbit: 'Обзор', fly: 'Полёт', walk: 'Прогулка' }

/** The strip under the scene: where you are and what is going on. */
export default function StatusBar({ floor, nav, proj, objects, rooms, conflicts, busy, error, onConflicts }: {
  floor: string
  nav: NavMode
  proj: Projection
  objects: number
  rooms: number | null
  conflicts: number
  /** a build in progress: text and 0..1 */
  busy: { text: string; progress?: number } | null
  error?: string | null
  onConflicts: () => void
}) {
  return (
    <footer role="status" className="flex h-6 shrink-0 select-none items-center gap-3 border-t border-border bg-card px-3 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">{floor}</span>
      <span>{NAV[nav]} · {proj.toUpperCase()}</span>
      {rooms != null && <span className="max-sm:hidden">{rooms} пом.</span>}
      {LATER.layers && <span className="max-sm:hidden">объектов на чертеже: {objects}</span>}
      <span className="flex-1" />
      {conflicts > 0 && (
        <Tip label="Открыть слой маршрутов на редактирование: маршруты с пересечением потоков отмечены справа">
          <button className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-xs text-destructive hover:underline" onClick={onConflicts}>
            <AlertTriangle className="size-3.5" /> конфликтов потоков: {conflicts}
          </button>
        </Tip>
      )}
      {error && <span className="text-destructive">{error}</span>}
      {busy && (
        <span className="inline-flex items-center gap-1.5 text-foreground">
          <Loader2 className="size-3.5 animate-spin" /> {busy.text}{busy.progress != null ? ` ${Math.round(busy.progress * 100)}%` : ''}
        </span>
      )}
    </footer>
  )
}
