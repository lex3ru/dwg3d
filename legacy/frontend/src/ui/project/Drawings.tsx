import { ExternalLink, FilePlus2, MoreHorizontal, Pencil, RefreshCw, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { deleteDrawing, renameDrawing, uploadFile, uploadRevision, type JobSummary, type Project } from '@/api'
import { useConfirm } from '@/components/confirm'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { jobColor } from '@/state'
import { fmtDate } from '../format'

const STATUS: Record<JobSummary['status'], { text: string; variant: 'success' | 'accent' | 'destructive' | 'default' }> = {
  queued: { text: 'в очереди', variant: 'default' },
  running: { text: 'обрабатывается', variant: 'accent' },
  done: { text: 'готов', variant: 'success' },
  error: { text: 'ошибка', variant: 'destructive' },
}

export default function Drawings({ p, editable, onChanged }: { p: Project; editable: boolean; onChanged: () => void }) {
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
    <Card>
      <CardHeader>
        <CardTitle>Чертежи <span className="ml-1 font-normal text-muted-foreground">{p.drawings.length}</span></CardTitle>
        {editable && <Button onClick={() => input.current?.click()}><Upload /> Загрузить DWG / DXF</Button>}
        <input ref={input} type="file" accept=".dwg,.dxf" multiple hidden onChange={(e) => { upload(e.target.files); e.target.value = '' }} />
      </CardHeader>
      <CardContent className="grid gap-3">
        {editable && (
          <div
            className={cn('cursor-pointer rounded-lg border-2 border-dashed border-input px-4 py-6 text-center text-sm text-muted-foreground transition-colors hover:border-primary hover:bg-accent', drag && 'border-primary bg-accent')}
            onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files) }}
            onClick={() => input.current?.click()}>
            <FilePlus2 className="mx-auto mb-1 size-5" />
            {busy ?? 'Перетащите сюда файлы чертежей: каждый корпус или раздел — отдельный чертёж'}
          </div>
        )}
        {err && <p className="m-0 text-sm text-destructive">{err}</p>}
        {!p.drawings.length && (
          <p className="m-0 text-sm text-muted-foreground">
            Чертежей пока нет.{editable ? ' Загрузите поэтажные планы — стены, окна, двери, лестницы и этажи распознаются автоматически.' : ''}
          </p>
        )}
        <ul className="m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-1 p-0">
          {p.drawings.map((d) => <DrawingRow key={d.id} d={d} editable={editable} onChanged={onChanged} />)}
        </ul>
      </CardContent>
    </Card>
  )
}

function DrawingRow({ d, editable, onChanged }: { d: JobSummary; editable: boolean; onChanged: () => void }) {
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(d.name)
  const [err, setErr] = useState<string | null>(null)
  const rev = useRef<HTMLInputElement>(null)
  const [ask, dialog] = useConfirm()
  const running = d.status === 'queued' || d.status === 'running'
  const st = STATUS[d.status]
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null)
    try { await fn(); onChanged(); return true } catch (e) { setErr((e as Error).message); return false }
  }
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg px-2 py-2 hover:bg-secondary/60">
      <i className="size-2.5 shrink-0 rounded-full" style={{ background: jobColor(d.id) }} />
      <div className="min-w-0 flex-1 basis-48">
        {d.status === 'done'
          ? <a className="font-semibold text-foreground no-underline hover:text-primary" href={`#/f/${d.id}`}>{d.name}</a>
          : <b>{d.name}</b>}
        <div className="truncate text-xs text-muted-foreground">
          {d.filename} · {(d.size / 1e6).toFixed(1)} МБ{d.build > 1 ? ` · сборка ${d.build}` : ''}
        </div>
        {running && (
          <div className="mt-1.5 h-1 w-full max-w-60 overflow-hidden rounded-full bg-secondary">
            <div className="h-full bg-primary transition-[width]" style={{ width: `${Math.round(d.progress * 100)}%` }} />
          </div>
        )}
        {err && <div className="text-xs text-destructive">{err}</div>}
      </div>
      <Badge variant={st.variant}>{st.text}{running ? ` ${Math.round(d.progress * 100)}%` : ''}</Badge>
      <span className="w-12 text-right text-xs text-muted-foreground">{d.status === 'done' ? `${d.floors} эт.` : ''}</span>
      <span className="w-20 text-right text-xs text-muted-foreground">{fmtDate(d.updated)}</span>
      <div className="flex items-center gap-1">
        {d.status === 'done' && <Button asChild size="sm"><a href={`#/f/${d.id}`}><ExternalLink /> Открыть</a></Button>}
        {editable && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Действия"><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => { setName(d.name); setRenaming(true) }}><Pencil /> Переименовать</DropdownMenuItem>
              <DropdownMenuItem disabled={running} onSelect={() => rev.current?.click()}>
                <RefreshCw /> Новая ревизия…
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive disabled={running} onSelect={async () => {
                if (await ask({ title: `Удалить чертёж «${d.name}»?`, text: 'Вместе с расстановкой на нём. Это нельзя отменить.', confirm: 'Удалить', danger: true })) act(() => deleteDrawing(d.id))
              }}><Trash2 /> Удалить</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <input ref={rev} type="file" accept=".dwg,.dxf" hidden onChange={(e) => {
          const f = e.target.files?.[0]
          e.target.value = ''
          if (f) act(() => uploadRevision(d.id, f))
        }} />
      </div>
      {dialog}
      <Dialog open={renaming} onOpenChange={setRenaming}>
        <DialogContent>
          <form className="grid gap-4" onSubmit={async (e) => { e.preventDefault(); if (await act(() => renameDrawing(d.id, name.trim()))) setRenaming(false) }}>
            <DialogHeader><DialogTitle>Название чертежа</DialogTitle></DialogHeader>
            <Input autoFocus value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
            <DialogFooter>
              <Button type="button" variant="secondary" onClick={() => setRenaming(false)}>Отмена</Button>
              <Button disabled={!name.trim()}>Сохранить</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </li>
  )
}
