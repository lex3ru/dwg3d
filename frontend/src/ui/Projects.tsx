import { FolderPlus, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { createProject, listProjects, type Project } from '@/api'
import { Page } from '@/components/AppHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { me, PROJECT_ROLE_NAMES } from '@/session'
import { fmtDate, plural } from './format'

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
    <Page wide>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 mr-auto text-2xl font-semibold">Проекты</h1>
        {list && list.length > 5 && (
          <div className="relative">
            <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
            <Input className="w-56 pl-8" placeholder="Поиск проекта" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        )}
        {!me?.guest && <Button onClick={() => setCreating(true)}><FolderPlus /> Новый проект</Button>}
      </div>
      {err && <p className="text-sm text-destructive">{err}</p>}
      {!list && !err && <p className="text-sm text-muted-foreground">Загрузка…</p>}
      {list && !list.length && (
        <Card><CardContent className="grid gap-1 py-10 text-center">
          <p className="m-0 font-medium">Проектов пока нет.</p>
          {!me?.guest && <p className="m-0 text-sm text-muted-foreground">Создайте проект и загрузите в него чертёж DWG или DXF. Проекты других пользователей видны, когда вас добавят участником.</p>}
        </CardContent></Card>
      )}
      <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3 p-0">
        {shown.map((p) => {
          const running = p.drawings.filter((d) => d.status === 'queued' || d.status === 'running').length
          return (
            <li key={p.id}>
              <a href={`#/p/${p.id}`} className="flex h-full flex-col gap-2 rounded-xl border border-border bg-card p-4 text-card-foreground no-underline transition-colors hover:border-primary hover:bg-accent/40">
                <b className="text-base">{p.name}</b>
                {p.description && <span className="line-clamp-2 text-sm text-muted-foreground">{p.description}</span>}
                <span className="mt-auto flex flex-wrap items-center gap-2 pt-2 text-xs text-muted-foreground">
                  <span>{p.drawings.length} {plural(p.drawings.length, 'чертёж', 'чертежа', 'чертежей')}</span>
                  {running > 0 && <Badge variant="accent">обрабатывается {running}</Badge>}
                  {p.my_role && <Badge>{PROJECT_ROLE_NAMES[p.my_role]}</Badge>}
                  <span className="flex-1" />
                  <span>{fmtDate(p.updated)}</span>
                </span>
              </a>
            </li>
          )
        })}
      </ul>
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <form className="grid gap-4" onSubmit={create}>
            <DialogHeader>
              <DialogTitle>Новый проект</DialogTitle>
              <DialogDescription>
                Проект — папка для всего, что относится к объекту: чертежи корпусов и этажей, слои мебели, видеонаблюдения, маршрутов; участники и ссылки для заказчика.
              </DialogDescription>
            </DialogHeader>
            <Label>Название <Input autoFocus value={name} maxLength={200} placeholder="Например, «Медцентр на Ленина»" onChange={(e) => setName(e.target.value)} /></Label>
            <Label>Описание <span className="font-normal text-muted-foreground">(необязательно)</span>
              <Textarea rows={2} value={descr} maxLength={5000} onChange={(e) => setDescr(e.target.value)} />
            </Label>
            {err && <p className="m-0 text-sm text-destructive">{err}</p>}
            <DialogFooter>
              <Button type="button" variant="secondary" onClick={() => setCreating(false)}>Отмена</Button>
              <Button disabled={busy || !name.trim()}>{busy ? 'Создание…' : 'Создать'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Page>
  )
}
