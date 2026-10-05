import { AlertTriangle, Copy, Columns3, RotateCcw, RotateCw, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type { Layer, LayerKindInfo, PlacedItem } from '@/scene/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { catalogItem } from '@/scene/furniture/catalog'
import { ISSUE_LABEL, LUX_LIT, LUX_WORK, camParams, itemElev, itemSize, lightZone, roomAt, type Issue, type PlanIndex } from '@/scene/furniture/geom'
import { layersFor } from '@/scene/furniture/layers'
import { cm, ItemSymbol, NumField } from './parts'

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label className="grid gap-1 text-xs text-muted-foreground">{label}{children}</label>
)

/** The selected placed item: size, position, rotation, layer, note, issues; copy, row, delete. */
export default function ItemInspector(p: {
  item: PlacedItem
  items: PlacedItem[]
  plan: PlanIndex | null
  issues: Issue[]
  layers: Layer[]
  kinds: LayerKindInfo[]
  readOnly: boolean
  onSelect: (id: string | null) => void
  onUpdate: (id: string, patch: Partial<PlacedItem>) => void
  onRotate: (id: string, by: number) => void
  onDuplicate: (id: string) => void
  onRow: (id: string, count: number, gap: number) => void
  onDelete: (id: string) => void
}) {
  const sel = p.item
  const c = catalogItem(sel.item)
  const [w, d, h] = itemSize(sel, c)
  const [row, setRow] = useState<{ n: number; gap: number } | null>(null)
  const setSize = (k: 0 | 1 | 2, v: number) => {
    const s: [number, number, number] = [w, d, h]
    s[k] = v / 100
    p.onUpdate(sel.id, { size: s })
  }
  const opts = layersFor(p.layers, p.kinds, c.cat)
  const cp = c.cam ? camParams(sel, c) : null
  const light = c.params?.light, lz = lightZone(sel, c)
  return (
    <div className="grid gap-3 p-3" onKeyDown={(e) => e.stopPropagation()}>
      <div className="flex items-start gap-2">
        <ItemSymbol c={c} />
        <div className="min-w-0 flex-1">
          <b className="block truncate">{c.name}</b>
          <small className="text-xs text-muted-foreground">{(p.plan && roomAt(p.plan, sel.at)) || 'вне помещений'}</small>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Снять выделение" onClick={() => p.onSelect(null)}><X /></Button>
      </div>
      {p.issues.length > 0 && (
        <ul className="m-0 grid list-none gap-1 p-0">
          {p.issues.map((x, i) => (
            <li key={i} className={`flex items-start gap-1.5 rounded-md p-1.5 text-xs ${x.kind === 'zone' ? 'bg-warning/15 text-warning' : 'bg-destructive/10 text-destructive'}`}>
              <AlertTriangle className="mt-px size-3.5 shrink-0" />
              <span>{ISSUE_LABEL[x.kind]}{x.with && <>: <button className="cursor-pointer border-0 bg-transparent p-0 text-xs underline" onClick={() => p.onSelect(x.with!)}>
                {catalogItem(p.items.find((o) => o.id === x.with)?.item ?? '').name}</button></>}</span>
            </li>
          ))}
        </ul>
      )}
      <fieldset disabled={p.readOnly} className="m-0 grid gap-3 border-0 p-0">
        <div className="grid grid-cols-3 gap-2">
          <NumField label="Ширина, см" value={cm(w)} onChange={(v) => setSize(0, v)} />
          <NumField label="Глубина, см" value={cm(d)} onChange={(v) => setSize(1, v)} />
          <NumField label="Высота, см" value={cm(h)} onChange={(v) => setSize(2, v)} />
        </div>
        {sel.size && (
          <button className="-mt-2 cursor-pointer justify-self-start border-0 bg-transparent p-0 text-xs text-primary hover:underline" onClick={() => p.onUpdate(sel.id, { size: undefined })}>
            Размер по каталогу ({cm(c.w)}×{cm(c.d)}×{cm(c.h)})
          </button>
        )}
        {(c.elev != null || sel.elev != null) && (
          <NumField label="Высота установки, см" value={cm(itemElev(sel, c))} min={0} max={2000} onChange={(v) => p.onUpdate(sel.id, { elev: v / 100 })} />
        )}
        {cp && (
          <div className="grid grid-cols-2 gap-2">
            <NumField label="Угол обзора, °" value={Math.round(cp.fov)} min={1} max={360} onChange={(v) => p.onUpdate(sel.id, { fov: v })} />
            <NumField label="Дальность, м" value={Math.round(cp.range * 10) / 10} min={0.5} max={300} onChange={(v) => p.onUpdate(sel.id, { range: v })} />
            <small className="col-span-2 text-xs text-muted-foreground">Лица различимы до {cp.ident.toFixed(1)} м</small>
          </div>
        )}
        {light && lz && (
          <small className="text-xs text-muted-foreground">
            {light.flux} лм · {light.power} Вт · луч {light.beam}° · {light.cct} К.
            Под светильником {Math.round(lz.under)} лк; не меньше {LUX_WORK} лк — в радиусе {lz.work.toFixed(1)} м, {LUX_LIT} лк — {lz.lit.toFixed(1)} м
            (на высоте 0,8 м, зависит от высоты установки)
          </small>
        )}
        <div className="grid grid-cols-[5rem_1fr] items-end gap-2">
          <NumField label="Поворот, °" value={Math.round(sel.angle)} min={-360} max={360} onChange={(v) => p.onUpdate(sel.id, { angle: ((v % 360) + 360) % 360 })} />
          <div className="flex gap-1">
            <Button variant="outline" size="sm" title="90° против часовой (R)" onClick={() => p.onRotate(sel.id, 90)}><RotateCcw /> 90°</Button>
            <Button variant="outline" size="sm" title="90° по часовой (Shift+R)" onClick={() => p.onRotate(sel.id, -90)}><RotateCw /> 90°</Button>
            <Button variant="outline" size="sm" title="15° против часовой (Q)" onClick={() => p.onRotate(sel.id, 15)}>15°</Button>
          </div>
        </div>
        {(opts.length > 1 || (sel.layer && !opts.some((l) => l.id === sel.layer))) && (
          <Field label="Слой">
            <Select value={sel.layer ?? ''} onChange={(e) => e.target.value && p.onUpdate(sel.id, { layer: e.target.value })}>
              {!sel.layer && <option value="">—</option>}
              {p.layers.filter((l) => l.id === sel.layer || opts.includes(l)).map((l) => (
                <option key={l.id} value={l.id}>{l.name}{l.locked ? ' (заблокирован)' : ''}</option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Примечание">
          <Input value={sel.note ?? ''} placeholder="артикул, поставщик…" maxLength={500} onChange={(e) => p.onUpdate(sel.id, { note: e.target.value || undefined })} />
        </Field>
        {row ? (
          <div className="grid grid-cols-2 gap-2 rounded-md border border-border p-2">
            <NumField label="Штук" value={row.n} min={2} max={50} onChange={(v) => setRow({ ...row, n: Math.round(v) })} />
            <NumField label="Зазор, см" value={cm(row.gap)} min={0} max={1000} onChange={(v) => setRow({ ...row, gap: v / 100 })} />
            <Button size="sm" onClick={() => { p.onRow(sel.id, row.n, row.gap); setRow(null) }}>Создать ряд</Button>
            <Button size="sm" variant="secondary" onClick={() => setRow(null)}>Отмена</Button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            <Button variant="outline" size="sm" title="Ctrl+D" onClick={() => p.onDuplicate(sel.id)}><Copy /> Копия</Button>
            <Button variant="outline" size="sm" title="Ряд одинаковых предметов вдоль ширины" onClick={() => setRow({ n: 3, gap: 0 })}><Columns3 /> Ряд…</Button>
            <Button variant="ghost" size="sm" className="ml-auto text-destructive" title="Delete" onClick={() => p.onDelete(sel.id)}><Trash2 /> Удалить</Button>
          </div>
        )}
      </fieldset>
    </div>
  )
}
