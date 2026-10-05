import { Upload, UserPlus } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPerson, importPeople, leavePerson, linkPerson, listPeople, type ImportReport, type Person } from '../api'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { useEvents } from '../stream'

/** The directory of people: one for the organisation, kept by administrators of buildings. */
export function People() {
  const [items, setItems] = useState<Person[]>([])
  const [q, setQ] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [report, setReport] = useState<ImportReport | null>(null)
  const picker = useRef<HTMLInputElement>(null)

  const load = useCallback(() => { listPeople(q).then(p => { setItems(p); setError(null) }, (e: Error) => setError(e.message)) }, [q])
  useEffect(load, [load])
  useEvents(event => { if (event.type.startsWith('people.')) load() })
  const act = (work: Promise<unknown>) => work.then(load, (e: Error) => setError(e.message))

  return (
    <section>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Люди</h1>
        <Input className="h-8 w-56" placeholder="ФИО или почта" aria-label="Поиск человека" value={q} onChange={e => setQ(e.target.value)} />
        <Button size="sm" variant="outline" onClick={() => setAdding(true)}><UserPlus className="size-4" /> Добавить</Button>
        <Button size="sm" variant="outline" onClick={() => picker.current?.click()}><Upload className="size-4" /> Из Excel</Button>
        <input ref={picker} type="file" accept=".xlsx" className="hidden" data-testid="people-file"
          onChange={e => {
            const file = e.target.files?.[0]
            if (file) importPeople(file).then(r => { setReport(r); load() }, (ex: Error) => setError(ex.message))
            e.target.value = ''
          }} />
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        Справочник общий для организации. Права выдаются людям из него — в разделе «Доступ». Excel: столбцы ФИО, Должность, Подразделение, Почта, Телефон.
      </p>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {report && (
        <div className="mt-3 rounded-lg border bg-card p-3 text-sm" data-testid="import-report">
          Добавлено: {report.created} · изменено: {report.updated} · без изменений: {report.unchanged}
          {report.errors.length > 0 && (
            <ul className="mt-1 text-destructive">
              {report.errors.map(e => <li key={e.row}>Строка {e.row}: {e.message}</li>)}
            </ul>
          )}
        </div>
      )}
      {adding && <NewPerson onDone={() => { setAdding(false); load() }} />}
      {items.length === 0 ? (
        <p className="mt-6 text-sm text-muted-foreground">{q ? 'Никого не найдено.' : 'В справочнике пока никого нет.'}</p>
      ) : (
        <ul className="mt-4 divide-y rounded-lg border bg-card text-sm" data-testid="people">
          {items.map(p => (
            <li key={p.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2" data-person={p.full_name}>
              <div className="min-w-40 flex-1">
                <div className="font-medium">{p.full_name}</div>
                <div className="text-xs text-muted-foreground">{[p.position, p.department, p.email].filter(Boolean).join(' · ')}</div>
              </div>
              {p.linked ? <Badge variant="success">есть учётная запись</Badge> : <LinkAccount onLink={sub => act(linkPerson(p.id, sub))} />}
              <Button variant="ghost" size="sm" title="Человек выбыл: все его права будут отозваны"
                onClick={() => { if (confirm(`Отметить, что «${p.full_name}» выбыл? Все его права будут отозваны.`)) act(leavePerson(p.id)) }}>
                Выбыл
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** The account links itself on the first sign-in, by the e-mail; by hand — when that cannot work. */
function LinkAccount({ onLink }: { onLink: (sub: string) => void }) {
  const [open, setOpen] = useState(false)
  const [sub, setSub] = useState('')
  if (!open) {
    return <Button variant="ghost" size="sm" title="Свяжется сама при первом входе, если почта совпадает" onClick={() => setOpen(true)}>Связать вручную</Button>
  }
  return (
    <form className="flex gap-1" onSubmit={e => { e.preventDefault(); if (sub.trim()) onLink(sub.trim()) }}>
      <Input className="h-7 w-52 text-xs" placeholder="Идентификатор учётной записи (Keycloak)" aria-label="Идентификатор учётной записи"
        value={sub} onChange={e => setSub(e.target.value)} autoFocus />
      <Button type="submit" size="sm">Связать</Button>
    </form>
  )
}

function NewPerson({ onDone }: { onDone: () => void }) {
  const [v, setV] = useState({ full_name: '', position: '', department: '', email: '' })
  const [error, setError] = useState<string | null>(null)
  const field = (key: keyof typeof v, label: string, required = false) => (
    <label className="grid gap-1 text-sm">{label}
      <Input value={v[key]} required={required} onChange={e => setV({ ...v, [key]: e.target.value })} />
    </label>
  )
  return (
    <form className="mt-4 grid max-w-lg gap-2 rounded-lg border bg-card p-4"
      onSubmit={e => {
        e.preventDefault()
        createPerson({ ...v, email: v.email.trim() || null }).then(onDone, (ex: Error) => setError(ex.message))
      }}>
      {field('full_name', 'ФИО', true)}
      {field('position', 'Должность')}
      {field('department', 'Подразделение')}
      {field('email', 'Почта — по ней учётная запись свяжется при первом входе')}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="mt-1 flex gap-2">
        <Button type="submit" disabled={!v.full_name.trim()}>Добавить</Button>
        <Button type="button" variant="ghost" onClick={onDone}>Отмена</Button>
      </div>
    </form>
  )
}
