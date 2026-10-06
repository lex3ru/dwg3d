import { AlertTriangle, Download, FileBox, PencilRuler, X } from 'lucide-react'
import { useState } from 'react'
import { fileUrl, type Job } from '@/scene/api'
import { Button } from '@/components/ui/button'
import { Tip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/**
 * The drawing chosen in the tree: its floors, the plan editor of the active
 * floor, saving the drawing with the objects of accounting, model downloads and
 * what the recognition warns about.
 */
export default function DrawingInspector({ job, shown, active, running, editCount, objectCount, saving, saveErr, editable, onFloor, onEditor, onSave, onClose }: {
  job: Job
  shown: Job
  active: string | null
  running: boolean
  editCount: number
  /** objects of accounting on the floors of this drawing */
  objectCount: number
  saving: 'dxf' | 'dwg' | null
  saveErr: string | null
  editable: boolean
  onFloor: (id: string | null) => void
  onEditor: () => void
  onSave: (f: 'dxf' | 'dwg', withObjects: boolean) => void
  onClose: () => void
}) {
  const r = shown.result!
  const floors = [...r.floors].sort((a, b) => b.elevation! - a.elevation!)
  const act = floors.find((f) => f.id === active)
  const [withObjects, setWithObjects] = useState(true)
  const warnings = [
    ...((r.edits_unmatched ?? 0) > 0 ? [`Правки ${r.edits_unmatched} этаж(ей) не применены: их лист не найден в текущем разборе.`] : []),
    ...r.warnings,
  ]
  return (
    <div className="grid gap-4 p-3 text-sm">
      <div className="flex items-start gap-2">
        <FileBox className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <b className="block truncate">{job.filename}</b>
          <small className="text-xs text-muted-foreground">{r.floors.length} этажей · {r.floors.reduce((s, f) => s + f.stats.rooms, 0)} помещений{shown.build > 1 ? ` · сборка ${shown.build}` : ''}</small>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Закрыть" hint="Убрать сводку из панели; снова открыть — щелчком по чертежу в дереве" onClick={onClose}><X /></Button>
      </div>

      {r.quality?.status === 'suspect' && (
        <div className="grid gap-1 rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
          <b className="flex items-center gap-1.5"><AlertTriangle className="size-3.5" /> Результат выглядит сомнительно</b>
          {r.quality.issues.map((w) => <span key={w}>{w}</span>)}
          <span className="text-muted-foreground">Проверьте роли слоёв и единицы в настройках этажей.</span>
        </div>
      )}

      <section className="grid gap-1">
        <b className="text-xs">Этажи</b>
        <ul className="m-0 grid list-none gap-0.5 p-0">
          {floors.map((f) => (
            <li key={f.id}>
              <Tip label="Сделать этаж активным: его план можно править, на нём ставятся объекты" side="left">
                <button className={cn('grid w-full cursor-pointer gap-0.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-foreground hover:bg-secondary', active === f.id && 'bg-accent')}
                  onClick={() => onFloor(f.id)}>
                  <span className="flex items-center gap-2 text-sm">
                    <span className={cn('grid h-5 min-w-6 place-items-center rounded-full px-1 text-[11px] font-bold', active === f.id ? 'bg-primary text-primary-foreground' : 'bg-secondary')}>{f.level}</span>
                    <span className="truncate">{f.name}</span>
                  </span>
                  <span className="flex flex-wrap gap-x-2.5 pl-8 text-[11px] text-muted-foreground">
                    <span>{f.elevation! >= 0 ? '+' : ''}{f.elevation!.toFixed(2)} м</span>
                    <span>h {f.height!.toFixed(2)} м</span>
                    <span>{f.stats.rooms} пом.</span>
                    <span>{Math.round(f.stats.footprint_m2)} м²</span>
                  </span>
                </button>
              </Tip>
            </li>
          ))}
        </ul>
        {editable && (
          <Button variant="outline" size="sm" className="justify-self-start" disabled={running || !act} onClick={onEditor}
            hint={running ? 'Недоступно, пока модель собирается' : !act ? 'Сначала выберите этаж в списке выше'
              : 'Исправить стены, проёмы и помещения в 2D-редакторе; применённые правки пересобирают модель'}>
            <PencilRuler /> {act ? `Редактировать план: ${act.name}` : 'Выберите этаж, чтобы править план'}
          </Button>
        )}
      </section>

      <section className="grid gap-2 rounded-md border border-border p-2.5">
        <b className="text-xs">Сохранить чертёж{editCount > 0 && <span className="ml-1.5 rounded-full bg-success/15 px-1.5 font-normal text-success">правок: {editCount}</span>}</b>
        {objectCount > 0 && (
          <Tip label="Положить в файл все объекты учёта этажей чертежа блоками с атрибутами: номер, состояние, ответственный, помещение. Скрытые слои тоже; предметы вариантов — нет">
            <label className="flex items-center gap-2 text-xs">
              <input type="checkbox" className="accent-primary" checked={withObjects} onChange={(e) => setWithObjects(e.target.checked)} />
              с объектами учёта ({objectCount})
            </label>
          </Tip>
        )}
        <div className="flex gap-1.5">
          {(['dxf', 'dwg'] as const).map((f) => (
            <Button key={f} variant="secondary" size="sm" className="flex-1" disabled={!!saving || running || (!editCount && !(withObjects && objectCount > 0))}
              hint={saving ? 'Файл уже готовится' : running ? 'Недоступно, пока модель собирается'
                : !editCount && !(withObjects && objectCount > 0) ? 'Нечего сохранять: нет исправлений плана и объектов учёта'
                  : `${f === 'dxf' ? 'Скачать исходный чертёж' : 'То же в формате AutoCAD: исходный чертёж'} с исправлениями плана${withObjects && objectCount > 0 ? ' и объектами учёта' : ''}`}
              onClick={() => onSave(f, withObjects && objectCount > 0)}>
              <Download /> {saving === f ? 'Готовлю…' : f.toUpperCase()}
            </Button>
          ))}
        </div>
        {!editCount && !objectCount && <small className="text-[11px] text-muted-foreground">Сохранять нечего: нет правок плана и объектов учёта.</small>}
        {saveErr && <small className="text-xs text-destructive">{saveErr}</small>}
      </section>

      {r.exports && (
        <section className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">3D-модель:</span>
          {Object.entries(r.exports).map(([k, name]) => (
            <Button key={k} asChild variant="outline" size="sm" hint="Скачать файл 3D-модели текущей сборки — для других программ">
              <a href={fileUrl(shown.id, name, shown.build)} download>{k.toUpperCase()}</a>
            </Button>
          ))}
        </section>
      )}

      {warnings.length > 0 && (
        <section className="grid gap-1 rounded-md bg-warning/10 p-2 text-xs text-warning">
          {warnings.map((w) => <span key={w} className="flex gap-1.5"><AlertTriangle className="mt-px size-3.5 shrink-0" /> {w}</span>)}
        </section>
      )}
      <small className="text-[11px] text-muted-foreground">Единицы: {r.units} ({r.units_source}) · {r.triangles.toLocaleString('ru')} треуг. · {r.elapsed_s} с</small>
    </div>
  )
}
