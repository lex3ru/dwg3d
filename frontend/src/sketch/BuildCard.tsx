import { Box, Hammer } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getDrawing, rebuildDrawing, type Drawing } from '@/api'
import { Button } from '@/components/ui/button'
import { floatClass } from '@/components/ui/float'
import { cn } from '@/lib/utils'
import { checkFloor } from '@/plan'
import { useEvents } from '@/stream'
import type { SketchState } from './state'

const SAVE_TEXT: Record<string, string> = {
  loading: 'Загрузка…', saved: 'Сохранено', unsaved: 'Не сохранено', saving: 'Сохраняется…',
}

/**
 * Where the plan is: saved or not, and its building — «Собрать здание» saves what is not saved yet and
 * builds it into floors, rooms and the 3D model, as a drawing is built.
 */
export function BuildCard({ drawing, st }: { drawing: string; st: SketchState }) {
  const [d, setD] = useState<Drawing | null>(null)
  const [live, setLive] = useState<{ progress: number; message: string } | null>(null)
  const [refused, setRefused] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => { getDrawing(drawing).then(setD, () => {}) }, [drawing])
  useEffect(load, [load])
  useEvents(event => {
    const data = event.data as { drawing_id?: string; progress?: number; message?: string }
    if (data.drawing_id !== drawing) return
    if (event.type === 'import.build.progress') setLive({ progress: data.progress ?? 0, message: data.message ?? '' })
    else if (event.type.startsWith('import.build.')) { setLive(null); load() }
  })

  // a plan with errors (walls crossing away from a corner, an opening off its wall) is not built
  const errors = useMemo(() => (st.sketch?.floors ?? []).flatMap(f => checkFloor(f).filter(i => i.level === 'error').map(i => `${f.name}: ${i.message}`)), [st.sketch])
  const empty = !(st.sketch?.floors ?? []).some(f => Object.keys(f.walls).length)
  const b = d?.build
  const running = b?.status === 'queued' || b?.status === 'running'
  const built = b?.status === 'done' && d?.current_build_id === b.id

  const build = () => {
    setBusy(true)
    setRefused(null)
    st.flush().then(() => rebuildDrawing(drawing)).then(setD, (e: Error) => setRefused(e.message)).finally(() => setBusy(false))
  }

  return (
    <div className={cn(floatClass, 'space-y-2 rounded-lg p-3 text-sm')} data-testid="sketch-build">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-semibold" title={d?.name}>{d?.name ?? 'План'}</span>
        <span className={cn('shrink-0 text-xs', st.status === 'saved' ? 'text-muted-foreground' : st.status === 'conflict' || st.status === 'failed' ? 'text-destructive' : 'text-foreground')}
          data-testid="sketch-save">{SAVE_TEXT[st.status] ?? 'Не сохранено'}</span>
      </div>
      {st.status === 'conflict' && (
        <div className="space-y-1.5" role="alert">
          <p className="text-xs text-destructive">План успели сохранить в другом окне. Правки отсюда больше не сохраняются.</p>
          <Button size="sm" variant="outline" onClick={st.reload} hint="Открыть план таким, как его сохранили в другом окне; несохранённое здесь пропадёт">Загрузить сохранённый</Button>
        </div>
      )}
      {st.status === 'failed' && (
        <div className="space-y-1.5" role="alert">
          <p className="text-xs text-destructive">Не удалось сохранить: {st.error}</p>
          <Button size="sm" variant="outline" onClick={() => { st.flush().catch(() => {}) }} hint="Отправить план на сервер ещё раз">Повторить</Button>
        </div>
      )}
      {running && (
        <div>
          <div className="h-1.5 w-full overflow-hidden rounded bg-secondary" role="progressbar" aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={Math.round((live?.progress ?? b?.progress ?? 0) * 100)}>
            <div className="h-full bg-primary transition-all" style={{ width: `${Math.round((live?.progress ?? b?.progress ?? 0) * 100)}%` }} />
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{b?.status === 'queued' ? 'В очереди' : live?.message ?? b?.message}</p>
        </div>
      )}
      {b?.status === 'error' && <p className="text-xs text-destructive" role="alert">Сборка {b.n} не удалась: {b.error}</p>}
      {refused && <p className="text-xs text-destructive" role="alert">{refused}</p>}
      {built && !running && <p className="text-xs text-muted-foreground" data-testid="sketch-built">Собрана сборка {b.n}: здание взяло этажи и помещения плана.</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy || running || empty || errors.length > 0 || st.status === 'conflict'} onClick={build} data-testid="sketch-build-button"
          hint={empty ? 'Собрать здание из плана: сначала нарисуйте стены'
            : errors.length ? `Собрать здание из плана: сначала исправьте — ${errors[0]}`
              : running ? 'Сборка уже идёт' : 'Сохранить план и собрать из него этажи, помещения и 3D-модель здания'}>
          <Hammer className="size-4" />Собрать здание
        </Button>
        {built && (
          <Button asChild size="sm" variant="outline" hint="3D-сцена здания из этого плана: помещения, расстановка объектов">
            <a href={`#/f/${drawing}`}><Box className="size-4" />Открыть в 3D</a>
          </Button>
        )}
      </div>
    </div>
  )
}
