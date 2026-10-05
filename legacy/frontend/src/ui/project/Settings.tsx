import { useState } from 'react'
import { deleteProject, updateProject, type Project } from '@/api'
import { useConfirm } from '@/components/confirm'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

/** Name and description (editors), and deleting the project (the owner). */
export default function ProjectSettings({ p, editable, owner, onSaved }: {
  p: Project; editable: boolean; owner: boolean; onSaved: (p: Project) => void
}) {
  const [name, setName] = useState(p.name)
  const [descr, setDescr] = useState(p.description)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [ask, dialog] = useConfirm()
  const dirty = name.trim() !== p.name || descr.trim() !== p.description
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader><CardTitle>Общие</CardTitle></CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={async (e) => {
            e.preventDefault()
            setErr(null)
            try { onSaved(await updateProject(p.id, { name: name.trim(), description: descr.trim() })); setSaved(true) } catch (ex) { setErr((ex as Error).message) }
          }}>
            <Label>Название <Input value={name} maxLength={200} disabled={!editable} onChange={(e) => { setName(e.target.value); setSaved(false) }} /></Label>
            <Label>Описание <Textarea rows={3} value={descr} maxLength={5000} disabled={!editable} onChange={(e) => { setDescr(e.target.value); setSaved(false) }} /></Label>
            {err && <p className="m-0 text-sm text-destructive">{err}</p>}
            {editable && (
              <div className="flex items-center gap-3">
                <Button disabled={!name.trim() || !dirty}>Сохранить</Button>
                {saved && <span className="text-sm text-success">Сохранено</span>}
              </div>
            )}
          </form>
        </CardContent>
      </Card>
      {owner && (
        <Card className="border-destructive/40">
          <CardHeader><CardTitle>Удаление проекта</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3">
            <p className="m-0 flex-1 basis-60 text-sm text-muted-foreground">Проект со всеми чертежами, слоями и ссылками будет удалён без возможности восстановления.</p>
            <Button variant="destructive" onClick={async () => {
              if (!(await ask({
                title: `Удалить проект «${p.name}»?`, text: 'Введите название проекта, чтобы подтвердить.',
                typed: p.name, confirm: 'Удалить проект', danger: true,
              }))) return
              try { await deleteProject(p.id); location.hash = '#/' } catch (e) { setErr((e as Error).message) }
            }}>Удалить проект…</Button>
          </CardContent>
        </Card>
      )}
      {dialog}
    </div>
  )
}
