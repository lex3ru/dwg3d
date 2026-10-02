import type { Job } from '../api'

const STAGES: Record<string, string> = {
  queued: 'В очереди', start: 'Запуск', convert: 'Конвертация DWG → DXF', read: 'Чтение чертежа',
  analyze: 'Поиск этажей', geometry: 'Построение геометрии', mesh: 'Построение 3D',
  export: 'Экспорт', done: 'Готово', error: 'Ошибка',
}

export default function Progress({ job }: { job: Job }) {
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
