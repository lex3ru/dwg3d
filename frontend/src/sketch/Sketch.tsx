import { BrickWall, Maximize2, MousePointer2, Plus, Redo2, Trash2, Undo2, type LucideIcon } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useConfirm } from '@/components/confirm'
import { Button } from '@/components/ui/button'
import { floatClass } from '@/components/ui/float'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import {
  checkFloor, findRooms, labelRoom, moveNode, removeWall, setWall, setWallLength, WALL_DEFAULTS, wallLength, wallsAt,
  type Floor, type WallKind,
} from '@/plan'
import { dist } from '@/plan/vec'
import { Canvas, type Selection, type Tool } from './Canvas'
import { areaText } from './format'
import { useSketch } from './state'

const TOOLS: { id: Tool; label: string; key: string; icon: LucideIcon; hint: string }[] = [
  { id: 'select', label: 'Выбор', key: 'V', icon: MousePointer2, hint: 'Выбрать и двигать стены, углы и помещения; клавиша V' },
  { id: 'wall', label: 'Стена', key: 'W', icon: BrickWall, hint: 'Рисовать стены от угла к углу с привязкой к углам и стенам; клавиша W' },
]
const THICKNESS_CM = [8, 10, 12, 20, 25, 38, 51]
const KIND_LABEL: Record<WallKind, string> = { bearing: 'Несущая', partition: 'Перегородка' }

/** A number in centimetres, applied on Enter or when the field is left. */
function CmField({ value, onApply, placeholder, min = 1, testid }: {
  value: number | null; onApply: (m: number | null) => void; placeholder?: string; min?: number; testid?: string
}) {
  const shown = value === null ? '' : String(Math.round(value * 1000) / 10)
  const [text, setText] = useState(shown)
  const [was, setWas] = useState(shown)
  if (shown !== was) { setWas(shown); setText(shown) }
  const apply = () => {
    if (text.trim() === '' && placeholder) { onApply(null); return }
    const v = Number(text.replace(',', '.'))
    if (Number.isFinite(v) && v >= min) onApply(v / 100)
    else setText(shown)
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

/** The 2D editor of a plan drawn from scratch. */
export function Sketch() {
  const st = useSketch()
  const { floor, commit, undo, redo } = st
  const [tool, setTool] = useState<Tool>('wall')
  const [kind, setKind] = useState<WallKind>('bearing')
  const [thickness, setThickness] = useState<Record<WallKind, number>>({ bearing: WALL_DEFAULTS.bearing.thickness, partition: WALL_DEFAULTS.partition.thickness })
  const [selection, setSelection] = useState<Selection | null>(null)
  const [fitSignal, setFitSignal] = useState(0)
  const [ask, dialog] = useConfirm()

  const issues = useMemo(() => checkFloor(floor), [floor])
  const issueWalls = useMemo(() => new Set(issues.filter(i => i.level === 'error').flatMap(i => i.ids).filter(id => id in floor.walls)), [issues, floor])
  const rooms = useMemo(() => findRooms(floor), [floor])
  const floors = [...st.sketch.floors].sort((a, b) => a.level - b.level)
  const below = floors.filter(f => f.level < floor.level).pop() ?? null
  const wallProps = { ...WALL_DEFAULTS[kind], thickness: thickness[kind] }

  // what was selected may be gone after undo or another edit
  const sel = selection && (
    (selection.kind === 'wall' && selection.id in floor.walls) || (selection.kind === 'node' && selection.id in floor.nodes)
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
      if (e.code === 'KeyF') setFitSignal(n => n + 1)
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [undo, redo])

  const pickFloor = (id: string) => { st.setFloorId(id); setSelection(null); setFitSignal(n => n + 1) }

  return (
    <div className="relative h-full w-full" data-testid="sketch">
      <Canvas floor={floor} below={below} tool={tool} wallProps={wallProps} selection={sel} onSelect={setSelection}
        onCommit={commit} fitSignal={fitSignal} issueWalls={issueWalls} />

      <div className={cn(floatClass, 'absolute top-2 left-2 flex max-w-[calc(100%-1rem)] flex-wrap items-center gap-1 rounded-lg p-1')}>
        {TOOLS.map(t => (
          <Button key={t.id} size="sm" variant={tool === t.id ? 'default' : 'ghost'} hint={t.hint} onClick={() => setTool(t.id)}
            data-testid={`sketch-tool-${t.id}`}>
            <t.icon className="size-4" /><span className="max-sm:hidden">{t.label}</span>
          </Button>
        ))}
        <span className="mx-1 h-5 w-px bg-border" />
        <Select value={kind} onChange={e => setKind(e.target.value as WallKind)} aria-label="Вид новой стены" className="w-32" data-testid="sketch-kind">
          {Object.entries(KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </Select>
        <Select value={Math.round(thickness[kind] * 100)} aria-label="Толщина новой стены, см" className="w-24" data-testid="sketch-thickness"
          onChange={e => setThickness(t => ({ ...t, [kind]: Number(e.target.value) / 100 }))}>
          {[...new Set([...THICKNESS_CM, Math.round(thickness[kind] * 100)])].sort((a, b) => a - b).map(v => <option key={v} value={v}>{v} см</option>)}
        </Select>
        <span className="mx-1 h-5 w-px bg-border" />
        <Button size="icon-sm" variant="ghost" disabled={!st.canUndo} onClick={st.undo} hint="Отменить последнее изменение; Ctrl+Z"><Undo2 className="size-4" /></Button>
        <Button size="icon-sm" variant="ghost" disabled={!st.canRedo} onClick={st.redo} hint="Вернуть отменённое; Ctrl+Shift+Z"><Redo2 className="size-4" /></Button>
        <Button size="icon-sm" variant="ghost" onClick={() => setFitSignal(n => n + 1)} hint="Показать весь этаж; клавиша F"><Maximize2 className="size-4" /></Button>
        <span className="mx-1 h-5 w-px bg-border" />
        <Select value={floor.id} onChange={e => pickFloor(e.target.value)} aria-label="Этаж" className="w-28" data-testid="sketch-floor">
          {floors.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
        </Select>
        <Button size="icon-sm" variant="ghost" onClick={st.addFloor} hint="Добавить этаж над верхним; стены нижнего этажа видны под ним бледно">
          <Plus className="size-4" />
        </Button>
      </div>

      <aside className={cn(floatClass, 'absolute top-2 right-2 w-72 space-y-3 rounded-lg p-3 max-md:hidden')} aria-label="Свойства" data-testid="sketch-inspector">
        {sel?.kind === 'wall' ? <WallPanel floor={floor} id={sel.id} onCommit={commit} onDone={() => setSelection(null)} />
          : sel?.kind === 'node' ? <NodePanel floor={floor} id={sel.id} onCommit={commit} onDone={() => setSelection(null)} />
            : sel?.kind === 'room' ? <RoomPanel floor={floor} roomKey={sel.key} rooms={rooms} onCommit={commit} onKey={key => setSelection({ kind: 'room', key })} />
              : (
                <>
                  <h2 className="text-sm font-semibold">Этаж</h2>
                  <Row label="Название"><TextField value={floor.name} onApply={name => name && commit({ ...floor, name })} /></Row>
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
                            onClick={() => { const id = i.ids.find(x => x in floor.walls); if (id) setSelection({ kind: 'wall', id }) }}>{i.message}</button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="text-xs text-muted-foreground">
                    {st.unsaved ? 'Черновик не удаётся сохранить в этом браузере: после перезагрузки он пропадёт.' : 'Черновик сохраняется в этом браузере.'}
                  </p>
                  <div className="flex gap-2">
                    {floors.length > 1 && (
                      <Button size="sm" variant="outline" hint="Убрать этот этаж из плана; Ctrl+Z вернёт"
                        onClick={() => { st.removeFloor(floor.id); setSelection(null) }}>Удалить этаж</Button>
                    )}
                    <Button size="sm" variant="outline" hint="Начать с чистого листа; Ctrl+Z вернёт нарисованное"
                      onClick={async () => { if (await ask({ title: 'Начать новый план?', text: 'Нарисованное уйдёт с экрана; Ctrl+Z вернёт его.', confirm: 'Начать заново', danger: true })) { st.reset(); setSelection(null); setFitSignal(n => n + 1) } }}>
                      Новый план
                    </Button>
                  </div>
                </>
              )}
      </aside>
      {dialog}
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
