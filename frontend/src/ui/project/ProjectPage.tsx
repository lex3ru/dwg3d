import { Bot, FileSpreadsheet, FolderOpen, Layers as LayersIcon, Link2, ListChecks, Settings as SettingsIcon, Users, type LucideIcon } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { getProject, type Project } from '@/api'
import { Page } from '@/components/AppHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { hasProjectRole, me, PROJECT_ROLE_NAMES, setProjectRole } from '@/session'
import Report from '../Report'
import Agents from './Agents'
import Checks, { useChecks } from './Checks'
import Drawings from './Drawings'
import Layers from './Layers'
import Members from './Members'
import ProjectSettings from './Settings'
import Shares from './Shares'

type Section = 'drawings' | 'layers' | 'spec' | 'checks' | 'members' | 'shares' | 'agents' | 'settings'

const NAV: { id: Section; label: string; icon: LucideIcon }[] = [
  { id: 'drawings', label: 'Чертежи', icon: FolderOpen },
  { id: 'layers', label: 'Слои', icon: LayersIcon },
  { id: 'spec', label: 'Спецификация', icon: FileSpreadsheet },
  { id: 'checks', label: 'Проверки', icon: ListChecks },
  { id: 'members', label: 'Участники', icon: Users },
  { id: 'shares', label: 'Ссылки', icon: Link2 },
  { id: 'agents', label: 'ИИ-агенты', icon: Bot },
  { id: 'settings', label: 'Настройки', icon: SettingsIcon },
]

/** A project: its drawings, layers, specification, checks, members, share links and agents' tokens, one section at a time. */
export default function ProjectPage({ pid, section }: { pid: string; section?: string }) {
  const [p, setP] = useState<Project | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const reload = useCallback(() => setNonce((n) => n + 1), [])
  const checks = useChecks(pid)
  const [report, setReport] = useState(false)
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

  const guest = !!me?.guest
  const editor = hasProjectRole('editor')
  const owner = hasProjectRole('owner')
  const hasChecks = !!checks && checks.fire.length > 0
  const items = NAV.filter((n) => {
    if (n.id === 'checks') return hasChecks
    if (n.id === 'agents') return !guest && !!p?.my_role
    if (n.id === 'members' || n.id === 'shares' || n.id === 'settings') return !guest && (n.id === 'members' || n.id === 'settings' || owner)
    return true
  })
  const current: Section = items.some((n) => n.id === section) ? (section as Section) : 'drawings'

  if (!p) {
    return (
      <Page crumbs={guest ? [] : [{ label: 'Проекты', href: '#/' }]}>
        {err ? <Card><CardContent className="grid gap-2"><p className="m-0 text-destructive">{err}</p><a href="#/">← К проектам</a></CardContent></Card>
          : <p className="text-sm text-muted-foreground">Загрузка…</p>}
      </Page>
    )
  }
  const count = (id: Section) => (id === 'drawings' ? p.drawings.length : id === 'checks' ? checks?.fire.length : undefined)
  return (
    <Page wide crumbs={[...(guest ? [] : [{ label: 'Проекты', href: '#/' }]), { label: p.name }]}>
      <div className="mb-5 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1 basis-72">
          <h1 className="m-0 text-2xl font-semibold">{p.name}</h1>
          {p.description && <p className="mt-1 mb-0 text-sm text-muted-foreground">{p.description}</p>}
        </div>
        {p.my_role && <Badge variant="accent">{PROJECT_ROLE_NAMES[p.my_role]}</Badge>}
      </div>
      <div className="flex flex-col gap-6 md:flex-row">
        <nav aria-label="Разделы проекта" className="flex shrink-0 gap-1 overflow-x-auto md:w-52 md:flex-col">
          {items.map((n) => (
            <a key={n.id} href={`#/p/${pid}/${n.id}`} aria-current={n.id === current ? 'page' : undefined}
              className={cn('flex items-center gap-2 rounded-lg px-3 py-2 text-sm whitespace-nowrap no-underline transition-colors',
                n.id === current ? 'bg-accent font-medium text-accent-foreground' : 'text-foreground hover:bg-secondary')}>
              <n.icon className="size-4" />
              <span className="flex-1">{n.label}</span>
              {count(n.id) != null && <span className="text-xs text-muted-foreground">{count(n.id)}</span>}
            </a>
          ))}
        </nav>
        <main className="min-w-0 flex-1">
          {err && <p className="mt-0 text-sm text-destructive">{err}</p>}
          {current === 'drawings' && <Drawings p={p} editable={editor} onChanged={reload} />}
          {current === 'layers' && <Layers pid={pid} editable={editor} />}
          {current === 'spec' && (
            <Card>
              <CardHeader><CardTitle>Спецификация</CardTitle><Button onClick={() => setReport(true)}><FileSpreadsheet /> Открыть</Button></CardHeader>
              <CardContent>
                <p className="m-0 text-sm text-muted-foreground">
                  Оборудование из слоёв проекта: по этажам всех чертежей или по помещениям, по всему проекту или одному слою; выгрузка в Excel.
                </p>
              </CardContent>
            </Card>
          )}
          {current === 'checks' && checks && <Checks c={checks} />}
          {current === 'members' && <Members pid={pid} owner={owner} />}
          {current === 'shares' && <Shares p={p} />}
          {current === 'agents' && <Agents p={p} editor={editor} owner={owner} />}
          {current === 'settings' && <ProjectSettings p={p} editable={editor} owner={owner} onSaved={setP} />}
        </main>
      </div>
      {report && <Report projectId={pid} onClose={() => setReport(false)} />}
    </Page>
  )
}
