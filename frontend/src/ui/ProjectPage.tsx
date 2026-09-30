import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addMember, copyLayer, createLayer, createShare, deleteDrawing, deleteLayer, deleteProject, getProject, layerKinds, listLayers,
  listMembers, listShares, removeMember, renameDrawing, revokeShare, setMemberRole, updateLayer, updateProject,
  uploadFile, uploadRevision,
  type JobSummary, type Layer, type LayerKindInfo, type Member, type Project, type ProjectRole, type ShareLink,
} from '../api'
import { jobColor } from '../state'
import { hasProjectRole, me, PROJECT_ROLE_NAMES, setProjectRole } from '../session'
import { fmtDate, plural } from './format'
import { PageHead } from './Projects'
import Report from './Report'
import Compare from './Compare'
import { variantGroup, variantGroups } from '../furniture/layers'
import { Icon } from './icons'

const STATUS: Record<JobSummary['status'], string> = { queued: 'в очереди', running: 'обрабатывается', done: 'готов', error: 'ошибка' }
const ROLES: ProjectRole[] = ['viewer', 'editor', 'owner']

/** A project: its drawings, layers, members and share links. */
export default function ProjectPage({ pid }: { pid: string }) {
  const [p, setP] = useState<Project | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const reload = useCallback(() => setNonce((n) => n + 1), [])
  useEffect(() => {
    let alive = true
    let timer: number | undefined
    const tick = () => getProject(pid).then((x) => {
      if (!alive) return
      setProjectRole(x.my_role)
      setP(x)
      setErr(null)
      if (x.drawings.some((d) => d.status === 'queued' || d.status === 'running')) timer = window.setTimeout(tick, 1500)
    }).catch((e) => { if (alive) setErr((e as Error).message) })
    tick()
    return () => { alive = false; window.clearTimeout(timer) }
  }, [pid, nonce])
  const [report, setReport] = useState(false)

  if (!p) {
    return (
      <div className="page"><PageHead /><main className="page-body">
        {err ? <div className="card empty"><p className="error">{err}</p><a href="#/">← К проектам</a></div> : <p className="hint">Загрузка…</p>}
      </main></div>
    )
  }
  const editor = hasProjectRole('editor')
  const owner = hasProjectRole('owner')
  return (
    <div className="page">
      <PageHead>{!me?.guest && <a className="crumb" href="#/">← Проекты</a>}</PageHead>
      <main className="page-body">
        <ProjectTitle p={p} editable={editor} onSaved={setP} />
        {err && <p className="error">{err}</p>}
        <Drawings p={p} editable={editor} onChanged={reload} />
        <Layers pid={pid} editable={editor} />
        <section className="card">
          <div className="sec-head">
            <h2>Спецификация</h2>
            <button onClick={() => setReport(true)}>Открыть…</button>
          </div>
          <p className="hint">Оборудование из слоёв проекта: по этажам всех чертежей или по помещениям, по всему проекту или одному слою; выгрузка в Excel.</p>
        </section>
        {!me?.guest && <Members pid={pid} owner={owner} />}
        {owner && <Shares p={p} />}
        {owner && <Danger p={p} />}
      </main>
      {report && <Report projectId={pid} onClose={() => setReport(false)} />}
    </div>
  )
}

function ProjectTitle({ p, editable, onSaved }: { p: Project; editable: boolean; onSaved: (p: Project) => void }) {
  const [edit, setEdit] = useState(false)
  const [name, setName] = useState(p.name)
  const [descr, setDescr] = useState(p.description)
  const [err, setErr] = useState<string | null>(null)
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      onSaved(await updateProject(p.id, { name: name.trim(), description: descr.trim() }))
      setEdit(false)
    } catch (ex) { setErr((ex as Error).message) }
  }
  if (edit) {
    return (
      <form className="page-title edit" onSubmit={save}>
        <input className="h1" autoFocus value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        <textarea rows={2} value={descr} placeholder="Описание" maxLength={5000} onChange={(e) => setDescr(e.target.value)} />
        {err && <p className="error">{err}</p>}
        <div className="row-actions">
          <button type="button" onClick={() => { setEdit(false); setName(p.name); setDescr(p.description) }}>Отмена</button>
          <button className="primary" disabled={!name.trim()}>Сохранить</button>
        </div>
      </form>
    )
  }
  return (
    <div className="page-title">
      <div className="grow">
        <h1>{p.name}</h1>
        {p.description && <p className="descr">{p.description}</p>}
      </div>
      {p.my_role && <span className="badge">{PROJECT_ROLE_NAMES[p.my_role]}</span>}
      {editable && <button className="ghost" title="Переименовать" onClick={() => setEdit(true)}><Icon name="edit" size={16} /></button>}
    </div>
  )
}

// ------------------------------------------------------------ drawings ---
function Drawings({ p, editable, onChanged }: { p: Project; editable: boolean; onChanged: () => void }) {
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const upload = async (files: FileList | File[] | null | undefined) => {
    const list = [...(files ?? [])].filter((f) => /\.(dwg|dxf)$/i.test(f.name))
    if (!list.length) return setErr('Нужен файл .dwg или .dxf')
    setErr(null)
    for (const f of list) {
      setBusy(`Загрузка ${f.name}…`)
      try { await uploadFile(f, p.id) } catch (e) { setErr(`${f.name}: ${(e as Error).message}`) }
    }
    setBusy(null)
    onChanged()
  }
  return (
    <section className="card">
      <div className="sec-head">
        <h2>Чертежи <small>{p.drawings.length}</small></h2>
        {editable && <button className="primary" onClick={() => input.current?.click()}><Icon name="upload" size={15} /> Загрузить DWG / DXF</button>}
        <input ref={input} type="file" accept=".dwg,.dxf" multiple hidden onChange={(e) => { upload(e.target.files); e.target.value = '' }} />
      </div>
      {editable && (
        <div className={`drop-strip ${drag ? 'drag' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files) }}
          onClick={() => input.current?.click()}>
          {busy ?? 'Перетащите сюда файлы чертежей: каждый корпус или раздел — отдельный чертёж'}
        </div>
      )}
      {err && <p className="error">{err}</p>}
      {!p.drawings.length && <p className="hint">Чертежей пока нет.{editable ? ' Загрузите поэтажные планы — стены, окна, двери, лестницы и этажи распознаются автоматически.' : ''}</p>}
      <ul className="rows">
        {p.drawings.map((d) => <DrawingRow key={d.id} d={d} editable={editable} onChanged={onChanged} />)}
      </ul>
    </section>
  )
}

function DrawingRow({ d, editable, onChanged }: { d: JobSummary; editable: boolean; onChanged: () => void }) {
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(d.name)
  const [err, setErr] = useState<string | null>(null)
  const rev = useRef<HTMLInputElement>(null)
  const running = d.status === 'queued' || d.status === 'running'
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null)
    try { await fn(); onChanged() } catch (e) { setErr((e as Error).message) }
  }
  return (
    <li className="row">
      <i className="dot" style={{ background: jobColor(d.id) }} />
      <div className="grow">
        {renaming ? (
          <form className="inline" onSubmit={(e) => { e.preventDefault(); act(() => renameDrawing(d.id, name.trim())).then(() => setRenaming(false)) }}>
            <input autoFocus value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
            <button className="small primary" disabled={!name.trim()}>OK</button>
            <button type="button" className="small" onClick={() => setRenaming(false)}>Отмена</button>
          </form>
        ) : (
          <>
            {d.status === 'done' ? <a href={`#/f/${d.id}`}><b>{d.name}</b></a> : <b>{d.name}</b>}
            <small>{d.filename} · {(d.size / 1e6).toFixed(1)} МБ{d.build > 1 ? ` · сборка ${d.build}` : ''}</small>
          </>
        )}
        {running && <div className="bar mini"><div style={{ width: `${Math.round(d.progress * 100)}%` }} /></div>}
        {err && <small className="error">{err}</small>}
      </div>
      <span className={`badge st-${d.status}`}>{STATUS[d.status]}{running ? ` ${Math.round(d.progress * 100)}%` : ''}</span>
      <small className="nowrap">{d.status === 'done' ? `${d.floors} эт.` : ''}</small>
      <small className="nowrap">{fmtDate(d.updated)}</small>
      <div className="row-actions">
        {d.status === 'done' && <a className="button small primary" href={`#/f/${d.id}`}>Открыть</a>}
        {editable && !renaming && (
          <>
            <button className="small" onClick={() => setRenaming(true)} title="Переименовать">Имя</button>
            <button className="small" disabled={running} onClick={() => rev.current?.click()}
              title="Загрузить новую версию файла: этажи, правки, мебель и метки перейдут на неё">Новая ревизия</button>
            <input ref={rev} type="file" accept=".dwg,.dxf" hidden onChange={(e) => {
              const f = e.target.files?.[0]
              e.target.value = ''
              if (f) act(() => uploadRevision(d.id, f))
            }} />
            <button className="small danger" disabled={running} onClick={() => {
              if (confirm(`Удалить чертёж «${d.name}» вместе с расстановкой на нём?`)) act(() => deleteDrawing(d.id))
            }}>Удалить</button>
          </>
        )}
      </div>
    </li>
  )
}

// -------------------------------------------------------------- layers ---
function Layers({ pid, editable }: { pid: string; editable: boolean }) {
  const [layers, setLayers] = useState<Layer[] | null>(null)
  const [kinds, setKinds] = useState<LayerKindInfo[]>([])
  const [kind, setKind] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(() => { listLayers(pid).then(setLayers).catch((e) => setErr((e as Error).message)) }, [pid])
  useEffect(() => { load(); layerKinds().then((k) => { setKinds(k.kinds); setKind(k.kinds[0]?.kind ?? '') }).catch(() => {}) }, [load])
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null)
    try { await fn() } catch (e) { setErr((e as Error).message) }
    load()
  }
  const kindName = (k: string) => kinds.find((x) => x.kind === k)?.name ?? k
  const [cmp, setCmp] = useState<[string, string] | null>(null)
  const groups = variantGroups(layers ?? [])
  const groupOf = (l: Layer) => groups.find((g) => g.some((x) => x.id === l.id)) ?? null
  return (
    <section className="card">
      <div className="sec-head">
        <h2>Слои <small>{layers?.length ?? ''}</small></h2>
        {editable && kinds.length > 0 && (
          <span className="inline">
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {kinds.map((k) => <option key={k.kind} value={k.kind}>{k.name}</option>)}
            </select>
            <button onClick={() => act(() => createLayer(pid, kind))}><Icon name="plus" size={14} /> Слой</button>
          </span>
        )}
      </div>
      <p className="hint">Слои — наборы объектов поверх чертежей: мебель, видеонаблюдение и другие. Объекты слоя могут стоять на любом чертеже проекта; в просмотре слои включаются и выключаются, а новые предметы ставятся в выбранный слой.</p>
      {err && <p className="error">{err}</p>}
      {layers && !layers.length && <p className="hint">Слоёв пока нет: первый появится, когда на план поставят предмет из каталога, или создайте его здесь.</p>}
      <ul className="rows">
        {(layers ?? []).map((l) => (
          <LayerRow key={l.id} l={l} kindName={kindName(l.kind)} editable={editable}
            variantOf={(() => { const g = groupOf(l); return g ? g.find((x) => x.id === variantGroup(l))?.name ?? g[0].name : null })()}
            onCopy={() => act(() => copyLayer(pid, l.id))}
            onCompare={groupOf(l) ? () => { const g = groupOf(l)!; setCmp([g[0].id === l.id ? g[1].id : g[0].id, l.id]) } : null}
            onPatch={(patch) => act(() => updateLayer(pid, l.id, { ...patch, version: l.version }))}
            onDelete={() => {
              if (confirm(`Удалить слой «${l.name}»${l.count ? ` и ${l.count} ${plural(l.count ?? 0, 'объект', 'объекта', 'объектов')} в нём` : ''}?`)) act(() => deleteLayer(pid, l.id))
            }} />
        ))}
      </ul>
      {cmp && <Compare projectId={pid} layers={layers ?? []} a={cmp[0]} b={cmp[1]} onClose={() => setCmp(null)} />}
    </section>
  )
}

function LayerRow({ l, kindName, editable, variantOf, onCopy, onCompare, onPatch, onDelete }: {
  l: Layer; kindName: string; editable: boolean; variantOf: string | null; onCopy: () => void; onCompare: (() => void) | null
  onPatch: (p: Partial<Layer>) => void; onDelete: () => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(l.name)
  return (
    <li className="row">
      <Icon name="layers" size={16} />
      <div className="grow">
        {renaming ? (
          <form className="inline" onSubmit={(e) => { e.preventDefault(); onPatch({ name: name.trim() }); setRenaming(false) }}>
            <input autoFocus value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
            <button className="small primary" disabled={!name.trim()}>OK</button>
            <button type="button" className="small" onClick={() => setRenaming(false)}>Отмена</button>
          </form>
        ) : <><b>{l.name}</b><small>{kindName} · {l.count ?? 0} {plural(l.count ?? 0, 'объект', 'объекта', 'объектов')}
          {variantOf && <span className="variant-of"> · варианты «{variantOf}»</span>}</small></>}
      </div>
      {onCompare && <button className="small" onClick={onCompare} title="Что отличается от другого варианта: предметы, стоимость">Сравнить…</button>}
      {l.locked && <span className="badge">заблокирован</span>}
      {!l.visible && <span className="badge">скрыт</span>}
      {editable && !renaming && (
        <div className="row-actions">
          <button className="small" onClick={() => setRenaming(true)}>Имя</button>
          <button className="small" title="Копия слоя со всеми объектами — вариант, который можно менять и сравнивать с исходным" onClick={onCopy}>Вариант</button>
          <button className="small" title="Показывать ли слой при открытии чертежа" onClick={() => onPatch({ visible: !l.visible })}>{l.visible ? 'Скрыть' : 'Показать'}</button>
          <button className="small" title="Заблокированный слой нельзя менять" onClick={() => onPatch({ locked: !l.locked })}>{l.locked ? 'Разблокировать' : 'Заблокировать'}</button>
          <button className="small danger" disabled={l.locked} onClick={onDelete}>Удалить</button>
        </div>
      )}
    </li>
  )
}

// ------------------------------------------------------------- members ---
function Members({ pid, owner }: { pid: string; owner: boolean }) {
  const [list, setList] = useState<Member[] | null>(null)
  const [who, setWho] = useState('')
  const [role, setRole] = useState<ProjectRole>('editor')
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(() => { listMembers(pid).then(setList).catch((e) => setErr((e as Error).message)) }, [pid])
  useEffect(load, [load])
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null)
    try { await fn(); return true } catch (e) { setErr((e as Error).message); return false } finally { load() }
  }
  return (
    <section className="card">
      <div className="sec-head"><h2>Участники <small>{list?.length ?? ''}</small></h2></div>
      {owner && (
        <form className="inline add-member" onSubmit={async (e) => {
          e.preventDefault()
          if (await act(() => addMember(pid, who.trim(), role))) setWho('')
        }}>
          <input value={who} placeholder="Логин или e-mail" onChange={(e) => setWho(e.target.value)} />
          <select value={role} onChange={(e) => setRole(e.target.value as ProjectRole)}>
            {ROLES.map((r) => <option key={r} value={r}>{PROJECT_ROLE_NAMES[r]}</option>)}
          </select>
          <button className="primary" disabled={!who.trim()}>Добавить</button>
        </form>
      )}
      {owner && <p className="hint">Добавить можно того, кто уже входил в систему, — по логину или e-mail. Если человек ещё не входил, укажите его e-mail: приглашение сработает при первом входе. Учётные записи заводит администратор в Keycloak.</p>}
      {err && <p className="error">{err}</p>}
      <ul className="rows">
        {(list ?? []).map((m) => (
          <li key={m.id} className="row">
            <div className="grow">
              <b>{m.user?.name ?? m.email}</b>
              <small>{m.user ? `${m.user.login}${m.email ? ` · ${m.email}` : ''}` : 'приглашён, ещё не входил'}</small>
            </div>
            {owner ? (
              <select value={m.role} onChange={(e) => act(() => setMemberRole(pid, m.id, e.target.value as ProjectRole))}>
                {ROLES.map((r) => <option key={r} value={r}>{PROJECT_ROLE_NAMES[r]}</option>)}
              </select>
            ) : <span className="badge">{m.role_name}</span>}
            {owner && <button className="small danger" onClick={() => {
              if (confirm(`Убрать ${m.user?.name ?? m.email} из проекта?`)) act(() => removeMember(pid, m.id))
            }}>Убрать</button>}
          </li>
        ))}
      </ul>
    </section>
  )
}

// --------------------------------------------------------- share links ---
function Shares({ p }: { p: Project }) {
  const [list, setList] = useState<ShareLink[] | null>(null)
  const [layers, setLayers] = useState<Layer[]>([])
  const [form, setForm] = useState(false)
  const [name, setName] = useState('')
  const [days, setDays] = useState<string>('30')
  const [drawings, setDrawings] = useState<Set<string> | null>(null)
  const [lset, setLset] = useState<Set<string> | null>(null)
  const [made, setMade] = useState<ShareLink | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(() => { listShares(p.id).then(setList).catch((e) => setErr((e as Error).message)) }, [p.id])
  useEffect(() => { load(); listLayers(p.id).then(setLayers).catch(() => {}) }, [load, p.id])
  const toggle = (set: Set<string> | null, all: string[], id: string): Set<string> | null => {
    const s = new Set(set ?? all)
    if (s.has(id)) s.delete(id)
    else s.add(id)
    return s.size === all.length ? null : s
  }
  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    try {
      const x = await createShare(p.id, {
        name: name.trim(), days: days ? Number(days) : null,
        drawings: drawings ? [...drawings] : null, layers: lset ? [...lset] : null,
      })
      setMade(x)
      setForm(false)
      setName('')
      setDrawings(null)
      setLset(null)
    } catch (ex) { setErr((ex as Error).message) }
    load()
  }
  const scope = (x: ShareLink) => [
    x.drawings ? `чертежей: ${x.drawings.length}` : 'все чертежи',
    x.layers ? `слоёв: ${x.layers.length}` : 'все слои',
  ].join(', ')
  const dnames = p.drawings.map((d) => d.id)
  const lids = layers.map((l) => l.id)
  return (
    <section className="card">
      <div className="sec-head">
        <h2>Ссылки для просмотра</h2>
        {!form && <button onClick={() => { setForm(true); setMade(null) }}><Icon name="plus" size={14} /> Ссылка</button>}
      </div>
      <p className="hint">Ссылка открывает проект без учётной записи — только для просмотра (например, заказчику). Можно ограничить чертежи и слои и задать срок; ссылку можно отозвать.</p>
      {made?.url && (
        <div className="made-link">
          <span>Ссылка создана — скопируйте её сейчас, позже она не показывается:</span>
          <span className="inline">
            <input readOnly value={made.url} onFocus={(e) => e.target.select()} />
            <button onClick={() => navigator.clipboard?.writeText(made.url!)}>Копировать</button>
          </span>
        </div>
      )}
      {form && (
        <form className="share-form" onSubmit={create}>
          <label>Для кого <input value={name} maxLength={200} placeholder="Например, «Заказчик»" onChange={(e) => setName(e.target.value)} /></label>
          <label>Срок
            <select value={days} onChange={(e) => setDays(e.target.value)}>
              <option value="7">7 дней</option><option value="30">30 дней</option><option value="90">90 дней</option>
              <option value="365">год</option><option value="">бессрочно</option>
            </select>
          </label>
          {p.drawings.length > 1 && (
            <fieldset><legend>Чертежи</legend>
              {p.drawings.map((d) => (
                <label key={d.id} className="check"><input type="checkbox" checked={!drawings || drawings.has(d.id)}
                  onChange={() => setDrawings(toggle(drawings, dnames, d.id))} /> {d.name}</label>
              ))}
            </fieldset>
          )}
          {layers.length > 0 && (
            <fieldset><legend>Слои</legend>
              {layers.map((l) => (
                <label key={l.id} className="check"><input type="checkbox" checked={!lset || lset.has(l.id)}
                  onChange={() => setLset(toggle(lset, lids, l.id))} /> {l.name}</label>
              ))}
            </fieldset>
          )}
          <div className="row-actions">
            <button type="button" onClick={() => setForm(false)}>Отмена</button>
            <button className="primary" disabled={(drawings?.size ?? 1) === 0}>Создать ссылку</button>
          </div>
        </form>
      )}
      {err && <p className="error">{err}</p>}
      <ul className="rows">
        {(list ?? []).map((x) => (
          <li key={x.id} className={`row${x.active ? '' : ' muted'}`}>
            <div className="grow">
              <b>{x.name || 'Без названия'}</b>
              <small>{scope(x)} · {x.revoked ? 'отозвана' : x.expires ? `${x.active ? 'до' : 'истекла'} ${fmtDate(x.expires)}` : 'бессрочно'}
                {x.last_used ? ` · открывали ${fmtDate(x.last_used)}` : ' · не открывали'}</small>
            </div>
            {x.active && <button className="small danger" onClick={() => {
              if (confirm('Отозвать ссылку? Открыть проект по ней больше не получится.')) revokeShare(p.id, x.id).then(load).catch((e) => setErr((e as Error).message))
            }}>Отозвать</button>}
          </li>
        ))}
      </ul>
    </section>
  )
}

function Danger({ p }: { p: Project }) {
  const [err, setErr] = useState<string | null>(null)
  return (
    <section className="card danger-zone">
      <div className="sec-head">
        <h2>Удаление проекта</h2>
        <button className="danger" onClick={async () => {
          if (prompt(`Проект «${p.name}» со всеми чертежами и слоями будет удалён. Введите его название, чтобы подтвердить:`) !== p.name) return
          try { await deleteProject(p.id); location.hash = '#/' } catch (e) { setErr((e as Error).message) }
        }}>Удалить проект…</button>
      </div>
      {err && <p className="error">{err}</p>}
    </section>
  )
}
