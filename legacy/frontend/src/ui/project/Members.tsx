import { UserMinus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { addMember, listMembers, removeMember, setMemberRole, type Member } from '@/api'
import { useConfirm } from '@/components/confirm'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { PROJECT_ROLE_NAMES, type ProjectRole } from '@/session'

const ROLES: ProjectRole[] = ['viewer', 'editor', 'owner']

export default function Members({ pid, owner }: { pid: string; owner: boolean }) {
  const [list, setList] = useState<Member[] | null>(null)
  const [who, setWho] = useState('')
  const [role, setRole] = useState<ProjectRole>('editor')
  const [err, setErr] = useState<string | null>(null)
  const [ask, dialog] = useConfirm()
  const load = useCallback(() => { listMembers(pid).then(setList).catch((e) => setErr((e as Error).message)) }, [pid])
  useEffect(load, [load])
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null)
    try { await fn(); return true } catch (e) { setErr((e as Error).message); return false } finally { load() }
  }
  return (
    <Card>
      <CardHeader><CardTitle>Участники <span className="ml-1 font-normal text-muted-foreground">{list?.length ?? ''}</span></CardTitle></CardHeader>
      <CardContent className="grid gap-3">
        {owner && (
          <>
            <form className="flex flex-wrap gap-2" onSubmit={async (e) => {
              e.preventDefault()
              if (await act(() => addMember(pid, who.trim(), role))) setWho('')
            }}>
              <Input className="flex-1 basis-56" value={who} placeholder="Логин или e-mail" onChange={(e) => setWho(e.target.value)} />
              <Select value={role} onChange={(e) => setRole(e.target.value as ProjectRole)} aria-label="Роль">
                {ROLES.map((r) => <option key={r} value={r}>{PROJECT_ROLE_NAMES[r]}</option>)}
              </Select>
              <Button disabled={!who.trim()}>Добавить</Button>
            </form>
            <p className="m-0 text-sm text-muted-foreground">
              Добавить можно того, кто уже входил в систему, — по логину или e-mail. Если человек ещё не входил, укажите его e-mail:
              приглашение сработает при первом входе. Учётные записи заводит администратор в Keycloak.
            </p>
          </>
        )}
        {err && <p className="m-0 text-sm text-destructive">{err}</p>}
        <ul className="m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-1 p-0">
          {(list ?? []).map((m) => (
            <li key={m.id} className="flex flex-wrap items-center gap-3 rounded-lg px-2 py-2 hover:bg-secondary/60">
              <div className="min-w-0 flex-1 basis-48">
                <b>{m.user?.name ?? m.email}</b>
                <div className="truncate text-xs text-muted-foreground">
                  {m.user ? `${m.user.login}${m.email ? ` · ${m.email}` : ''}` : 'приглашён, ещё не входил'}
                </div>
              </div>
              {owner ? (
                <Select value={m.role} onChange={(e) => act(() => setMemberRole(pid, m.id, e.target.value as ProjectRole))} aria-label="Роль">
                  {ROLES.map((r) => <option key={r} value={r}>{PROJECT_ROLE_NAMES[r]}</option>)}
                </Select>
              ) : <Badge>{m.role_name}</Badge>}
              {owner && (
                <Button variant="ghost" size="icon-sm" aria-label="Убрать из проекта" onClick={async () => {
                  if (await ask({ title: `Убрать ${m.user?.name ?? m.email} из проекта?`, confirm: 'Убрать', danger: true })) act(() => removeMember(pid, m.id))
                }}><UserMinus /></Button>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
      {dialog}
    </Card>
  )
}
