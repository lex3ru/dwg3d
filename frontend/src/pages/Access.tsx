import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  createGrant, listGrants, listPeople, peopleByIds, revokeGrant,
  type Building, type Grant, type Person, type Role, type TreeFloor,
} from '../api'
import { Button } from '../components/ui/button'
import { useEvents } from '../stream'

const ROLES: Record<Role, string> = { viewer: 'просмотр', responsible: 'ответственный', admin: 'администратор' }
const select = 'h-8 rounded-md border bg-card px-2 text-sm'

/** Who may do what in the building: rights are given to people of the directory, for an area. */
export function Access({ building, floors }: { building: Building; floors: TreeFloor[] }) {
  const [grants, setGrants] = useState<Grant[]>([])
  const [names, setNames] = useState<Record<string, string>>({})
  const [people, setPeople] = useState<Person[]>([])
  const [error, setError] = useState<string | null>(null)
  const [person, setPerson] = useState('')
  const [role, setRole] = useState<Role>('viewer')
  const [scope, setScope] = useState('building')            // 'building' | a floor id | a room id

  const load = useCallback(() => {
    listGrants(building.id).then(async g => {
      setGrants(g)
      const known = await peopleByIds([...new Set(g.map(x => x.person_id))])
      setNames(Object.fromEntries(known.map(p => [p.id, p.full_name])))
      setError(null)
    }, (e: Error) => setError(e.message))
  }, [building.id])
  useEffect(load, [load])
  useEffect(() => { listPeople().then(setPeople, () => {}) }, [])
  useEvents(event => { if (event.type.startsWith('access.')) load() })

  const areas = useMemo(() => {
    const out = new Map<string, { kind: 'building' | 'floor' | 'room'; label: string }>([['building', { kind: 'building', label: 'всё здание' }]])
    for (const f of floors) {
      out.set(f.id, { kind: 'floor', label: f.name || `этаж ${f.level}` })
      for (const r of f.rooms) out.set(r.id, { kind: 'room', label: `${f.name || f.level} · ${r.name || 'без названия'} (${r.area} м²)` })
    }
    return out
  }, [floors])
  const areaName = (g: Grant) => (g.scope.kind === 'building' ? 'всё здание' : areas.get(g.scope.id)?.label ?? 'область снята')

  const give = (e: React.FormEvent) => {
    e.preventDefault()
    const area = areas.get(scope)!
    createGrant({ person_id: person, role, building_id: building.id, scope: { kind: area.kind, id: scope === 'building' ? building.id : scope } })
      .then(() => { setPerson(''); load() }, (ex: Error) => setError(ex.message))
  }

  return (
    <section>
      <h1 className="text-xl font-semibold">Доступ</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
        Право на область действует на всё внутри неё. Любое право в здании открывает его план; объекты и люди видны только в своих помещениях.
      </p>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      <form onSubmit={give} className="mt-4 flex flex-wrap items-end gap-2 rounded-lg border bg-card p-3" data-testid="grant-form">
        <label className="grid gap-1 text-xs text-muted-foreground">Кому
          <select className={select} value={person} onChange={e => setPerson(e.target.value)} required aria-label="Кому">
            <option value="">— человек из справочника —</option>
            {people.map(p => <option key={p.id} value={p.id}>{p.full_name}{p.position ? ` — ${p.position}` : ''}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">Что может
          <select className={select} value={role} onChange={e => setRole(e.target.value as Role)} aria-label="Что может">
            {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">Где
          <select className={`${select} max-w-64`} value={scope} onChange={e => setScope(e.target.value)} aria-label="Где">
            {[...areas].map(([id, a]) => <option key={id} value={id}>{a.kind === 'room' ? `  ${a.label}` : a.label}</option>)}
          </select>
        </label>
        <Button type="submit" size="sm" disabled={!person}>Выдать</Button>
      </form>
      {grants.length === 0 ? (
        <p className="mt-5 text-sm text-muted-foreground">Прав в этом здании пока никому не выдано.</p>
      ) : (
        <ul className="mt-4 divide-y rounded-lg border bg-card text-sm" data-testid="grants">
          {grants.map(g => (
            <li key={g.id} className="flex flex-wrap items-center gap-3 px-3 py-2" data-grant={names[g.person_id] ?? ''}>
              <span className="min-w-40 flex-1 font-medium">{names[g.person_id] ?? '…'}</span>
              <span>{ROLES[g.role]}</span>
              <span className="text-muted-foreground">{areaName(g)}</span>
              <Button variant="ghost" size="sm" onClick={() => revokeGrant(g.id).then(load, (ex: Error) => setError(ex.message))}>Отозвать</Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
