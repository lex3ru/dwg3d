import { AlertTriangle, Copy, Columns3, RotateCcw, RotateCw, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type { Layer, PlacedItem } from '@/scene/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tip } from '@/components/ui/tooltip'
import { assetOf } from '@/scene/compat'
import { catalogItem } from '@/scene/furniture/catalog'
import { ISSUE_LABEL, LUX_LIT, LUX_WORK, camParams, itemElev, itemSize, lightZone, roomAt, type Issue, type PlanIndex } from '@/scene/furniture/geom'
import { cm, ItemSymbol, NumField } from './parts'

// Placed items are objects of accounting or items of variants. What the services keep of them: the place, the turn,
// the note, and for an object its mounting height; the size, a camera's view and the layer are its type's in the catalog.
const FROM_CATALOG = 'Задаёт тип в каталоге — у всех объектов этого типа сразу; правит администратор в редакторе каталога'

/** A value the services do not keep per item: shown, not edited. */
const Fixed = ({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) => (
  <Tip label={hint}>
    <div className="grid gap-1 text-xs text-muted-foreground">{label}<span className="text-sm text-foreground">{children}</span></div>
  </Tip>
)

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label className="grid gap-1 text-xs text-muted-foreground">{label}{children}</label>
)

/** The selected placed item: size, mounting height, rotation, layer, note, issues; copy, row, delete. */
export default function ItemInspector(p: {
  item: PlacedItem
  items: PlacedItem[]
  plan: PlanIndex | null
  issues: Issue[]
  layers: Layer[]
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
  // an object of accounting: its size is its type's, it is retired in its card rather than deleted here
  const asset = assetOf(sel.id)
  const [w, d, h] = itemSize(sel, c)
  const [row, setRow] = useState<{ n: number; gap: number } | null>(null)
  const layer = p.layers.find((l) => l.id === sel.layer)
  const cp = c.cam ? camParams(sel, c) : null
  const light = c.params?.light, lz = lightZone(sel, c)
  return (
    <div className="grid gap-3 p-3" onKeyDown={(e) => e.stopPropagation()}>
      <div className="flex items-start gap-2">
        <ItemSymbol c={c} />
        <div className="min-w-0 flex-1">
          <b className="block truncate">{c.name}</b>
          {asset && (
            <Tip label="Открыть карточку объекта: свойства, ответственный, история">
              <a className="block text-xs text-primary hover:underline" href={asset.card} data-testid="asset-link">инв. № {asset.number} — карточка</a>
            </Tip>
          )}
          <small className="text-xs text-muted-foreground">{(p.plan && roomAt(p.plan, sel.at)) || 'вне помещений'}</small>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Снять выделение" hint="Закрыть свойства предмета (Esc); он останется на месте" onClick={() => p.onSelect(null)}><X /></Button>
      </div>
      {p.issues.length > 0 && (
        <ul className="m-0 grid list-none gap-1 p-0">
          {p.issues.map((x, i) => (
            <li key={i} className={`flex items-start gap-1.5 rounded-md p-1.5 text-xs ${x.kind === 'zone' ? 'bg-warning/15 text-warning' : 'bg-destructive/10 text-destructive'}`}>
              <AlertTriangle className="mt-px size-3.5 shrink-0" />
              <span>{ISSUE_LABEL[x.kind]}{x.with && <>: <Tip label="Выделить второй предмет этого замечания"><button className="cursor-pointer border-0 bg-transparent p-0 text-xs underline" onClick={() => p.onSelect(x.with!)}>
                {catalogItem(p.items.find((o) => o.id === x.with)?.item ?? '').name}</button></Tip></>}</span>
            </li>
          ))}
        </ul>
      )}
      <fieldset disabled={p.readOnly} className="m-0 grid gap-3 border-0 p-0">
        <Fixed label="Габариты" hint={FROM_CATALOG}>{cm(w)}×{cm(d)}×{cm(h)} см</Fixed>
        {(c.elev != null || c.ceiling || sel.elev != null) && (asset ? (
          <NumField label="Высота установки, см" value={cm(itemElev(sel, c))} min={0} max={2000} onChange={(v) => p.onUpdate(sel.id, { elev: v / 100 })}
            hint="От пола этажа, 0–2000 см; уходит в учёт вместе с положением объекта" />
        ) : (
          <Fixed label="Высота установки" hint="Как у типа в каталоге: вариант хранит место, поворот и примечание предмета, но не высоту">
            {cm(itemElev(sel, c))} см
          </Fixed>
        ))}
        {cp && (
          <div className="grid grid-cols-2 gap-2">
            <Fixed label="Угол обзора" hint={`${FROM_CATALOG}; по нему на плане строится сектор`}>{Math.round(cp.fov)}°</Fixed>
            <Fixed label="Дальность" hint={`${FROM_CATALOG}; по ней на плане строится сектор`}>{(Math.round(cp.range * 10) / 10).toLocaleString('ru')} м</Fixed>
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
          <NumField label="Поворот, °" value={Math.round(sel.angle)} min={-360} max={360} onChange={(v) => p.onUpdate(sel.id, { angle: ((v % 360) + 360) % 360 })}
            hint="Угол в градусах, плюс — против часовой; сохраняется сразу, Ctrl+Z отменяет" />
          <div className="flex gap-1">
            <Button variant="outline" size="sm" hint="Против часовой стрелки (R); сохраняется сразу, Ctrl+Z отменяет" onClick={() => p.onRotate(sel.id, 90)}><RotateCcw /> 90°</Button>
            <Button variant="outline" size="sm" hint="По часовой стрелке (Shift+R)" onClick={() => p.onRotate(sel.id, -90)}><RotateCw /> 90°</Button>
            <Button variant="outline" size="sm" hint="Против часовой (Q); E — на 15° по часовой" onClick={() => p.onRotate(sel.id, 15)}>15°</Button>
          </div>
        </div>
        {layer && (
          <Fixed label="Слой" hint={asset ? 'Слой задаёт раздел каталога, к которому относится тип объекта; другой тип выбирается в карточке объекта'
            : 'Предмет варианта лежит в слое своего варианта, по разделу каталога своего типа'}>{layer.name}</Fixed>
        )}
        <Field label="Примечание">
          <Tip label={asset ? 'До 500 знаков; уходит в учёт с историей и видно в карточке объекта' : 'До 500 знаков; сохраняется в варианте вместе с предметом'}>
            <Input value={sel.note ?? ''} placeholder="артикул, поставщик…" maxLength={500} onChange={(e) => p.onUpdate(sel.id, { note: e.target.value || undefined })} />
          </Tip>
        </Field>
        {row ? (
          <div className="grid grid-cols-2 gap-2 rounded-md border border-border p-2">
            <NumField label="Штук" value={row.n} min={2} max={50} onChange={(v) => setRow({ ...row, n: Math.round(v) })} hint="Всего в ряду вместе с выбранным, 2–50" />
            <NumField label="Зазор, см" value={cm(row.gap)} min={0} max={1000} onChange={(v) => setRow({ ...row, gap: v / 100 })} hint="Расстояние между соседними предметами, 0–1000 см" />
            <Button size="sm" hint={asset ? 'Поставить копии вдоль ширины; спросит номер первого нового объекта, остальные пойдут подряд' : 'Поставить копии вдоль ширины предмета'}
              onClick={() => { p.onRow(sel.id, row.n, row.gap); setRow(null) }}>Создать ряд</Button>
            <Button size="sm" variant="secondary" onClick={() => setRow(null)}>Отмена</Button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            <Button variant="outline" size="sm" hint={asset ? 'Такой же рядом (Ctrl+D): новый объект учёта, спросит инвентарный номер' : 'Такой же предмет рядом (Ctrl+D)'}
              onClick={() => p.onDuplicate(sel.id)}><Copy /> Копия</Button>
            <Button variant="outline" size="sm" hint="Несколько одинаковых в линию вдоль ширины, с заданным зазором" onClick={() => setRow({ n: 3, gap: 0 })}><Columns3 /> Ряд…</Button>
            {!asset && <Button variant="ghost" size="sm" className="ml-auto text-destructive" hint="Убрать предмет из варианта (Delete); Ctrl+Z вернёт" onClick={() => p.onDelete(sel.id)}><Trash2 /> Удалить</Button>}
          </div>
        )}
      </fieldset>
    </div>
  )
}
