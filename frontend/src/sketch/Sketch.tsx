import { BrickWall, DoorOpen, Eye, EyeOff, FlipHorizontal2, FlipVertical2, ImagePlus, Maximize2, Move, Ruler, MousePointer2, Plus, Redo2, Trash2, Undo2, type LucideIcon } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { floatClass } from '@/components/ui/float'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import {
  allSides, checkFloor, findRooms, labelRoom, moveNode, moveOpening, OPENING_DEFAULTS, removeOpening, removeWall, setOpening, setWall, setWallLength,
  WALL_DEFAULTS, wallLength, wallsAt,
  type Floor, type Opening, type OpeningKind, type Sketch as Sketch_, type WallKind,
} from '@/plan'
import { dist, type XY } from '@/plan/vec'
import { underlayUrl, uploadUnderlay } from '@/api'
import { Canvas, type Selection, type Tool } from './Canvas'
import { areaText } from './format'
import { calibrate, placeUnderlay } from './underlay'
import { BuildCard } from './BuildCard'
import { useSketch, type SketchState } from './state'

const TOOLS: { id: Tool; label: string; key: string; icon: LucideIcon; hint: string }[] = [
  { id: 'select', label: 'Выбор', key: 'V', icon: MousePointer2, hint: 'Выбрать и двигать стены, углы и помещения; клавиша V' },
  { id: 'wall', label: 'Стена', key: 'W', icon: BrickWall, hint: 'Рисовать стены от угла к углу с привязкой к углам и стенам; клавиша W' },
  { id: 'opening', label: 'Проём', key: 'O', icon: DoorOpen, hint: 'Ставить двери, окна, витражи и проходы в стены; клавиша O' },
]
const THICKNESS_CM = [8, 10, 12, 20, 25, 38, 51]
const KIND_LABEL: Record<WallKind, string> = { bearing: 'Несущая', partition: 'Перегородка' }
const OPENING_LABEL: Record<OpeningKind, string> = { door: 'Дверь', window: 'Окно', vitrage: 'Витраж', passage: 'Проход' }
/** usual widths, cm */
const OPENING_WIDTHS: Record<OpeningKind, number[]> = {
  door: [60, 70, 80, 90, 100, 120, 140],
  window: [60, 90, 120, 150, 180, 210],
  vitrage: [150, 200, 250, 300, 400],
  passage: [70, 80, 90, 120, 150, 200],
}

/** A number in centimetres, applied on Enter or when the field is left; refused (`onApply` gives false), the field shows the value again. */
function CmField({ value, onApply, placeholder, min = 1, testid }: {
  value: number | null; onApply: (m: number | null) => unknown; placeholder?: string; min?: number; testid?: string
}) {
  const shown = value === null ? '' : String(Math.round(value * 1000) / 10)
  const [text, setText] = useState(shown)
  const [was, setWas] = useState(shown)
  if (shown !== was) { setWas(shown); setText(shown) }
  const apply = () => {
    if (text.trim() === '' && placeholder) { onApply(null); return }
    const v = Number(text.replace(',', '.'))
    if (!Number.isFinite(v) || v < min || onApply(v / 100) === false) setText(shown)
  }
  return (
    <div className="relative">
      <Input value={text} placeholder={placeholder} inputMode="decimal" className="pr-8 tabular-nums" data-testid={testid}
        onChange={e => setText(e.target.value)} onBlur={apply} onKeyDown={e => { if (e.key === 'Enter') { apply(); e.currentTarget.blur() } }} />
      <span className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-xs text-muted-foreground">см</span>
    </div>
  )
}

function TextField({ value, onApply, placeholder, testid }: { value: string; onApply: (v: string) => void; placeholder?: string; testid?: string }) {
  const [text, setText] = useState(value)
  const [was, setWas] = useState(value)
  if (value !== was) { setWas(value); setText(value) }
  return <Input value={text} placeholder={placeholder} data-testid={testid} onChange={e => setText(e.target.value)}
    onBlur={() => text !== value && onApply(text.trim())} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />
}

const Row = ({ label, children }: { label: string; children: ReactNode }) => (
  <label className="grid grid-cols-[6.5rem_1fr] items-center gap-2 text-sm"><span className="text-muted-foreground">{label}</span>{children}</label>
)

/** The 2D editor of a plan drawn from scratch: the plan of a drawing of kind «sketch», saved as one draws. */
export function Sketch({ drawing }: { drawing: string }) {
  const st = useSketch(drawing)
  if (!st.sketch || !st.floor) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
        <h1 className="text-lg font-semibold">{st.status === 'loading' ? 'Загрузка плана…' : 'План не открылся'}</h1>
        {st.error && <p className="max-w-sm text-sm text-muted-foreground">{st.error}</p>}
        {st.status === 'failed' && <Button onClick={st.reload} hint="Ещё раз запросить план у сервера">Повторить</Button>}
      </div>
    )
  }
  return <Editor st={st as Loaded} drawing={drawing} />
}

type Loaded = SketchState & { sketch: Sketch_; floor: Floor }

function Editor({ st, drawing }: { st: Loaded; drawing: string }) {
  const { floor, commit, undo, redo } = st
  const [tool, setTool] = useState<Tool>('wall')
  const [kind, setKind] = useState<WallKind>('bearing')
  const [thickness, setThickness] = useState<Record<WallKind, number>>({ bearing: WALL_DEFAULTS.bearing.thickness, partition: WALL_DEFAULTS.partition.thickness })
  const [opening, setOpening_] = useState<OpeningKind>('door')
  const [openingWidth, setOpeningWidth] = useState<Record<OpeningKind, number>>(
    () => Object.fromEntries(Object.entries(OPENING_DEFAULTS).map(([k, v]) => [k, v.width])) as Record<OpeningKind, number>)
  const [selection, setSelection] = useState<Selection | null>(null)
  // two points picked on the picture: its scale waits for their distance
  const [cal, setCal] = useState<[XY, XY] | null>(null)
  const [lastTool, setLastTool] = useState(tool)
  if (tool !== lastTool) { setLastTool(tool); setCal(null) }
  const [fitSignal, setFitSignal] = useState(0)

  const issues = useMemo(() => checkFloor(floor), [floor])
  const bad = useMemo(() => new Set(issues.filter(i => i.level === 'error').flatMap(i => i.ids)), [issues])
  const rooms = useMemo(() => findRooms(floor), [floor])
  const floors = [...st.sketch.floors].sort((a, b) => a.level - b.level)
  const below = floors.filter(f => f.level < floor.level).pop() ?? null
  const wallProps = { ...WALL_DEFAULTS[kind], thickness: thickness[kind] }

  // what was selected may be gone after undo or another edit
  const sel = selection && (
    (selection.kind === 'wall' && selection.id in floor.walls) || (selection.kind === 'node' && selection.id in floor.nodes)
    || (selection.kind === 'opening' && selection.id in floor.openings)
    || (selection.kind === 'room' && rooms.some(r => r.key === selection.key))) ? selection : null

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.code === 'KeyZ') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return }
      if (mod && e.code === 'KeyY') { e.preventDefault(); redo(); return }
      if (mod || e.altKey) return
      if (e.code === 'KeyV') setTool('select')
      if (e.code === 'KeyW') setTool('wall')
      if (e.code === 'KeyO') setTool('opening')
      if (e.code === 'KeyF') setFitSignal(n => n + 1)
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [undo, redo])

  const pickFloor = (id: string) => { st.setFloorId(id); setSelection(null); setFitSignal(n => n + 1) }

  return (
    <div className="relative h-full w-full" data-testid="sketch">
      <Canvas floor={floor} below={below} tool={tool} wallProps={wallProps} selection={sel} onSelect={setSelection}
        openingProps={{ kind: opening, width: openingWidth[opening] }}
        onCommit={commit} fitSignal={fitSignal} bad={bad}
        underlayUrl={floor.underlay ? underlayUrl(drawing, floor.underlay.image) : null}
        onCalibrate={(a, b) => setCal([a, b])} />

      <div className={cn(floatClass, 'absolute top-2 left-2 flex max-w-[calc(100%-1rem)] flex-wrap items-center gap-1 rounded-lg p-1')}>
        {TOOLS.map(t => (
          <Button key={t.id} size="sm" variant={tool === t.id ? 'default' : 'ghost'} hint={t.hint} onClick={() => setTool(t.id)}
            data-testid={`sketch-tool-${t.id}`}>
            <t.icon className="size-4" /><span className="max-sm:hidden">{t.label}</span>
          </Button>
        ))}
        <span className="mx-1 h-5 w-px bg-border" />
        {tool === 'opening' ? (
          <>
            <Select value={opening} onChange={e => setOpening_(e.target.value as OpeningKind)} aria-label="Вид нового проёма" className="w-28" data-testid="sketch-opening-kind">
              {Object.entries(OPENING_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
            <Select value={Math.round(openingWidth[opening] * 100)} aria-label="Ширина нового проёма, см" className="w-24" data-testid="sketch-opening-width"
              onChange={e => setOpeningWidth(w => ({ ...w, [opening]: Number(e.target.value) / 100 }))}>
              {[...new Set([...OPENING_WIDTHS[opening], Math.round(openingWidth[opening] * 100)])].sort((a, b) => a - b).map(v => <option key={v} value={v}>{v} см</option>)}
            </Select>
          </>
        ) : (
          <>
          <Select value={kind} onChange={e => setKind(e.target.value as WallKind)} aria-label="Вид новой стены" className="w-32" data-testid="sketch-kind">
            {Object.entries(KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Select>
          <Select value={Math.round(thickness[kind] * 100)} aria-label="Толщина новой стены, см" className="w-24" data-testid="sketch-thickness"
            onChange={e => setThickness(t => ({ ...t, [kind]: Number(e.target.value) / 100 }))}>
            {[...new Set([...THICKNESS_CM, Math.round(thickness[kind] * 100)])].sort((a, b) => a - b).map(v => <option key={v} value={v}>{v} см</option>)}
          </Select>
          </>
        )}
        <span className="mx-1 h-5 w-px bg-border" />
        <Button size="icon-sm" variant="ghost" aria-label="Отменить" disabled={!st.canUndo} onClick={st.undo} hint="Отменить последнее изменение; Ctrl+Z"><Undo2 className="size-4" /></Button>
        <Button size="icon-sm" variant="ghost" aria-label="Вернуть" disabled={!st.canRedo} onClick={st.redo} hint="Вернуть отменённое; Ctrl+Shift+Z"><Redo2 className="size-4" /></Button>
        <Button size="icon-sm" variant="ghost" aria-label="Весь этаж" onClick={() => setFitSignal(n => n + 1)} hint="Показать весь этаж; клавиша F"><Maximize2 className="size-4" /></Button>
        <span className="mx-1 h-5 w-px bg-border" />
        <Select value={floor.id} onChange={e => pickFloor(e.target.value)} aria-label="Этаж" className="w-28" data-testid="sketch-floor">
          {floors.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
        </Select>
        <Button size="icon-sm" variant="ghost" onClick={st.addFloor} aria-label="Добавить этаж" data-testid="sketch-add-floor" hint="Добавить этаж над верхним: на нём сразу будут несущие стены этажа под ним, без перегородок и проёмов; Ctrl+Z отменит">
          <Plus className="size-4" />
        </Button>
      </div>

      <div className="absolute top-2 right-2 flex w-72 flex-col gap-2 max-md:hidden">
      <BuildCard drawing={drawing} st={st} />
      <aside className={cn(floatClass, 'space-y-3 rounded-lg p-3')} aria-label="Свойства" data-testid="sketch-inspector">
        {sel?.kind === 'opening' ? <OpeningPanel key={sel.id} floor={floor} id={sel.id} onCommit={commit} onDone={() => setSelection(null)} />
          : sel?.kind === 'wall' ? <WallPanel floor={floor} id={sel.id} onCommit={commit} onDone={() => setSelection(null)} />
          : sel?.kind === 'node' ? <NodePanel floor={floor} id={sel.id} onCommit={commit} onDone={() => setSelection(null)} />
            : sel?.kind === 'room' ? <RoomPanel floor={floor} roomKey={sel.key} rooms={rooms} onCommit={commit} onKey={key => setSelection({ kind: 'room', key })} />
              : (
                <>
                  <h2 className="text-sm font-semibold">Этаж</h2>
                  <Row label="Название"><TextField value={floor.name} testid="floor-name" onApply={name => name && commit({ ...floor, name })} /></Row>
                  <Row label="Высота"><CmField value={floor.height} min={50} onApply={h => h && commit({ ...floor, height: h })} /></Row>
                  <p className="text-sm text-muted-foreground" data-testid="sketch-summary">
                    Стен: {Object.keys(floor.walls).length} · помещений: {rooms.length}
                    {rooms.length > 0 && <> · {areaText(rooms.reduce((s, r) => s + r.area, 0))}</>}
                  </p>
                  {issues.length > 0 && (
                    <ul className="space-y-1 text-sm" data-testid="sketch-issues">
                      {issues.map((i, n) => (
                        <li key={n}>
                          <button className={cn('text-left underline-offset-2 hover:underline', i.level === 'error' ? 'text-destructive' : 'text-muted-foreground')}
                            onClick={() => {
                              const o = i.ids.find(x => x in floor.openings), w = i.ids.find(x => x in floor.walls)
                              if (o) setSelection({ kind: 'opening', id: o })
                              else if (w) setSelection({ kind: 'wall', id: w })
                            }}>{i.message}</button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <UnderlayPanel floor={floor} drawing={drawing} onCommit={commit} tool={tool}
                    setTool={t => { setTool(t); setSelection(null) }} cal={cal} />
                  {floors.length > 1 && (
                    <Button size="sm" variant="outline" hint="Убрать этот этаж из плана; Ctrl+Z вернёт"
                      onClick={() => { st.removeFloor(floor.id); setSelection(null) }}>Удалить этаж</Button>
                  )}
                </>
              )}
      </aside>
      </div>
    </div>
  )
}

function WallPanel({ floor, id, onCommit, onDone }: { floor: Floor; id: string; onCommit: (f: Floor) => void; onDone: () => void }) {
  const w = floor.walls[id]
  return (
    <>
      <h2 className="text-sm font-semibold">Стена</h2>
      <Row label="Длина по оси"><CmField value={wallLength(floor, id)} testid="wall-length" onApply={v => v && onCommit(setWallLength(floor, id, v))} /></Row>
      <Row label="Толщина"><CmField value={w.thickness} testid="wall-thickness" onApply={v => v && onCommit(setWall(floor, id, { thickness: v }))} /></Row>
      <Row label="Высота"><CmField value={w.height} placeholder={`${Math.round(floor.height * 100)} — как этаж`} min={10} onApply={v => onCommit(setWall(floor, id, { height: v }))} /></Row>
      <Row label="Вид">
        <Select value={w.kind} onChange={e => onCommit(setWall(floor, id, { kind: e.target.value as WallKind }))}>
          {Object.entries(KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </Select>
      </Row>
      <p className="text-xs text-muted-foreground">Длина меняется от начала стены: её конец сдвигается вместе с примыкающими стенами.</p>
      <Button size="sm" variant="outline" hint="Убрать стену; Delete делает то же, Ctrl+Z вернёт" onClick={() => { onCommit(removeWall(floor, id)); onDone() }}>
        <Trash2 className="size-4" />Удалить стену
      </Button>
    </>
  )
}

function NodePanel({ floor, id, onCommit, onDone }: { floor: Floor; id: string; onCommit: (f: Floor) => void; onDone: () => void }) {
  const p = floor.nodes[id]
  const n = wallsAt(floor, id).length
  return (
    <>
      <h2 className="text-sm font-semibold">Угол</h2>
      <Row label="X"><CmField value={p[0]} min={-1e9} onApply={v => v !== null && onCommit(moveNode(floor, id, [v, p[1]], true))} /></Row>
      <Row label="Y"><CmField value={p[1]} min={-1e9} onApply={v => v !== null && onCommit(moveNode(floor, id, [p[0], v], true))} /></Row>
      <p className="text-xs text-muted-foreground">Сходится стен: {n}. Перетащите угол на другой, чтобы соединить их.</p>
      <Button size="sm" variant="outline" hint="Убрать все стены, что сходятся в этом углу; Ctrl+Z вернёт"
        onClick={() => { onCommit(wallsAt(floor, id).reduce((f, w) => removeWall(f, w), floor)); onDone() }}>
        <Trash2 className="size-4" />Удалить стены угла
      </Button>
    </>
  )
}

function RoomPanel({ floor, roomKey, rooms, onCommit, onKey }: {
  floor: Floor; roomKey: string; rooms: ReturnType<typeof findRooms>; onCommit: (f: Floor) => void; onKey: (key: string) => void
}) {
  const room = rooms.find(r => r.key === roomKey)
  if (!room) return null
  const set = (patch: { name?: string; number?: string }) => {
    const r = labelRoom(floor, room, patch)
    onCommit(r.floor)
    onKey(r.id)
  }
  const perimeter = room.contour.reduce((s, p, i) => s + dist(p, room.contour[(i + 1) % room.contour.length]), 0)
  return (
    <>
      <h2 className="text-sm font-semibold">Помещение</h2>
      <Row label="Номер"><TextField value={room.label?.number ?? ''} testid="room-number" onApply={number => set({ number })} /></Row>
      <Row label="Название"><TextField value={room.label?.name ?? ''} placeholder="Кухня, коридор…" testid="room-name" onApply={name => set({ name })} /></Row>
      <p className="text-sm tabular-nums" data-testid="room-area">
        Площадь {areaText(room.area)} · периметр {perimeter.toFixed(2).replace('.', ',')} м
      </p>
      <p className="text-xs text-muted-foreground">Площадь — по внутренним граням стен. Помещение получается само, когда стены замыкают контур.</p>
    </>
  )
}

function OpeningPanel({ floor, id, onCommit, onDone }: { floor: Floor; id: string; onCommit: (f: Floor) => void; onDone: () => void }) {
  const o = floor.openings[id]
  const sides = allSides(floor)[o.wall]
  const left = o.at - o.width / 2 - sides.from
  const set = (patch: Parameters<typeof setOpening>[2]) => {
    const next = setOpening(floor, id, patch)
    if (next === floor) return false
    onCommit(next)
    return true
  }
  // the refusal stays only while the opening is as it was refused
  const [refused, setRefused] = useState<Opening | null>(null)
  return (
    <>
      <h2 className="text-sm font-semibold">Проём</h2>
      <Row label="Вид">
        <Select value={o.kind} data-testid="opening-kind" onChange={e => {
          // a door turned into a window gets a window's height and sill
          const kind = e.target.value as OpeningKind
          set({ kind, height: OPENING_DEFAULTS[kind].height, sill: OPENING_DEFAULTS[kind].sill })
        }}>
          {Object.entries(OPENING_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </Select>
      </Row>
      <Row label="Ширина"><CmField value={o.width} min={10} testid="opening-width" onApply={v => { const ok = !!v && set({ width: v }); setRefused(ok ? null : o); return ok }} /></Row>
      <Row label="Высота"><CmField value={o.height} min={10} testid="opening-height" onApply={v => v && set({ height: v })} /></Row>
      <Row label="От пола"><CmField value={o.sill} min={0} testid="opening-sill" onApply={v => v !== null && set({ sill: v })} /></Row>
      <Row label="До угла"><CmField value={left} min={0} testid="opening-offset" onApply={v => v !== null && onCommit(moveOpening(floor, id, sides.from + v + o.width / 2))} /></Row>
      {refused === o && <p className="text-xs text-destructive">Такая ширина не помещается: проём упрётся в угол или в соседний проём.</p>}
      {o.kind === 'door' && (
        <div className="flex gap-2">
          <Button size="sm" variant="outline" hint="Перевесить полотно на другой край проёма" onClick={() => set({ hinge: o.hinge === 'a' ? 'b' : 'a' })}>
            <FlipHorizontal2 className="size-4" />Петли
          </Button>
          <Button size="sm" variant="outline" hint="Открывать в другую сторону от стены" onClick={() => set({ side: o.side === 'left' ? 'right' : 'left' })}>
            <FlipVertical2 className="size-4" />Открывание
          </Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground">«До угла» — от края проёма до ближнего к началу стены угла по грани. Проём перетаскивается вдоль стены и на другую стену.</p>
      <Button size="sm" variant="outline" hint="Убрать проём, стена станет сплошной; Delete делает то же, Ctrl+Z вернёт" onClick={() => { onCommit(removeOpening(floor, id)); onDone() }}>
        <Trash2 className="size-4" />Удалить проём
      </Button>
    </>
  )
}

/** The picture under the floor: putting one in, its scale by two points, its place, how much it shows. */
function UnderlayPanel({ floor, drawing, onCommit, tool, setTool, cal }: {
  floor: Floor; drawing: string; onCommit: (f: Floor) => void; tool: Tool; setTool: (t: Tool) => void; cal: [XY, XY] | null
}) {
  const u = floor.underlay ?? null
  const picker = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [opacity, setOpacity] = useState(u?.opacity ?? 0.5)
  const [was, setWas] = useState(u?.opacity)
  if (u?.opacity !== was) { setWas(u?.opacity); setOpacity(u?.opacity ?? 0.5) }

  const put = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      const { id } = await uploadUnderlay(drawing, file)
      const img = new Image()
      img.src = underlayUrl(drawing, id)
      await img.decode()
      const ps = Object.values(floor.nodes)
      const walls: [number, number, number, number] | null = ps.length
        ? [Math.min(...ps.map(p => p[0])), Math.min(...ps.map(p => p[1])), Math.max(...ps.map(p => p[0])), Math.max(...ps.map(p => p[1]))] : null
      onCommit({ ...floor, underlay: placeUnderlay(id, img.naturalWidth, img.naturalHeight, walls) })
      setTool('calibrate')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Картинку не удалось загрузить')
    } finally {
      setBusy(false)
      if (picker.current) picker.current.value = ''
    }
  }
  const set = (patch: Partial<NonNullable<typeof u>>) => u && onCommit({ ...floor, underlay: { ...u, ...patch } })

  return (
    <div className="space-y-2 border-t pt-3" data-testid="sketch-underlay-panel">
      <h3 className="text-sm font-semibold">Подложка</h3>
      <input ref={picker} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" data-testid="underlay-file"
        onChange={e => { const f = e.target.files?.[0]; if (f) void put(f) }} />
      {!u ? (
        <>
          <p className="text-xs text-muted-foreground">Картинка плана — скан, фото, план из объявления, — по которой удобно обводить стены.</p>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => picker.current?.click()}
            hint="Положить под этаж картинку PNG, JPEG или WebP до 20 МБ; затем задать её масштаб по двум точкам">
            <ImagePlus className="size-4" />{busy ? 'Загружается…' : 'Загрузить картинку'}
          </Button>
        </>
      ) : (
        <>
          {tool === 'calibrate' && !cal && (
            <p className="text-xs text-foreground" data-testid="underlay-calibrate-hint">Щёлкните на картинке два конца отрезка известной длины.</p>
          )}
          {cal && (
            <Row label="Длина отрезка">
              <CmField value={null} placeholder={`сейчас ${Math.round(dist(cal[0], cal[1]) * 100)}`} min={1} testid="underlay-length"
                onApply={v => { if (v) { onCommit({ ...floor, underlay: calibrate(u, cal[0], cal[1], v) }); setTool('select') } }} />
            </Row>
          )}
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant={tool === 'calibrate' ? 'default' : 'outline'} onClick={() => setTool(tool === 'calibrate' ? 'select' : 'calibrate')}
              hint="Задать масштаб картинки: щёлкнуть два конца отрезка, длина которого известна, и ввести её" data-testid="underlay-calibrate">
              <Ruler className="size-4" />Масштаб
            </Button>
            <Button size="sm" variant={tool === 'underlay' ? 'default' : 'outline'} onClick={() => setTool(tool === 'underlay' ? 'select' : 'underlay')}
              hint="Перетаскивать картинку мышью, чтобы совместить её со стенами" data-testid="underlay-move">
              <Move className="size-4" />Двигать
            </Button>
            <Button size="icon-sm" variant="ghost" aria-label={u.hidden ? 'Показать подложку' : 'Скрыть подложку'} onClick={() => set({ hidden: !u.hidden })}
              hint={u.hidden ? 'Показать картинку под планом' : 'Спрятать картинку, не убирая её'}>
              {u.hidden ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
            </Button>
            <Button size="icon-sm" variant="ghost" aria-label="Убрать подложку" onClick={() => { onCommit({ ...floor, underlay: null }); setTool('select') }}
              hint="Убрать картинку из-под этажа; Ctrl+Z вернёт">
              <Trash2 className="size-4" />
            </Button>
          </div>
          <Row label="Прозрачность">
            <input type="range" min={0.1} max={1} step={0.05} value={opacity} aria-label="Насколько видна подложка" data-testid="underlay-opacity"
              onChange={e => setOpacity(Number(e.target.value))}
              onPointerUp={() => opacity !== u.opacity && set({ opacity })} onKeyUp={() => opacity !== u.opacity && set({ opacity })} />
          </Row>
        </>
      )}
      {error && <p className="text-xs text-destructive" role="alert">{error}</p>}
    </div>
  )
}
