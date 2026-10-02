import { Copy, Link2Off, Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { createShare, listLayers, listShares, revokeShare, type Layer, type Project, type ShareLink } from '@/api'
import { useConfirm } from '@/components/confirm'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { fmtDate } from '../format'

export default function Shares({ p }: { p: Project }) {
  const [list, setList] = useState<ShareLink[] | null>(null)
  const [layers, setLayers] = useState<Layer[]>([])
  const [form, setForm] = useState(false)
  const [name, setName] = useState('')
  const [days, setDays] = useState<string>('30')
  const [drawings, setDrawings] = useState<Set<string> | null>(null)
  const [lset, setLset] = useState<Set<string> | null>(null)
  const [made, setMade] = useState<ShareLink | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ask, dialog] = useConfirm()
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
  const dids = p.drawings.map((d) => d.id)
  const lids = layers.map((l) => l.id)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ссылки для просмотра</CardTitle>
        <Button onClick={() => { setForm(true); setMade(null) }}><Plus /> Ссылка</Button>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="m-0 text-sm text-muted-foreground">
          Ссылка открывает проект без учётной записи — только для просмотра (например, заказчику). Можно ограничить чертежи и слои и задать срок; ссылку можно отозвать.
        </p>
        {made?.url && (
          <div className="grid gap-2 rounded-lg border border-success/40 bg-success/10 p-3 text-sm">
            <span>Ссылка создана — скопируйте её сейчас, позже она не показывается:</span>
            <div className="flex gap-2">
              <Input readOnly value={made.url} onFocus={(e) => e.target.select()} />
              <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(made.url!)}><Copy /> Копировать</Button>
            </div>
          </div>
        )}
        {err && <p className="m-0 text-sm text-destructive">{err}</p>}
        {list && !list.length && <p className="m-0 text-sm text-muted-foreground">Ссылок пока нет.</p>}
        <ul className="m-0 grid list-none gap-1 p-0">
          {(list ?? []).map((x) => (
            <li key={x.id} className={`flex flex-wrap items-center gap-3 rounded-lg px-2 py-2 hover:bg-secondary/60 ${x.active ? '' : 'opacity-60'}`}>
              <div className="min-w-0 flex-1 basis-48">
                <b>{x.name || 'Без названия'}</b>
                <div className="text-xs text-muted-foreground">
                  {scope(x)} · {x.revoked ? 'отозвана' : x.expires ? `${x.active ? 'до' : 'истекла'} ${fmtDate(x.expires)}` : 'бессрочно'}
                  {x.last_used ? ` · открывали ${fmtDate(x.last_used)}` : ' · не открывали'}
                </div>
              </div>
              {!x.active && <Badge>{x.revoked ? 'отозвана' : 'истекла'}</Badge>}
              {x.active && (
                <Button variant="ghost" size="sm" className="text-destructive" onClick={async () => {
                  if (await ask({ title: 'Отозвать ссылку?', text: 'Открыть проект по ней больше не получится.', confirm: 'Отозвать', danger: true })) {
                    revokeShare(p.id, x.id).then(load).catch((e) => setErr((e as Error).message))
                  }
                }}><Link2Off /> Отозвать</Button>
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
              <DialogTitle>Новая ссылка для просмотра</DialogTitle>
              <DialogDescription>Без учётной записи, только чтение.</DialogDescription>
            </DialogHeader>
            <Label>Для кого <Input value={name} maxLength={200} placeholder="Например, «Заказчик»" onChange={(e) => setName(e.target.value)} /></Label>
            <Label>Срок
              <Select value={days} onChange={(e) => setDays(e.target.value)}>
                <option value="7">7 дней</option><option value="30">30 дней</option><option value="90">90 дней</option>
                <option value="365">год</option><option value="">бессрочно</option>
              </Select>
            </Label>
            {p.drawings.length > 1 && (
              <fieldset className="m-0 grid gap-1.5 rounded-lg border border-border p-3">
                <legend className="px-1 text-sm font-medium">Чертежи</legend>
                {p.drawings.map((d) => (
                  <label key={d.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" className="accent-primary" checked={!drawings || drawings.has(d.id)}
                      onChange={() => setDrawings(toggle(drawings, dids, d.id))} /> {d.name}
                  </label>
                ))}
              </fieldset>
            )}
            {layers.length > 0 && (
              <fieldset className="m-0 grid gap-1.5 rounded-lg border border-border p-3">
                <legend className="px-1 text-sm font-medium">Слои</legend>
                {layers.map((l) => (
                  <label key={l.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" className="accent-primary" checked={!lset || lset.has(l.id)}
                      onChange={() => setLset(toggle(lset, lids, l.id))} /> {l.name}
                  </label>
                ))}
              </fieldset>
            )}
            <DialogFooter>
              <Button type="button" variant="secondary" onClick={() => setForm(false)}>Отмена</Button>
              <Button disabled={(drawings?.size ?? 1) === 0}>Создать ссылку</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
