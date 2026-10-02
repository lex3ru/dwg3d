import { Copy, Eye, EyeOff, GitCompare, Layers as LayersIcon, Lock, LockOpen, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { copyLayer, createLayer, deleteLayer, layerKinds, listLayers, updateLayer, type Layer, type LayerKindInfo } from '@/api'
import { useConfirm } from '@/components/confirm'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Tip } from '@/components/ui/tooltip'
import { variantGroup, variantGroups } from '@/furniture/layers'
import Compare from '../Compare'
import { plural } from '../format'

export default function Layers({ pid, editable }: { pid: string; editable: boolean }) {
  const [layers, setLayers] = useState<Layer[] | null>(null)
  const [kinds, setKinds] = useState<LayerKindInfo[]>([])
  const [kind, setKind] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [cmp, setCmp] = useState<[string, string] | null>(null)
  const [ask, dialog] = useConfirm()
  const load = useCallback(() => { listLayers(pid).then(setLayers).catch((e) => setErr((e as Error).message)) }, [pid])
  useEffect(() => { load(); layerKinds().then((k) => { setKinds(k.kinds); setKind(k.kinds[0]?.kind ?? '') }).catch(() => {}) }, [load])
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null)
    try { await fn() } catch (e) { setErr((e as Error).message) }
    load()
  }
  const kindName = (k: string) => kinds.find((x) => x.kind === k)?.name ?? k
  const groups = variantGroups(layers ?? [])
  const groupOf = (l: Layer) => groups.find((g) => g.some((x) => x.id === l.id)) ?? null
  return (
    <Card>
      <CardHeader>
        <CardTitle>Слои <span className="ml-1 font-normal text-muted-foreground">{layers?.length ?? ''}</span></CardTitle>
        {editable && kinds.length > 0 && (
          <div className="flex items-center gap-2">
            <Select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Тип слоя">
              {kinds.map((k) => <option key={k.kind} value={k.kind}>{k.name}</option>)}
            </Select>
            <Button onClick={() => act(() => createLayer(pid, kind))}><Plus /> Слой</Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="m-0 text-sm text-muted-foreground">
          Слои — наборы объектов поверх чертежей: мебель, видеонаблюдение и другие. Объекты слоя могут стоять на любом чертеже проекта;
          в просмотре слои включаются и выключаются, а новые предметы ставятся в выбранный слой.
        </p>
        {err && <p className="m-0 text-sm text-destructive">{err}</p>}
        {layers && !layers.length && (
          <p className="m-0 text-sm text-muted-foreground">Слоёв пока нет: первый появится, когда на план поставят предмет из каталога, или создайте его здесь.</p>
        )}
        <ul className="m-0 grid list-none gap-1 p-0">
          {(layers ?? []).map((l) => {
            const g = groupOf(l)
            const variantOf = g ? g.find((x) => x.id === variantGroup(l))?.name ?? g[0].name : null
            return (
              <LayerRow key={l.id} l={l} kindName={kindName(l.kind)} editable={editable} variantOf={variantOf}
                onCopy={() => act(() => copyLayer(pid, l.id))}
                onCompare={g ? () => setCmp([g[0].id === l.id ? g[1].id : g[0].id, l.id]) : null}
                onPatch={(patch) => act(() => updateLayer(pid, l.id, { ...patch, version: l.version }))}
                onDelete={async () => {
                  const n = l.count ?? 0
                  if (await ask({
                    title: `Удалить слой «${l.name}»?`,
                    text: n ? `Вместе с объектами в нём: ${n} ${plural(n, 'объект', 'объекта', 'объектов')}.` : undefined,
                    confirm: 'Удалить', danger: true,
                  })) act(() => deleteLayer(pid, l.id))
                }} />
            )
          })}
        </ul>
      </CardContent>
      {dialog}
      {cmp && <Compare projectId={pid} layers={layers ?? []} a={cmp[0]} b={cmp[1]} onClose={() => setCmp(null)} />}
    </Card>
  )
}

function LayerRow({ l, kindName, editable, variantOf, onCopy, onCompare, onPatch, onDelete }: {
  l: Layer; kindName: string; editable: boolean; variantOf: string | null; onCopy: () => void; onCompare: (() => void) | null
  onPatch: (p: Partial<Layer>) => void; onDelete: () => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(l.name)
  const n = l.count ?? 0
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg px-2 py-2 hover:bg-secondary/60">
      <LayersIcon className="size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1 basis-48">
        <b className={l.visible ? '' : 'text-muted-foreground'}>{l.name}</b>
        <div className="truncate text-xs text-muted-foreground">
          {kindName} · {n} {plural(n, 'объект', 'объекта', 'объектов')}
          {variantOf && <span className="text-accent-foreground"> · варианты «{variantOf}»</span>}
        </div>
      </div>
      {onCompare && <Button variant="outline" size="sm" onClick={onCompare}><GitCompare /> Сравнить</Button>}
      {l.locked && <Badge>заблокирован</Badge>}
      {!l.visible && <Badge>скрыт</Badge>}
      {editable && (
        <div className="flex items-center gap-0.5">
          <Tip label={l.visible ? 'Не показывать слой при открытии чертежа' : 'Показывать слой при открытии чертежа'}>
            <Button variant="ghost" size="icon-sm" aria-label="Видимость" onClick={() => onPatch({ visible: !l.visible })}>{l.visible ? <Eye /> : <EyeOff />}</Button>
          </Tip>
          <Tip label={l.locked ? 'Разблокировать слой' : 'Заблокировать: слой нельзя менять'}>
            <Button variant="ghost" size="icon-sm" aria-label="Блокировка" onClick={() => onPatch({ locked: !l.locked })}>{l.locked ? <Lock /> : <LockOpen />}</Button>
          </Tip>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Действия"><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => { setName(l.name); setRenaming(true) }}><Pencil /> Переименовать</DropdownMenuItem>
              <DropdownMenuItem onSelect={onCopy}><Copy /> Создать вариант</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive disabled={l.locked} onSelect={onDelete}><Trash2 /> Удалить</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}
      <Dialog open={renaming} onOpenChange={setRenaming}>
        <DialogContent>
          <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); onPatch({ name: name.trim() }); setRenaming(false) }}>
            <DialogHeader><DialogTitle>Название слоя</DialogTitle></DialogHeader>
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
