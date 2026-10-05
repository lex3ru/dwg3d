import { ArrowLeft, Box, RefreshCw, Trash2, Upload } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteDrawing, getBuilding, getTree, listDrawings, listPlaced, rebuildDrawing, uploadDrawing, uploadDrawingFile,
  type Building as BuildingInfo, type Drawing, type PlacedDrawing, type TreeFloor,
} from '../api'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { useEvents } from '../stream'

const STATUS: Record<string, [string, 'default' | 'accent' | 'success' | 'destructive']> = {
  queued: ['в очереди', 'default'], running: ['обрабатывается', 'accent'], done: ['готов', 'success'], error: ['ошибка', 'destructive'],
}
const size = (n: number | null) => (n == null ? '' : n > 1e6 ? `${(n / 1e6).toFixed(1)} МБ` : `${Math.ceil(n / 1e3)} КБ`)

/** One building: its drawings (upload, state of the build, opening in the viewer), floors and rooms. */
export function Building({ id }: { id: string }) {
  const [building, setBuilding] = useState<BuildingInfo | null>(null)
  const [drawings, setDrawings] = useState<Drawing[]>([])
  const [placed, setPlaced] = useState<PlacedDrawing[]>([])
  const [floors, setFloors] = useState<TreeFloor[]>([])
  const [live, setLive] = useState<Record<string, { progress: number; message: string }>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const picker = useRef<HTMLInputElement>(null)
  const target = useRef<string | null>(null)        // the drawing a picked file is a new version of

  const load = useCallback(() => {
    Promise.all([getBuilding(id), listDrawings(id), listPlaced(id), getTree(id)]).then(([b, d, p, f]) => {
      setBuilding(b); setDrawings(d); setPlaced(p); setFloors(f); setError(null)
    }, (e: Error) => setError(e.message))
  }, [id])
  useEffect(load, [load])
  useEvents(event => {
    if (event.type === 'import.build.progress') {
      const d = event.data as { drawing_id: string; progress: number; message: string }
      setLive(l => ({ ...l, [d.drawing_id]: { progress: d.progress, message: d.message } }))
    } else if (event.type.startsWith('import.') || event.type.startsWith('buildings.')) load()
  })

  const act = (work: Promise<unknown>) => {
    setBusy(true)
    work.then(() => setError(null), (e: Error) => setError(e.message)).finally(() => { setBusy(false); load() })
  }
  const picked = (files: FileList | null) => {
    const file = files?.[0]
    if (!file) return
    act(target.current
      ? uploadDrawingFile(target.current, file).then(d => { if (d.unchanged) throw new Error('Это тот же файл — чертёж не изменился') })
      : uploadDrawing(id, file))
    if (picker.current) picker.current.value = ''
  }
  const pick = (drawing: string | null) => { target.current = drawing; picker.current?.click() }

  if (!building) return <p className="text-sm text-muted-foreground">{error ?? 'Загрузка…'}</p>
  const rooms = floors.reduce((n, f) => n + f.rooms.length, 0)
  return (
    <section className="space-y-6">
      <div>
        <a href="#/buildings" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Мои здания
        </a>
        <h1 className="mt-1 text-xl font-semibold">{building.name}</h1>
        {building.address && <p className="text-sm text-muted-foreground">{building.address}</p>}
        {floors.length > 0 && <p className="mt-1 text-sm text-muted-foreground" data-testid="totals">Этажей: {floors.length} · помещений: {rooms}</p>}
      </div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

      <div>
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold">Чертежи</h2>
          <Button size="sm" onClick={() => pick(null)} disabled={busy}><Upload className="size-4" /> Загрузить чертёж</Button>
          <input ref={picker} type="file" accept=".dwg,.dxf" className="hidden" data-testid="file"
            onChange={e => picked(e.target.files)} />
        </div>
        {drawings.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">Загрузите поэтажные планы здания в формате DWG или DXF — одним файлом или по файлу на этаж или корпус.</p>
        ) : (
          <ul className="mt-3 divide-y rounded-lg border bg-card" data-testid="drawings">
            {drawings.map(d => {
              const b = d.build
              const shown = placed.find(p => p.id === d.id)?.build_id
              // built, but the building follows the event and may be a moment behind
              const publishing = b?.status === 'done' && shown !== b.id
              const [label, tone] = publishing ? STATUS.running : STATUS[b?.status ?? 'queued']
              const running = b?.status === 'queued' || b?.status === 'running' || publishing
              const now = live[d.id]
              const progress = publishing ? 0.99 : b?.status === 'running' ? (now?.progress ?? b.progress) : 0
              return (
                <li key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5" data-drawing={d.name}
                  data-status={publishing ? 'running' : b?.status}>
                  <div className="min-w-40 flex-1">
                    <div className="font-medium">{d.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {size(d.size)}{d.file_n && d.file_n > 1 ? ` · файл ${d.file_n}` : ''}{b ? ` · сборка ${b.n}` : ''}
                    </div>
                    {running && (
                      <div className="mt-1.5">
                        <div className="h-1.5 w-full max-w-xs overflow-hidden rounded bg-secondary" role="progressbar"
                          aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
                          <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
                        </div>
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {publishing ? 'Публикация' : b?.status === 'running' ? (now?.message ?? b.message) : 'В очереди'}
                        </div>
                      </div>
                    )}
                    {b?.status === 'error' && <div role="alert" className="mt-1 text-sm text-destructive">{b.error}</div>}
                  </div>
                  <Badge variant={tone}>{label}</Badge>
                  {shown && (
                    <Button asChild size="sm"><a href={`#/f/${d.id}`}><Box className="size-4" /> Открыть</a></Button>
                  )}
                  <Button variant="outline" size="sm" disabled={busy || running} onClick={() => pick(d.id)} title="Загрузить новую версию файла">
                    <Upload className="size-4" /> <span className="max-sm:hidden">Новый файл</span>
                  </Button>
                  <Button variant="ghost" size="icon" disabled={busy || running} title="Собрать заново" onClick={() => act(rebuildDrawing(d.id))}>
                    <RefreshCw className="size-4" />
                  </Button>
                  <Button variant="ghost" size="icon" disabled={busy} title="Удалить чертёж"
                    onClick={() => { if (confirm(`Удалить чертёж «${d.name}»? Его этажи и помещения будут сняты.`)) act(deleteDrawing(d.id)) }}>
                    <Trash2 className="size-4" />
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {floors.length > 0 && (
        <div>
          <h2 className="text-base font-semibold">Этажи</h2>
          <ul className="mt-3 divide-y rounded-lg border bg-card text-sm" data-testid="floors">
            {floors.map(f => (
              <li key={f.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <span>{f.name || `Этаж ${f.level ?? ''}`}</span>
                <span className="text-muted-foreground">помещений: {f.rooms.length}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
