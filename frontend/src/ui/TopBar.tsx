import { useEffect, useMemo, useState } from 'react'
import { listJobs, type FloorMeta, type JobSummary, type Result, type RoomMeta } from '../api'
import { jobColor } from '../state'
import { Icon } from './icons'
import { useMenu } from './menuCtx'

/** Top centre: current building chip (switch buildings) + search over rooms and buildings. */
export default function TopBar({ jobId, name, result, onOpenJob, onNewFile, onRoom }: {
  jobId: string
  name: string
  result: Result | undefined
  onOpenJob: (id: string) => void
  onNewFile: () => void
  onRoom: (f: FloorMeta, r: RoomMeta) => void
}) {
  const chip = useMenu('buildings')
  const search = useMenu('search')
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [q, setQ] = useState('')
  useEffect(() => {
    if (!chip.isOpen && !search.isOpen) return
    listJobs().then((j) => setJobs(j.filter((x) => x.status === 'done'))).catch(() => {})
  }, [chip.isOpen, search.isOpen])

  const typeLabel = useMemo(() => new Map((result?.room_types ?? []).map((t) => [t.type, t.label])), [result])
  const hits = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return { rooms: [], buildings: [] }
    const rooms = (result?.floors ?? []).flatMap((f) => f.rooms
      .filter((r) => (r.name || '').toLowerCase().includes(s) || (typeLabel.get(r.type ?? '') ?? '').toLowerCase().includes(s))
      .map((r) => ({ f, r }))).slice(0, 30)
    const buildings = jobs.filter((j) => j.id !== jobId && (j.name + ' ' + j.filename).toLowerCase().includes(s)).slice(0, 8)
    return { rooms, buildings }
  }, [q, result, jobs, jobId, typeLabel])

  return (
    <div className="topbar">
      <div className="menu-root chip-wrap">
        <button className="chip" onClick={chip.toggle} title="Выбрать здание">
          <i style={{ background: jobColor(jobId) }} />
          <span>{name}</span>
          <Icon name="chevron" size={14} />
        </button>
        {chip.isOpen && (
          <div className="menu drop-left buildings" role="menu">
            <div className="menu-title">Здания</div>
            {jobs.map((j) => (
              <button key={j.id} className={`menu-item${j.id === jobId ? ' on' : ''}`} onClick={() => { chip.close(); onOpenJob(j.id) }}>
                <i className="dot" style={{ background: jobColor(j.id) }} />
                <span className="grow">{j.name}</span>
                <small>{j.floors} эт.</small>
              </button>
            ))}
            <button className="menu-item accent" onClick={() => { chip.close(); onNewFile() }}>
              <Icon name="upload" size={15} /> Загрузить новый чертёж…
            </button>
          </div>
        )}
      </div>
      <div className="menu-root search-wrap">
        <Icon name="search" size={16} className="search-ico" />
        <input value={q} placeholder="Поиск помещения или здания" onFocus={search.open}
          onChange={(e) => { setQ(e.target.value); search.open() }} />
        {search.isOpen && (hits.rooms.length > 0 || hits.buildings.length > 0) && (
          <div className="menu drop-left hits" role="listbox">
            {hits.rooms.length > 0 && <div className="menu-title">Помещения</div>}
            {hits.rooms.map(({ f, r }) => (
              <button key={r.node} className="menu-item hit" onClick={() => { search.close(); setQ(''); onRoom(f, r) }}>
                <b>{r.name || typeLabel.get(r.type ?? '') || 'Помещение'}</b>
                <span>{f.name} · {r.area.toFixed(1)} м²</span>
              </button>
            ))}
            {hits.buildings.length > 0 && <div className="menu-title">Здания</div>}
            {hits.buildings.map((j) => (
              <button key={j.id} className="menu-item hit" onClick={() => { search.close(); setQ(''); onOpenJob(j.id) }}>
                <b><i className="dot" style={{ background: jobColor(j.id) }} /> {j.name}</b>
                <span>{j.floors} этажей</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
