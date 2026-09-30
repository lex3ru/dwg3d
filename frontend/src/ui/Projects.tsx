import { useEffect, useState } from 'react'
import { createProject, listProjects, type Project } from '../api'
import { can, me, PROJECT_ROLE_NAMES, signOut } from '../session'
import CatalogEditor from './CatalogEditor'
import { fmtDate, plural } from './format'
import { Icon } from './icons'

/** The header of the project pages: the app, the user, sign-out. */
export function PageHead({ children }: { children?: React.ReactNode }) {
  const [catalog, setCatalog] = useState(false)
  return (
    <header className="page-head">
      <a className="brand-link" href="#/">Поэтажные планы → 3D</a>
      <div className="grow">{children}</div>
      {can('catalog_admin') && <button className="ghost" onClick={() => setCatalog(true)}>Каталог оборудования</button>}
      {me?.auth && !me.guest && (
        <div className="page-user">
          <span><b>{me.name}</b><small>{me.login}{me.role !== 'user' ? ` · ${me.role_name}` : ''}</small></span>
          <button className="small" onClick={signOut}>Выйти</button>
        </div>
      )}
      {me?.guest && <span className="badge">просмотр по ссылке</span>}
      {catalog && <CatalogEditor onClose={() => setCatalog(false)} onChanged={() => {}} />}
    </header>
  )
}

/** Start page: the projects the user may open, and a new one. */
export default function Projects() {
  const [list, setList] = useState<Project[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [descr, setDescr] = useState('')
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')
  useEffect(() => { listProjects().then(setList).catch((e) => setErr((e as Error).message)) }, [])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      const p = await createProject(name.trim(), descr.trim())
      location.hash = `#/p/${p.id}`
    } catch (ex) {
      setErr((ex as Error).message)
      setBusy(false)
    }
  }
  const shown = (list ?? []).filter((p) => !q || `${p.name} ${p.description}`.toLowerCase().includes(q.toLowerCase()))

  return (
    <div className="page">
      <PageHead />
      <main className="page-body">
        <div className="page-title">
          <h1>Проекты</h1>
          {list && list.length > 5 && (
            <input className="filter" placeholder="Поиск проекта" value={q} onChange={(e) => setQ(e.target.value)} />
          )}
          {!me?.guest && <button className="primary" onClick={() => setCreating(true)}><Icon name="plus" size={15} /> Новый проект</button>}
        </div>
        {creating && (
          <form className="card new-project" onSubmit={create}>
            <label>Название
              <input autoFocus value={name} maxLength={200} placeholder="Например, «Медцентр на Ленина»" onChange={(e) => setName(e.target.value)} />
            </label>
            <label>Описание <small>(необязательно)</small>
              <textarea rows={2} value={descr} maxLength={5000} onChange={(e) => setDescr(e.target.value)} />
            </label>
            <div className="row-actions">
              <button type="button" onClick={() => setCreating(false)}>Отмена</button>
              <button className="primary" disabled={busy || !name.trim()}>{busy ? 'Создание…' : 'Создать'}</button>
            </div>
            <p className="hint">Проект — папка для всего, что относится к объекту: чертежи корпусов и этажей, слои мебели, видеонаблюдения, маршрутов; участники и ссылки для заказчика.</p>
          </form>
        )}
        {err && <p className="error">{err}</p>}
        {!list && !err && <p className="hint">Загрузка…</p>}
        {list && !list.length && !creating && (
          <div className="card empty">
            <p>Проектов пока нет.</p>
            {!me?.guest && <p className="hint">Создайте проект и загрузите в него чертёж DWG или DXF. Проекты других пользователей видны, когда вас добавят участником.</p>}
          </div>
        )}
        <ul className="proj-list">
          {shown.map((p) => {
            const running = p.drawings.filter((d) => d.status === 'queued' || d.status === 'running').length
            return (
              <li key={p.id}>
                <a className="card proj" href={`#/p/${p.id}`}>
                  <b>{p.name}</b>
                  {p.description && <span className="descr">{p.description}</span>}
                  <span className="meta">
                    <span>{p.drawings.length} {plural(p.drawings.length, 'чертёж', 'чертежа', 'чертежей')}</span>
                    {running > 0 && <span className="badge busy">обрабатывается {running}</span>}
                    {p.my_role && <span className="badge">{PROJECT_ROLE_NAMES[p.my_role]}</span>}
                    <span className="grow" />
                    <span>{fmtDate(p.updated)}</span>
                  </span>
                </a>
              </li>
            )
          })}
        </ul>
      </main>
    </div>
  )
}
