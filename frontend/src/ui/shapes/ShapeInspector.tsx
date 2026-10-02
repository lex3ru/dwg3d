import { AlertTriangle, ArrowDown, ArrowUp, Check, MapPin, RefreshCw, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type { FloorMeta, Layer, ShapeObject, V3, XY } from '@/api'
import { useConfirm } from '@/components/confirm'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { polyArea, polyLength, routeProps, type ShapeDraft, type ShapeEditor } from '@/hooks/useShapeEditor'
import { cn } from '@/lib/utils'
import { fmtTime, type CableProps, type Conflict, type RouteStop, type Rules, type ZoneProps } from '@/viewer/routing'

const floorName = (floors: FloorMeta[], id: string) => floors.find((f) => f.id === id)?.name ?? '?'
const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label className="grid gap-1 text-xs text-muted-foreground">{label}{children}</label>
)
const stop = (e: React.KeyboardEvent) => e.stopPropagation()

/** A room as a route stop (instead of a click on the plan). */
function RoomPicker({ floors, planOf, onPick }: { floors: FloorMeta[]; planOf: (v: V3) => XY; onPick: (st: RouteStop) => void }) {
  const rooms = floors.flatMap((f) => f.rooms.filter((r) => r.id && (r.name || r.type)).map((r) => ({ f, r })))
  return (
    <Field label="…или помещение">
      <Select value="" onChange={(e) => {
        const hit = rooms.find((x) => String(x.r.id) === e.target.value)
        if (hit) onPick({ floor: hit.f.id, at: planOf(hit.r.label_pos), room: hit.r.id ?? null, label: hit.r.name || hit.r.type || 'помещение' })
      }}>
        <option value="">— выбрать —</option>
        {rooms.map(({ f, r }) => <option key={`${f.id}-${r.id}`} value={String(r.id)}>{f.name} · {r.name || r.type} · {r.area.toFixed(0)} м²</option>)}
      </Select>
    </Field>
  )
}

function Head({ color, square, title, sub, onClose }: { color: string; square?: boolean; title: string; sub: string; onClose?: () => void }) {
  return (
    <div className="flex items-start gap-2">
      <i className={cn('mt-1 size-3 shrink-0', square ? 'rounded-[3px]' : 'rounded-full')} style={{ background: color }} />
      <div className="min-w-0 flex-1"><b className="block truncate">{title}</b><small className="text-xs text-muted-foreground">{sub}</small></div>
      {onClose && <Button variant="ghost" size="icon-sm" aria-label="Снять выделение" onClick={onClose}><X /></Button>}
    </div>
  )
}

/** The thing being drawn: its kind and name, how far it is, finish or cancel. */
export function DraftCard({ ed, draft, rules, floors, planOf }: { ed: ShapeEditor; draft: ShapeDraft; rules: Rules; floors: FloorMeta[]; planOf: (v: V3) => XY }) {
  const set = (patch: Partial<ShapeDraft>) => ed.setDraft({ ...draft, ...patch } as ShapeDraft)
  return (
    <div className="grid gap-3 p-3" onKeyDown={stop}>
      <div className="rounded-md bg-accent p-2 text-xs text-accent-foreground">{ed.hint}</div>
      {draft.what === 'route' && (
        <>
          <Field label="Название"><Input autoFocus value={draft.name} maxLength={200} placeholder="Например, «Первичный приём»" onChange={(e) => set({ name: e.target.value })} /></Field>
          <Field label="Поток">
            <Select value={draft.flow} onChange={(e) => set({ flow: e.target.value })}>
              {Object.entries(rules.flows).map(([k, f]) => <option key={k} value={k}>{f.name}</option>)}
            </Select>
          </Field>
          <ol className="m-0 grid gap-0.5 pl-5 text-xs">{draft.stops.map((s, i) => <li key={i}>{s.label || `Точка ${i + 1}`} <small className="text-muted-foreground">{floorName(floors, s.floor)}</small></li>)}</ol>
          <RoomPicker floors={floors} planOf={planOf} onPick={(st) => ed.addStop(st)} />
        </>
      )}
      {draft.what === 'zone' && (
        <>
          <Field label="Вид зоны">
            <Select value={draft.zone} onChange={(e) => set({ zone: e.target.value })}>
              {Object.entries(rules.zone_kinds).map(([k, z]) => <option key={k} value={k}>{z.name}</option>)}
            </Select>
          </Field>
          <Field label="Название"><Input value={draft.name} maxLength={200} placeholder="Например, «Стерилизационная»" onChange={(e) => set({ name: e.target.value })} /></Field>
          <small className="text-xs text-muted-foreground">{floorName(floors, draft.floor)} · углов: {draft.pts.length}{draft.pts.length >= 3 ? ` · ${polyArea(draft.pts).toFixed(1)} м²` : ''}</small>
        </>
      )}
      {draft.what === 'cable' && (
        <>
          <Field label="Кабель">
            <Select value={draft.cable} onChange={(e) => set({ cable: e.target.value })}>
              {Object.entries(rules.cables).map(([k, x]) => <option key={k} value={k}>{x.name}</option>)}
            </Select>
          </Field>
          <Field label="Название"><Input value={draft.name} maxLength={200} placeholder="Например, «Стояк серверной»" onChange={(e) => set({ name: e.target.value })} /></Field>
          <Field label="Запас, %">
            <Input type="number" min={0} max={100} value={draft.reserve} onChange={(e) => set({ reserve: Math.max(0, Math.min(100, Number(e.target.value) || 0)) })} />
          </Field>
          <small className="text-xs text-muted-foreground">{floorName(floors, draft.floor)} · {polyLength(draft.pts).toFixed(1)} м по плану</small>
        </>
      )}
      <div className="flex gap-1.5">
        {draft.what !== 'route' && (
          <Button size="sm" disabled={draft.pts.length < (draft.what === 'cable' ? 2 : 3)} onClick={ed.finish}><Check /> Готово</Button>
        )}
        <Button size="sm" variant="secondary" onClick={ed.cancel}>Отмена</Button>
      </div>
    </div>
  )
}

/** The selected route: name, flow, stops, way, conflicts. */
export function RouteInspector({ ed, r, rules, floors, conflicts, editable, planOf, flyTo, onClose }: {
  ed: ShapeEditor; r: ShapeObject; rules: Rules; floors: FloorMeta[]; conflicts: Conflict[]; editable: boolean
  planOf: (v: V3) => XY; flyTo: (floor: string, at: XY) => void; onClose: () => void
}) {
  const x = routeProps(r)
  const [name, setName] = useState(x.name)
  const [ask, dialog] = useConfirm()
  const stops = x.stops ?? []
  const change = (props: typeof x) => ed.saveRoute(r.id, props, r)
  const move = (i: number, d: number) => { const s = [...stops]; [s[i], s[i + d]] = [s[i + d], s[i]]; change({ ...x, stops: s }) }
  const mine = conflicts.filter((c) => c.a === r.id || c.b === r.id)
  const adding = ed.adding === r.id
  return (
    <div className="grid gap-3 p-3" onKeyDown={stop}>
      <Head color={rules.flows[x.flow]?.color ?? '#868e96'} title={x.name || rules.flows[x.flow]?.name || 'Маршрут'}
        sub={x.path ? `${x.length?.toFixed(0)} м · ${fmtTime(x.time ?? 0)}${x.floors_changed ? ` · этажей: ${x.floors_changed}` : ''}` : 'путь не рассчитан'} onClose={onClose} />
      {ed.hint && <div className="rounded-md bg-accent p-2 text-xs text-accent-foreground">{ed.hint}</div>}
      {x.problem && <p className="m-0 flex gap-1.5 rounded-md bg-destructive/10 p-2 text-xs text-destructive"><AlertTriangle className="size-3.5 shrink-0" /> {x.problem}</p>}
      {mine.map((c, i) => (
        <button key={i} className="flex cursor-pointer gap-1.5 rounded-md border-0 bg-warning/15 p-2 text-left text-xs text-warning" onClick={() => flyTo(c.floor, c.at)}>
          <AlertTriangle className="size-3.5 shrink-0" /> {c.text}
        </button>
      ))}
      <fieldset disabled={!editable} className="m-0 grid gap-3 border-0 p-0">
        <Field label="Название"><Input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} onBlur={() => name !== x.name && change({ ...x, name })} /></Field>
        <Field label="Поток">
          <Select value={x.flow} onChange={(e) => change({ ...x, flow: e.target.value })}>
            {Object.entries(rules.flows).map(([k, f]) => <option key={k} value={k}>{f.name}</option>)}
          </Select>
        </Field>
        <div className="grid gap-1">
          <b className="text-xs">Остановки</b>
          <ol className="m-0 grid list-none gap-0.5 p-0">
            {stops.map((st, i) => (
              <li key={i} className="flex items-center gap-1 rounded-md px-1 text-xs hover:bg-secondary">
                <span className="w-4 text-muted-foreground">{i + 1}</span>
                <button className="min-w-0 flex-1 cursor-pointer truncate border-0 bg-transparent py-1 text-left text-xs text-foreground" onClick={() => flyTo(st.floor, st.at)}>
                  {st.label || `Точка ${i + 1}`} <small className="text-muted-foreground">{floorName(floors, st.floor)}</small>
                </button>
                {editable && (
                  <>
                    <Button variant="ghost" size="icon-sm" aria-label="Выше" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp /></Button>
                    <Button variant="ghost" size="icon-sm" aria-label="Ниже" disabled={i === stops.length - 1} onClick={() => move(i, 1)}><ArrowDown /></Button>
                    <Button variant="ghost" size="icon-sm" aria-label="Убрать" disabled={stops.length <= 2} onClick={() => change({ ...x, stops: stops.filter((_, k) => k !== i) })}><X /></Button>
                  </>
                )}
              </li>
            ))}
          </ol>
        </div>
        {editable && (
          <>
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" variant={adding ? 'default' : 'outline'} onClick={() => ed.setAdding(adding ? null : r.id)}>
                {adding ? <><Check /> Закончить</> : <><MapPin /> Остановка на плане</>}
              </Button>
              <Button size="sm" variant="outline" title="Пересчитать путь по текущему плану и мебели" onClick={() => change(x)}><RefreshCw /> Пересчитать</Button>
            </div>
            <RoomPicker floors={floors} planOf={planOf} onPick={(st) => change({ ...x, stops: [...stops, st] })} />
            <Button size="sm" variant="ghost" className="justify-self-start text-destructive" onClick={async () => {
              if (await ask({ title: `Удалить маршрут «${x.name || 'без названия'}»?`, confirm: 'Удалить', danger: true })) ed.remove(r)
            }}><Trash2 /> Удалить маршрут</Button>
          </>
        )}
      </fieldset>
      {dialog}
    </div>
  )
}

/** The selected zone or cable line. */
export function OutlineInspector({ ed, s, rules, floors, editable, onClose }: {
  ed: ShapeEditor; s: ShapeObject; rules: Rules; floors: FloorMeta[]; editable: boolean; onClose: () => void
}) {
  const [ask, dialog] = useConfirm()
  const zone = s.geom === 'polygon'
  const z = (s.props ?? {}) as unknown as ZoneProps & CableProps
  const [name, setName] = useState(z.name ?? '')
  const kind = zone ? rules.zone_kinds[z.zone] : rules.cables[z.cable]
  const len = polyLength(s.points ?? []) * (1 + (z.reserve ?? 0) / 100)
  return (
    <div className="grid gap-3 p-3" onKeyDown={stop}>
      <Head color={kind?.color ?? '#868e96'} square title={z.name || kind?.name || (zone ? 'Зона' : 'Трасса')}
        sub={`${floorName(floors, s.floor)} · ${zone ? `${polyArea(s.points ?? []).toFixed(1)} м²` : `${len.toFixed(1)} м${z.reserve ? ` (запас ${z.reserve}%)` : ''}`}`} onClose={onClose} />
      {ed.hint && <div className="rounded-md bg-accent p-2 text-xs text-accent-foreground">{ed.hint}</div>}
      <fieldset disabled={!editable} className="m-0 grid gap-3 border-0 p-0">
        <Field label="Название"><Input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} onBlur={() => name !== (z.name ?? '') && ed.update(s, { ...z, name })} /></Field>
        {zone ? (
          <Field label="Вид зоны">
            <Select value={z.zone} onChange={(e) => ed.update(s, { ...z, zone: e.target.value })}>
              {Object.entries(rules.zone_kinds).map(([k, x]) => <option key={k} value={k}>{x.name}</option>)}
            </Select>
          </Field>
        ) : (
          <div className="grid grid-cols-[1fr_6rem] gap-2">
            <Field label="Кабель">
              <Select value={z.cable} onChange={(e) => ed.update(s, { ...z, cable: e.target.value })}>
                {Object.entries(rules.cables).map(([k, x]) => <option key={k} value={k}>{x.name}</option>)}
              </Select>
            </Field>
            <Field label="Запас, %">
              <Input type="number" min={0} max={100} defaultValue={z.reserve ?? 0}
                onBlur={(e) => { const v = Math.max(0, Math.min(100, Number(e.target.value) || 0)); if (v !== (z.reserve ?? 0)) ed.update(s, { ...z, reserve: v }) }} />
            </Field>
          </div>
        )}
        {editable && (
          <Button size="sm" variant="ghost" className="justify-self-start text-destructive" onClick={async () => {
            if (await ask({ title: zone ? 'Удалить зону?' : 'Удалить трассу?', confirm: 'Удалить', danger: true })) ed.remove(s)
          }}><Trash2 /> Удалить</Button>
        )}
      </fieldset>
      {dialog}
    </div>
  )
}

/** The layer being edited, nothing selected: its objects, checks and totals. */
export function LayerShapes({ ed, layer, shapes, rules, floors, conflicts, editable, onSelect }: {
  ed: ShapeEditor; layer: Layer; shapes: ShapeObject[]; rules: Rules; floors: FloorMeta[]; conflicts: Conflict[]
  editable: boolean; onSelect: (s: ShapeObject) => void
}) {
  const mine = shapes.filter((s) => s.layer === layer.id)
  const cables = mine.filter((s) => s.geom === 'polyline')
  const totals = Object.entries(cables.reduce<Record<string, number>>((acc, x) => {
    const pr = (x.props ?? {}) as unknown as CableProps
    acc[pr.cable] = (acc[pr.cable] ?? 0) + polyLength(x.points ?? []) * (1 + (pr.reserve ?? 0) / 100)
    return acc
  }, {}))
  const item = (s: ShapeObject) => {
    if (s.geom === 'route') {
      const x = routeProps(s)
      return { color: rules.flows[x.flow]?.color, title: x.name || rules.flows[x.flow]?.name || 'Маршрут',
        sub: x.path ? `${x.length?.toFixed(0)} м · ${fmtTime(x.time ?? 0)}` : 'путь не рассчитан', bad: !!x.problem || conflicts.some((c) => c.a === s.id || c.b === s.id) }
    }
    const z = (s.props ?? {}) as unknown as ZoneProps & CableProps
    const k = s.geom === 'polygon' ? rules.zone_kinds[z.zone] : rules.cables[z.cable]
    return { color: k?.color, title: z.name || k?.name || 'Объект', sub: `${k?.name ?? ''} · ${floorName(floors, s.floor)}`, bad: false }
  }
  return (
    <div className="grid gap-3 p-3 text-sm">
      <div><b className="block">{layer.name}</b><small className="text-xs text-muted-foreground">{mine.length} объектов на чертеже</small></div>
      {ed.hint && <div className="rounded-md bg-accent p-2 text-xs text-accent-foreground">{ed.hint}</div>}
      {editable && !mine.length && (
        <p className="m-0 text-xs text-muted-foreground">
          {layer.kind === 'routes' ? 'Маршрут — путь человека через помещения и этажи: вход → регистратура → кабинет → выход. Длина и время считаются по плану.'
            : layer.kind === 'zones' ? 'Зоны — области этажа: чистая, грязная, с ограниченным доступом. Маршруты проверяются по ним.'
              : 'Трассы СКС и электрики рисуются по плану; их длина с запасом попадает в спецификацию.'}
          {' '}Начните кнопкой в панели сверху.
        </p>
      )}
      <ul className="m-0 grid list-none gap-0.5 p-0">
        {mine.map((s) => {
          const it = item(s)
          return (
            <li key={s.id}>
              <button className="flex w-full cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-1.5 py-1 text-left text-foreground hover:bg-secondary" onClick={() => onSelect(s)}>
                <i className={cn('size-2.5 shrink-0', s.geom === 'route' ? 'rounded-full' : 'rounded-[3px]')} style={{ background: it.color ?? '#868e96' }} />
                <span className="min-w-0 flex-1 leading-tight"><span className="block truncate text-sm">{it.title}</span><small className="text-[11px] text-muted-foreground">{it.sub}</small></span>
                {it.bad && <AlertTriangle className="size-3.5 shrink-0 text-warning" />}
              </button>
            </li>
          )
        })}
      </ul>
      {totals.length > 0 && <p className="m-0 text-xs text-muted-foreground">Итого: {totals.map(([k, v]) => `${rules.cables[k]?.name ?? k} — ${v.toFixed(1)} м`).join('; ')}</p>}
      {(layer.kind === 'routes' || layer.kind === 'zones') && (
        <section className="grid gap-1">
          <b className="text-xs">Проверки потоков</b>
          {!conflicts.length && <p className="m-0 text-xs text-success">Потоки не пересекаются, запретные зоны не нарушены.</p>}
          {conflicts.map((c, i) => {
            const s = shapes.find((x) => x.id === c.a)
            return (
              <button key={i} className="flex cursor-pointer gap-1.5 rounded-md border-0 bg-warning/15 p-1.5 text-left text-xs text-warning" onClick={() => s && onSelect(s)}>
                <AlertTriangle className="size-3.5 shrink-0" /> {c.text} <small className="ml-auto text-muted-foreground">{floorName(floors, c.floor)}</small>
              </button>
            )
          })}
          <small className="text-[11px] text-muted-foreground">Правила: {rules.flow_conflicts.map(([a, b]) => `${rules.flows[a]?.name.toLowerCase()} × ${rules.flows[b]?.name.toLowerCase()}`).join('; ')}</small>
        </section>
      )}
    </div>
  )
}

