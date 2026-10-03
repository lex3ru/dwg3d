import { Copy, KeyRound, Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { createAgentToken, listAgentTokens, revokeAgentToken, type AgentMode, type AgentToken, type Project } from '@/api'
import { useConfirm } from '@/components/confirm'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { fmtDate } from '../format'

const MODES: { id: AgentMode; label: string; hint: string }[] = [
  { id: 'read', label: 'Только чтение', hint: 'Агент видит проект: чертежи, помещения, слои, объекты, отчёты.' },
  { id: 'propose', label: 'Предложения', hint: 'Пока — как чтение; позже агент сможет предлагать изменения, а вы — принимать их.' },
  { id: 'write', label: 'Изменение', hint: 'Агент расставляет, меняет и удаляет объекты, создаёт слои — как редактор. Удалять слои и чертежи, менять участников он не может.' },
]

/** Tokens of AI agents: access to the project for an MCP client or a script, acting for the user. */
export default function Agents({ p, editor, owner }: { p: Project; editor: boolean; owner: boolean }) {
  const [list, setList] = useState<AgentToken[] | null>(null)
  const [form, setForm] = useState(false)
  const [name, setName] = useState('')
  const [mode, setMode] = useState<AgentMode>('read')
  const [days, setDays] = useState('90')
  const [made, setMade] = useState<AgentToken | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ask, dialog] = useConfirm()
  const load = useCallback(() => { listAgentTokens(p.id).then(setList).catch((e) => setErr((e as Error).message)) }, [p.id])
  useEffect(load, [load])
  const modes = MODES.filter((m) => m.id !== 'write' || editor)
  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    try {
      setMade(await createAgentToken(p.id, { name: name.trim(), mode, days: Number(days) }))
      setForm(false)
      setName('')
    } catch (ex) { setErr((ex as Error).message) }
    load()
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Доступ для ИИ-агентов</CardTitle>
        <Button onClick={() => { setForm(true); setMade(null); setMode('read') }}><Plus /> Токен</Button>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="m-0 text-sm text-muted-foreground">
          Токен даёт ИИ-агенту (например, Claude через MCP) или скрипту доступ к этому проекту от вашего имени — не больше ваших прав
          и не больше выбранного режима. Изменения агента видны в журнале с пометкой токена. Токен можно отозвать в любой момент.
        </p>
        {made?.token && (
          <div className="grid gap-2 rounded-lg border border-success/40 bg-success/10 p-3 text-sm">
            <span>Токен создан — скопируйте его сейчас, позже он не показывается. Агент передаёт его в заголовке <code>Authorization: Bearer …</code></span>
            <div className="flex gap-2">
              <Input readOnly className="font-mono" value={made.token} onFocus={(e) => e.target.select()} />
              <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(made.token!)}><Copy /> Копировать</Button>
            </div>
          </div>
        )}
        {err && <p className="m-0 text-sm text-destructive">{err}</p>}
        {list && !list.length && <p className="m-0 text-sm text-muted-foreground">Токенов пока нет.</p>}
        <ul className="m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-1 p-0">
          {(list ?? []).map((x) => (
            <li key={x.id} className={`flex flex-wrap items-center gap-3 rounded-lg px-2 py-2 hover:bg-secondary/60 ${x.active ? '' : 'opacity-60'}`}>
              <div className="min-w-0 flex-1 basis-48">
                <b>{x.name || 'Без названия'}</b>
                <div className="text-xs text-muted-foreground">
                  {x.mode_name}
                  {owner && !x.mine && x.user ? ` · ${x.user.name || x.user.login}` : ''}
                  {' · '}{x.revoked ? 'отозван' : `${x.active ? 'до' : 'истёк'} ${fmtDate(x.expires)}`}
                  {x.last_used ? ` · использовался ${fmtDate(x.last_used)}` : ' · не использовался'}
                </div>
              </div>
              {!x.active && <Badge>{x.revoked ? 'отозван' : 'истёк'}</Badge>}
              {x.active && (
                <Button variant="ghost" size="sm" className="text-destructive" onClick={async () => {
                  if (await ask({ title: 'Отозвать токен?', text: 'Агент с этим токеном сразу потеряет доступ к проекту.', confirm: 'Отозвать', danger: true })) {
                    if (made?.id === x.id) setMade(null)
                    revokeAgentToken(p.id, x.id).then(load).catch((e) => setErr((e as Error).message))
                  }
                }}><KeyRound /> Отозвать</Button>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
      {dialog}
      <Dialog open={form} onOpenChange={setForm}>
        <DialogContent>
          <form className="grid gap-4" onSubmit={create}>
            <DialogHeader>
              <DialogTitle>Новый токен агента</DialogTitle>
              <DialogDescription>Доступ только к проекту «{p.name}», от вашего имени.</DialogDescription>
            </DialogHeader>
            <Label>Название <Input value={name} maxLength={120} placeholder="Например, «Claude Code на ноутбуке»" onChange={(e) => setName(e.target.value)} /></Label>
            <Label>Режим
              <Select value={mode} onChange={(e) => setMode(e.target.value as AgentMode)}>
                {modes.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </Select>
              <span className="text-xs font-normal text-muted-foreground">{MODES.find((m) => m.id === mode)?.hint}</span>
            </Label>
            <Label>Срок
              <Select value={days} onChange={(e) => setDays(e.target.value)}>
                <option value="1">1 день</option><option value="7">7 дней</option><option value="30">30 дней</option>
                <option value="90">90 дней</option><option value="365">год</option>
              </Select>
            </Label>
            <DialogFooter>
              <Button type="button" variant="secondary" onClick={() => setForm(false)}>Отмена</Button>
              <Button>Создать токен</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
