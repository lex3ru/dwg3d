import type { Job } from '../api'
import { cn } from '@/lib/utils'

const STAGES: Record<string, string> = {
  queued: 'В очереди', start: 'Запуск', convert: 'Конвертация DWG → DXF', read: 'Чтение чертежа',
  analyze: 'Поиск этажей', geometry: 'Построение геометрии', mesh: 'Построение 3D',
  export: 'Экспорт', done: 'Готово', error: 'Ошибка',
}

/** A build in progress: file, stage, percent. */
export default function Progress({ job, className }: { job: Job; className?: string }) {
  const pct = Math.round(job.progress * 100)
  return (
    <div className={cn('grid w-full max-w-md gap-2 rounded-xl border border-float-border bg-float p-3 text-foreground shadow-md backdrop-blur', className)}>
      <div className="truncate font-semibold">{job.filename}</div>
      <div className="h-1.5 overflow-hidden rounded-full bg-secondary"><div className="h-full bg-primary transition-[width] duration-300" style={{ width: `${pct}%` }} /></div>
      <div className="flex justify-between gap-2 text-xs text-muted-foreground">
        <span>{STAGES[job.stage] ?? job.stage}</span>
        <span className="truncate">{job.message && job.message !== STAGES[job.stage] ? job.message : ''}</span>
        <span className="tabular-nums">{pct}%</span>
      </div>
    </div>
  )
}
