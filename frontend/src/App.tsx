import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fileUrl, getJob, rebuildJob, uploadFile, type FloorEdits, type Job } from './api'
import Editor2D from './Editor2D'
import Settings from './Settings'
import Viewer, { type FocusRoom, type MeasureMode, type Tool, type ViewMode, type ViewState } from './Viewer'

const STAGES: Record<string, string> = {
  queued: 'В очереди', start: 'Запуск', convert: 'Конвертация DWG → DXF', read: 'Чтение чертежа',
  analyze: 'Поиск этажей', geometry: 'Построение геометрии', mesh: 'Построение 3D',
  export: 'Экспорт', done: 'Готово', error: 'Ошибка',
}

const MODES: { id: ViewMode; label: string; title: string }[] = [
  { id: 'all', label: 'Все', title: 'Показать всё здание' },
  { id: 'isolate', label: 'Изоляция', title: 'Только выбранный этаж' },
  { id: 'below', label: 'До этажа', title: 'Выбранный этаж и ниже (срез)' },
  { id: 'explode', label: 'Разнос', title: 'Этажи разъезжаются по вертикали' },
]

const TOOLS: { id: Tool; label: string; title: string }[] = [
  { id: 'orbit', label: 'Осмотр', title: 'Вращение, зум, панорама' },
  { id: 'measure', label: 'Рулетка', title: 'Расстояние между точками или площадь контура' },
  { id: 'walk', label: 'Прогулка', title: 'Вид от первого лица на выбранном этаже (WASD, мышь, Shift — быстрее, Esc — выход)' },
]

function useJobPolling(jobId: string | null, nonce: number) {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!jobId) return
    let stop = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const j = await getJob(jobId)
        if (stop) return
        setJob(j)
        setError(null)
        if (j.status === 'queued' || j.status === 'running') timer = window.setTimeout(tick, 600)
      } catch (e) {
        if (!stop) {
          setError(String((e as Error).message))
          timer = window.setTimeout(tick, 2000)
        }
      }
    }
    tick()
    return () => { stop = true; window.clearTimeout(timer) }
  }, [jobId, nonce])
  return { job, setJob, error }
}

function Upload({ onJob }: { onJob: (id: string) => void }) {
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const send = async (f: File | undefined) => {
    if (!f) return
    setBusy(true)
    setErr(null)
    try {
      const j = await uploadFile(f)
      onJob(j.id)
    } catch (e) {
      setErr((e as Error).message)
      setBusy(false)
    }
  }
  return (
    <div className="upload-screen">
      <div
        className={`dropzone ${drag ? 'drag' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files[0]) }}
        onClick={() => input.current?.click()}
      >
        <div className="dz-icon">⬆</div>
        <h1>Поэтажные планы → 3D</h1>
        <p>Перетащите файл <b>.dwg</b> или <b>.dxf</b> сюда или нажмите, чтобы выбрать</p>
        <p className="hint">Стены, окна, двери, лестницы и этажи распознаются автоматически; их можно поправить после построения.</p>
        {busy && <p>Загрузка…</p>}
        {err && <p className="error">{err}</p>}
        <input ref={input} type="file" accept=".dwg,.dxf" hidden onChange={(e) => send(e.target.files?.[0])} />
      </div>
    </div>
  )
}

function Progress({ job }: { job: Job }) {
  return (
    <div className="progress-card">
      <div className="progress-title">{job.filename}</div>
      <div className="bar"><div style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
      <div className="progress-msg">
        <span>{STAGES[job.stage] ?? job.stage}</span>
        <span>{job.message && job.message !== STAGES[job.stage] ? job.message : ''}</span>
        <span>{Math.round(job.progress * 100)}%</span>
      </div>
    </div>
  )
}

export default function App() {
  const [jobId, setJobId] = useState<string | null>(() => new URLSearchParams(location.search).get('job'))
  const [pollNonce, setPollNonce] = useState(0)
  const { job, setJob, error } = useJobPolling(jobId, pollNonce)
  const [view, setView] = useState<ViewState>({
    mode: 'all', selected: null, explode: 6, showRoof: true, showRooms: true, showGlass: true, labels: true,
    cutH: { on: false, y: 0 }, cutV: { on: false, x: 0 },
  })
  const [tool, setTool] = useState<Tool>('orbit')
  const [measureMode, setMeasureMode] = useState<MeasureMode>('length')
  const [walkActive, setWalkActive] = useState(false)
  const exitWalk = useCallback(() => { setTool('orbit'); setWalkActive(false) }, [])
  const [settings, setSettings] = useState(false)
  const [editor, setEditor] = useState(false)
  const [query, setQuery] = useState('')
  const [focusRoom, setFocusRoom] = useState<FocusRoom | null>(null)
  // keep the last finished model on screen while a rebuild is running
  const [shown, setShown] = useState<Job | null>(null)
  useEffect(() => { if (job?.status === 'done') setShown(job) }, [job])

  const openJob = useCallback((id: string) => {
    setJobId(id)
    setShown(null)
    history.replaceState(null, '', `?job=${id}`)
  }, [])

  const r = shown?.result
  const floorsDesc = useMemo(() => [...(r?.floors ?? [])].sort((a, b) => b.elevation! - a.elevation!), [r])
  const selFloor = floorsDesc.find((f) => f.id === view.selected) ?? floorsDesc[floorsDesc.length - 1]
  const [yMin, yMax] = r?.height_range ?? [0, 10]
  const [xMin, xMax] = r?.extent?.x ?? [-60, 60]

  // default section heights once a model is shown
  useEffect(() => {
    if (!r) return
    setView((v) => ({
      ...v,
      cutH: { ...v.cutH, y: v.cutH.y || r.height_range[1] },
      cutV: { ...v.cutV, x: v.cutV.x || ((r.extent?.x[0] ?? 0) + (r.extent?.x[1] ?? 0)) / 2 },
    }))
  }, [r])

  const hits = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q || !r) return []
    return r.floors.flatMap((f) => f.rooms.filter((rm) => rm.name.toLowerCase().includes(q)).map((rm) => ({ f, rm }))).slice(0, 30)
  }, [query, r])

  const selectFloor = (id: string) =>
    setView((v) => ({ ...v, selected: id, mode: v.mode === 'all' ? 'isolate' : v.mode }))

  const rebuild = async (override: Record<string, unknown>) => {
    setSettings(false)
    try {
      setJob(await rebuildJob(job!.id, override))
      setPollNonce((n) => n + 1)   // restart polling
    } catch (e) {
      alert((e as Error).message)
    }
  }

  // the editor stays open during the rebuild and reloads the plan afterwards
  const applyEdits = (floorId: string, edits: FloorEdits) => rebuild({ edits: { [floorId]: edits } })

  const planCut = () => {
    if (!selFloor) return
    setView((v) => ({
      ...v, mode: v.mode === 'all' || v.mode === 'explode' ? 'below' : v.mode, selected: selFloor.id,
      cutH: { on: true, y: selFloor.elevation! + 1.2 },
    }))
  }

  const startWalk = () => {
    if (!selFloor) return
    setView((v) => ({ ...v, mode: 'isolate', selected: selFloor.id }))
    setTool('walk')
  }

  if (!jobId) return <Upload onJob={openJob} />

  const running = job && (job.status === 'queued' || job.status === 'running')

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span>DWG → 3D</span>
          <button className="ghost small" onClick={() => { setJobId(null); setShown(null); history.replaceState(null, '', '/') }}>
            Новый файл
          </button>
        </div>
        {job && <div className="file-name" title={job.filename}>{job.filename}</div>}
        {running && <Progress job={job} />}
        {job?.status === 'error' && (
          <div className="error-card"><b>Ошибка обработки</b><p>{job.error}</p></div>
        )}
        {error && <div className="error-card">{error}</div>}

        {r && (
          <>
            <div className="seg">
              {MODES.map((m) => (
                <button key={m.id} title={m.title} className={view.mode === m.id ? 'on' : ''}
                  onClick={() => setView((v) => ({
                    ...v, mode: m.id,
                    selected: v.selected ?? (m.id === 'isolate' || m.id === 'below' ? floorsDesc[floorsDesc.length - 1]?.id ?? null : null),
                  }))}>
                  {m.label}
                </button>
              ))}
            </div>
            {view.mode === 'explode' && (
              <label className="slider">
                <span>Разнос: {view.explode} м</span>
                <input type="range" min={1} max={20} step={0.5} value={view.explode}
                  onChange={(e) => setView((v) => ({ ...v, explode: Number(e.target.value) }))} />
              </label>
            )}

            <div className="search">
              <input placeholder="Поиск помещения…" value={query} onChange={(e) => setQuery(e.target.value)} />
              {hits.length > 0 && (
                <ul className="hits">
                  {hits.map(({ f, rm }) => (
                    <li key={rm.node} onClick={() => {
                      setView((v) => ({ ...v, selected: f.id, mode: 'isolate' }))
                      setFocusRoom({ node: rm.node, nonce: Date.now() })
                      setQuery('')
                    }}>
                      <b>{rm.name}</b><span>{f.name} · {rm.area.toFixed(1)} м²</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <h3 className="list-title">Этажи <span>{r.floors.length}</span></h3>
            <ul className="floors">
              {floorsDesc.map((f) => (
                <li key={f.id} className={view.selected === f.id && view.mode !== 'all' ? 'sel' : ''}
                  onClick={() => selectFloor(f.id)}>
                  <div className="f-name">{f.name}</div>
                  <div className="f-meta">
                    <span>{f.elevation! >= 0 ? '+' : ''}{f.elevation!.toFixed(2)} м</span>
                    <span>h {f.height!.toFixed(2)} м</span>
                    <span>{f.stats.rooms} пом.</span>
                  </div>
                </li>
              ))}
            </ul>

            <div className="toggles">
              <label><input type="checkbox" checked={view.showRoof} onChange={(e) => setView((v) => ({ ...v, showRoof: e.target.checked }))} /> Кровля</label>
              <label><input type="checkbox" checked={view.showRooms} onChange={(e) => setView((v) => ({ ...v, showRooms: e.target.checked }))} /> Помещения</label>
              <label><input type="checkbox" checked={view.showGlass} onChange={(e) => setView((v) => ({ ...v, showGlass: e.target.checked }))} /> Остекление</label>
              <label><input type="checkbox" checked={view.labels} onChange={(e) => setView((v) => ({ ...v, labels: e.target.checked }))} /> Подписи</label>
            </div>

            <h3 className="list-title">Разрезы</h3>
            <div className="cuts">
              <label className="cut-row">
                <input type="checkbox" checked={view.cutH.on} onChange={(e) => setView((v) => ({ ...v, cutH: { ...v.cutH, on: e.target.checked } }))} />
                <span>По высоте</span>
                <input type="range" min={yMin} max={yMax} step={0.05} value={view.cutH.y} disabled={!view.cutH.on}
                  onChange={(e) => setView((v) => ({ ...v, cutH: { ...v.cutH, y: Number(e.target.value) } }))} />
                <span className="val">{view.cutH.y.toFixed(1)}</span>
              </label>
              <label className="cut-row">
                <input type="checkbox" checked={view.cutV.on} onChange={(e) => setView((v) => ({ ...v, cutV: { ...v.cutV, on: e.target.checked } }))} />
                <span>Вертикальный</span>
                <input type="range" min={xMin} max={xMax} step={0.1} value={view.cutV.x} disabled={!view.cutV.on}
                  onChange={(e) => setView((v) => ({ ...v, cutV: { ...v.cutV, x: Number(e.target.value) } }))} />
                <span className="val">{view.cutV.x.toFixed(1)}</span>
              </label>
              <button className="small" onClick={planCut} title="Разрез выбранного этажа на высоте 1,2 м — как на плане">
                План-срез этажа
              </button>
            </div>

            <h3 className="list-title">Инструменты</h3>
            <div className="seg seg3">
              {TOOLS.map((t) => (
                <button key={t.id} title={t.title} className={tool === t.id ? 'on' : ''}
                  onClick={() => (t.id === 'walk' ? startWalk() : setTool(t.id))}>{t.label}</button>
              ))}
            </div>
            {tool === 'measure' && (
              <div className="seg seg2 sub-seg">
                <button className={measureMode === 'length' ? 'on' : ''} onClick={() => setMeasureMode('length')}>
                  ↔ Расстояние
                </button>
                <button className={measureMode === 'area' ? 'on' : ''} onClick={() => setMeasureMode('area')}>
                  ▱ Площадь
                </button>
              </div>
            )}

            <div className="actions">
              <button className="secondary" disabled={!!running || !selFloor} onClick={() => setEditor(true)}
                title="Исправить стены, проёмы и помещения на плане выбранного этажа">
                2D-редактор: {selFloor?.name ?? '—'}
              </button>
              <button className="secondary" disabled={!!running} onClick={() => setSettings(true)}>
                Этажи и слои…
              </button>
            </div>

            {r.exports && (
              <div className="exports">
                <span>Скачать:</span>
                {Object.entries(r.exports).map(([k, name]) => (
                  <a key={k} href={fileUrl(shown!.id, name, shown!.build)} download>{k.toUpperCase()}</a>
                ))}
              </div>
            )}
            {r.warnings.length > 0 && (
              <div className="warn-card">{r.warnings.map((w) => <p key={w}>⚠ {w}</p>)}</div>
            )}
            <div className="info">
              Единицы: {r.units} ({r.units_source}) · {r.triangles.toLocaleString('ru')} треуг. · {r.elapsed_s} с
            </div>
          </>
        )}
      </aside>
      <main className="stage">
        {shown?.model_url && r ? (
          <Suspense fallback={<div className="center-msg">Загрузка модели…</div>}>
            <Viewer key={shown.model_url} url={shown.model_url} result={r} view={view} tool={tool}
              focusRoom={focusRoom} measureMode={measureMode} onExitWalk={exitWalk} />
          </Suspense>
        ) : running ? (
          <div className="center-msg"><Progress job={job!} /></div>
        ) : null}
        {r && tool === 'walk' && !walkActive && (
          <div className="walk-overlay" onClick={() => {
            setWalkActive(true)
            try { void document.querySelector('canvas')?.requestPointerLock?.() } catch { /* drag-to-look fallback */ }
          }}>
            <div>
              <b>Прогулка: {selFloor?.name}</b>
              <p>Нажмите, чтобы начать. WASD / стрелки — ходьба, мышь (или перетаскивание) — обзор, Shift — быстрее, Esc — выход.</p>
            </div>
          </div>
        )}
        {r && tool === 'walk' && walkActive && (
          <div className="help">WASD — ходьба · мышь — обзор · Shift — быстрее · Esc — выход</div>
        )}
        {r && tool !== 'walk' && (
          <>
            <div className="legend-3d">
              <span><i style={{ background: '#ede8de' }} />стены</span>
              <span><i style={{ background: '#dbe3ed' }} />перегородки</span>
              <span><i style={{ background: '#a8805c' }} />двери</span>
              <span><i style={{ background: '#8cbff2' }} />остекление</span>
              <span><i style={{ background: '#c7bdad' }} />лестницы</span>
            </div>
            <div className="help">
              {tool === 'measure' && measureMode === 'length' ? 'Кликните две точки на модели · Esc — сброс'
                : tool === 'measure' ? 'Кликайте вершины контура · замкнуть: клик по первой точке, двойной клик или Enter · Backspace — убрать точку · Esc — сброс'
                : 'ЛКМ — вращение · ПКМ — панорама · колесо — зум · наведите на помещение'}
            </div>
          </>
        )}
        {editor && job && shown && selFloor && (
          <Editor2D key={selFloor.id} job={job.status === 'done' ? job : { ...shown, config: job.config }}
            floor={selFloor} busy={!!running} onApply={applyEdits} onClose={() => setEditor(false)} />
        )}
      </main>
      {settings && job?.result && <Settings job={job} onRebuild={rebuild} onClose={() => setSettings(false)} />}
    </div>
  )
}
