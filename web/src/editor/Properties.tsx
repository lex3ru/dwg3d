import { Footprints, Scissors, Trash2 } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { usePurposes } from "@/catalog/parts";
import { Button } from "@/ui/button";
import { remove } from "./ops";
import { OPENING_TITLES, centerline, dist, polylineLength, type FloorInfo, type Lift, type OpeningKind, type Plan } from "./plan";
import { useEditor, type EditorStore, type Sel } from "./store";
import type { WallDefaults } from "./Canvas";

// Свойства выбранного (5.3.1 «справа»): числа правятся на месте, Enter или уход с поля —
// один шаг отмены.

export function NumberField({ label, value, unit, onChange, step = 1, min, max, disabled, digits = 0, hint }: {
  label: string; value: number; unit?: string; onChange: (v: number) => void; step?: number; min?: number; max?: number; disabled?: boolean; digits?: number;
  // подсказка под полем, где неочевидно, что писать (8.6 п. 3)
  hint?: string;
}) {
  const shown = Number(value.toFixed(digits));
  const [text, setText] = useState(String(shown));
  useEffect(() => setText(String(shown)), [shown]);
  const commit = () => {
    const v = Number.parseFloat(text.replace(",", "."));
    if (Number.isFinite(v) && (min === undefined || v >= min) && (max === undefined || v <= max)) {
      if (v !== shown) onChange(v);
    } else setText(String(shown));
  };
  const hintId = useId();
  const field = (
    <label className="flex flex-col gap-1 text-[12px] text-ink-2">
      {label}
      <span className="flex items-center gap-1.5">
        <input
          type="text"
          inputMode="decimal"
          aria-describedby={hint ? hintId : undefined}
          value={text}
          disabled={disabled}
          step={step}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            e.stopPropagation();
          }}
          className="h-8 w-full min-w-0 rounded-md border border-line-strong bg-surface px-2 font-mono text-[13px] text-ink max-md:h-11"
        />
        {unit && <span className="shrink-0 text-ink-3">{unit}</span>}
      </span>
    </label>
  );
  return hint ? <Hinted id={hintId} hint={hint}>{field}</Hinted> : field;
}

// подсказка — описанием поля (aria-describedby), а не частью его названия
function Hinted({ id, hint, children }: { id: string; hint: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      {children}
      <span id={id} className="text-[11px] leading-snug text-ink-3">{hint}</span>
    </div>
  );
}

export function TextField({ label, value, onChange, placeholder, disabled, hint }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; disabled?: boolean; hint?: string }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const hintId = useId();
  const field = (
    <label className="flex flex-col gap-1 text-[12px] text-ink-2">
      {label}
      <input
        value={text}
        aria-describedby={hint ? hintId : undefined}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => text !== value && onChange(text.trim())}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          e.stopPropagation();
        }}
        className="h-8 rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink max-md:h-11"
      />
    </label>
  );
  return hint ? <Hinted id={hintId} hint={hint}>{field}</Hinted> : field;
}

export function Segmented<T extends string>({ label, value, options, onChange, disabled }: { label: string; value: T; options: { value: T; title: string }[]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-col gap-1 text-[12px] text-ink-2">
      {label}
      <div role="radiogroup" aria-label={label} className="flex rounded-md border border-line-strong p-0.5">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={value === o.value}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={cn("h-7 flex-1 cursor-pointer rounded border-0 px-2 text-[12px] max-md:h-11", value === o.value ? "bg-accent text-on-accent" : "bg-transparent text-ink hover:bg-surface-2")}
          >
            {o.title}
          </button>
        ))}
      </div>
    </div>
  );
}

// Назначение помещения из справочника (5.2): от него — норма освещённости и рабочая поверхность
function PurposeField({ value, onChange, disabled }: { value: string | null; onChange: (v: string | null) => void; disabled?: boolean }) {
  const list = usePurposes(true);
  const items = list.data?.items ?? [];
  const current = items.find((p) => p.id === value);
  return (
    <label className="flex flex-col gap-1 text-[12px] text-ink-2">
      Назначение
      <select
        aria-label="Назначение"
        value={value ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value || null)}
        className="h-8 rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink max-md:h-11"
      >
        <option value="">не задано</option>
        {items
          .filter((p) => !p.archived || p.id === value)
          .map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
              {p.archived ? " (в архиве)" : ""}
            </option>
          ))}
      </select>
      {current && (
        <span className="text-ink-3">
          норма {current.norm} лк на высоте {(current.surface / 1000).toLocaleString("ru-RU")} м
        </span>
      )}
    </label>
  );
}

function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-b border-line px-4 py-4">
      <h3 className="m-0 text-sm font-semibold">{title}</h3>
      {children}
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </section>
  );
}

const grid2 = "grid grid-cols-2 gap-2.5";

export function Properties({
  store, readOnly, floors, floorId, wallDefaults, setWallDefaults, onLiftChange, onLiftDelete,
}: {
  store: EditorStore;
  readOnly: boolean;
  floors: FloorInfo[];
  floorId: string;
  wallDefaults: WallDefaults;
  setWallDefaults: (d: WallDefaults) => void;
  onLiftChange: (lift: Lift, patch: Partial<Lift>) => void;
  onLiftDelete: (lift: Lift) => void;
}) {
  const plan = useEditor(store, (s) => s.plan);
  const selection = useEditor(store, (s) => s.selection);
  const tool = useEditor(store, (s) => s.tool);
  const check = useEditor(store, (s) => s.check);
  const lifts = useEditor(store, (s) => s.lifts);
  const edit = (change: (p: Plan) => void) => store.apply(change);
  const del = () => store.apply((p) => remove(p, selection), []);
  const ro = readOnly;
  const admin = useMe().role === "admin";

  if (selection.length > 1) {
    return (
      <Section title={`Выбрано: ${selection.length}`} actions={!ro && <Button size="sm" variant="danger" onClick={del}><Trash2 /> Удалить</Button>}>
        <p className="m-0 text-[13px] text-ink-2">Перетащите, чтобы сдвинуть всё вместе; Ctrl+C и Ctrl+V — копия.</p>
      </Section>
    );
  }
  const sel: Sel | undefined = selection[0];

  if (!sel) {
    if (!ro && (tool === "wall" || tool === "arc"))
      return (
        <Section title="Новая стена">
          <Segmented label="Вид" value={wallDefaults.kind} onChange={(kind) => setWallDefaults({ ...wallDefaults, kind, thickness: kind === "bearing" ? 380 : 120 })} options={[{ value: "partition", title: "Перегородка" }, { value: "bearing", title: "Несущая" }]} />
          <NumberField label="Толщина" unit="мм" value={wallDefaults.thickness} min={10} max={3000} onChange={(thickness) => setWallDefaults({ ...wallDefaults, thickness })} />
          <p className="m-0 text-[13px] text-ink-2">
            {tool === "wall" ? "Щелчок — начало, щелчки дальше — цепочка стен. Enter — ввести длину, Esc — закончить." : "Щелчок — начало, второй — конец, третий — насколько выгнуть."}
          </p>
        </Section>
      );
    const floor = floors.find((f) => f.id === floorId);
    return (
      <Section title={floor?.name ?? "Этаж"}>
        <div className="text-[13px] text-ink-2">
          Стен {plan.walls.length}, проёмов {plan.openings.length}, помещений {check?.rooms.length ?? "…"}
        </div>
        <p className="m-0 text-[13px] text-ink-2">Выберите стену, проём, помещение или другой элемент, чтобы увидеть и изменить его свойства.</p>
      </Section>
    );
  }

  if (sel.kind === "wall" || sel.kind === "node") {
    const wall = sel.kind === "wall" ? plan.walls.find((w) => w.id === sel.id) : plan.walls.find((w) => w.a === sel.id || w.b === sel.id);
    if (!wall) return null;
    const line = centerline(plan, wall);
    const length = polylineLength(line);
    const openings = plan.openings.filter((o) => o.wall === wall.id).length;
    const setLength = (mm: number) =>
      edit((p) => {
        const w = p.walls.find((x) => x.id === wall.id)!;
        const a = p.nodes[w.a]!;
        const b = p.nodes[w.b]!;
        const d = dist(a, b) || 1;
        p.nodes[w.b] = [a[0] + ((b[0] - a[0]) / d) * mm, a[1] + ((b[1] - a[1]) / d) * mm];
      });
    const set = (patch: Partial<typeof wall>) => edit((p) => Object.assign(p.walls.find((x) => x.id === wall.id)!, patch));
    return (
      <Section
        title={`Стена · ${wall.kind === "bearing" ? "несущая" : "перегородка"}`}
        actions={
          !ro && (
            <>
              <Button size="sm" onClick={() => store.set({ tool: "cut" })}>
                <Scissors /> Разрезать
              </Button>
              <Button size="sm" variant="danger" onClick={del}>
                <Trash2 /> Удалить
              </Button>
            </>
          )
        }
      >
        <div className="text-[13px] text-ink-2">{openings ? `Проёмов: ${openings}` : "Без проёмов"}</div>
        <div className={grid2}>
          <NumberField label="Длина" unit="м" digits={3} value={length / 1000} min={0.01} onChange={(m) => setLength(m * 1000)} disabled={ro || Math.abs(wall.bulge) > 1e-9} />
          <NumberField label="Толщина" unit="мм" value={wall.thickness} min={10} max={3000} onChange={(thickness) => set({ thickness })} disabled={ro} />
        </div>
        <Segmented label="Вид" value={wall.kind} disabled={ro} onChange={(kind) => set({ kind })} options={[{ value: "partition", title: "Перегородка" }, { value: "bearing", title: "Несущая" }]} />
        {Math.abs(wall.bulge) > 1e-9 && (
          <NumberField label="Стрелка дуги" unit="мм" hint="Насколько середина дуги отходит от прямой между концами; 0 — прямая стена." value={(wall.bulge * dist(plan.nodes[wall.a]!, plan.nodes[wall.b]!)) / 2} disabled={ro} onChange={(s) => set({ bulge: Math.max(-1, Math.min(1, (2 * s) / dist(plan.nodes[wall.a]!, plan.nodes[wall.b]!))) })} />
        )}
      </Section>
    );
  }

  if (sel.kind === "opening") {
    const o = plan.openings.find((x) => x.id === sel.id);
    if (!o) return null;
    const wall = plan.walls.find((w) => w.id === o.wall);
    const length = wall ? polylineLength(centerline(plan, wall)) : 0;
    const set = (patch: Partial<typeof o>) => edit((p) => Object.assign(p.openings.find((x) => x.id === o.id)!, patch));
    return (
      <Section title={OPENING_TITLES[o.kind]} actions={!ro && <Button size="sm" variant="danger" onClick={del}><Trash2 /> Удалить</Button>}>
        <Segmented<OpeningKind> label="Вид" value={o.kind} disabled={ro} onChange={(kind) => set({ kind })} options={(["door", "window", "passage", "glazing"] as const).map((k) => ({ value: k, title: OPENING_TITLES[k] }))} />
        <div className={grid2}>
          <NumberField label="Ширина" unit="мм" value={o.width} min={100} max={length} disabled={ro} onChange={(width) => set({ width })} />
          <NumberField label="Высота" unit="мм" value={o.height} min={100} disabled={ro} onChange={(height) => set({ height })} />
          {(o.kind === "window" || o.kind === "glazing") && <NumberField label="Подоконник" unit="мм" hint="Высота низа окна от пола." value={o.sill} min={0} disabled={ro} onChange={(sill) => set({ sill })} />}
          <NumberField label="От начала стены" unit="мм" hint="Расстояние от начала стены до края проёма." value={o.at - o.width / 2} min={0} max={length - o.width} disabled={ro} onChange={(s) => set({ at: s + o.width / 2 })} />
        </div>
        {o.kind === "door" && (
          <>
            <Segmented label="Петли" value={o.hinge} disabled={ro} onChange={(hinge) => set({ hinge })} options={[{ value: "start", title: "У начала" }, { value: "end", title: "У конца" }]} />
            <Segmented label="Открывается" value={o.side} disabled={ro} onChange={(side) => set({ side })} options={[{ value: "left", title: "Влево" }, { value: "right", title: "Вправо" }]} />
          </>
        )}
        <TextField label="Обозначение" hint="Марка проёма по проекту, печатается на плане." value={o.label ?? ""} placeholder="Д-201" disabled={ro} onChange={(label) => set({ label: label || null })} />
      </Section>
    );
  }

  if (sel.kind === "room") {
    const r = plan.rooms.find((x) => x.id === sel.id);
    if (!r) return null;
    const shape = check?.rooms.find((s) => s.label === r.id);
    const set = (patch: Partial<typeof r>) => edit((p) => Object.assign(p.rooms.find((x) => x.id === r.id)!, patch));
    return (
      <Section
        title={`Помещение${r.number ? ` ${r.number}` : ""}`}
        actions={
          <>
            <Button size="sm" onClick={() => window.dispatchEvent(new CustomEvent("editor:walk-here", { detail: [r.x, r.y] }))}>
              <Footprints /> Пройтись отсюда
            </Button>
            {!ro && (
              <Button size="sm" variant="danger" onClick={del}>
                <Trash2 /> Убрать подпись
              </Button>
            )}
          </>
        }
      >
        <TextField label="Номер" value={r.number} placeholder="214" disabled={ro} onChange={(number) => set({ number })} />
        <TextField label="Название" value={r.name} placeholder="Кабинет терапевта" disabled={ro} onChange={(name) => set({ name })} />
        <div className="text-[13px] text-ink-2">
          Площадь: <span className="font-mono text-ink">{shape ? `${shape.area.toLocaleString("ru-RU")} м²` : "подпись вне помещений"}</span>
        </div>
        <PurposeField value={r.purpose_id} disabled={ro} onChange={(purpose_id) => set({ purpose_id })} />
        {admin && shape?.id && (
          <Link to={`/journal?ref=room:${shape.id}`} className="text-[13px]">
            Журнал помещения
          </Link>
        )}
      </Section>
    );
  }

  if (sel.kind === "column") {
    const c = plan.columns.find((x) => x.id === sel.id);
    if (!c) return null;
    const set = (patch: Partial<typeof c>) => edit((p) => Object.assign(p.columns.find((x) => x.id === c.id)!, patch));
    return (
      <Section title="Колонна" actions={!ro && <Button size="sm" variant="danger" onClick={del}><Trash2 /> Удалить</Button>}>
        <Segmented label="Сечение" value={c.round ? "round" : "rect"} disabled={ro} onChange={(v) => set({ round: v === "round" })} options={[{ value: "rect", title: "Прямоугольное" }, { value: "round", title: "Круглое" }]} />
        <div className={grid2}>
          <NumberField label={c.round ? "Диаметр" : "Ширина"} unit="мм" value={c.w} min={50} disabled={ro} onChange={(w) => set(c.round ? { w, d: w } : { w })} />
          {!c.round && <NumberField label="Глубина" unit="мм" value={c.d} min={50} disabled={ro} onChange={(d) => set({ d })} />}
          {!c.round && <NumberField label="Поворот" unit="°" value={c.angle} disabled={ro} onChange={(angle) => set({ angle })} />}
        </div>
      </Section>
    );
  }

  if (sel.kind === "stair") {
    const s = plan.stairs.find((x) => x.id === sel.id);
    if (!s) return null;
    const set = (patch: Partial<typeof s>) => edit((p) => Object.assign(p.stairs.find((x) => x.id === s.id)!, patch));
    const floor = floors.find((f) => f.id === floorId);
    const above = floors.find((f) => floor && f.position === floor.position + 1);
    return (
      <Section title="Лестница" actions={!ro && <Button size="sm" variant="danger" onClick={del}><Trash2 /> Удалить</Button>}>
        <div className="text-[13px] text-ink-2">{above ? `Ведёт на «${above.name}»` : "Выше этажей нет — лестница никуда не ведёт"}</div>
        <div className={grid2}>
          <NumberField label="Ширина марша" unit="мм" value={s.width} min={600} disabled={ro} onChange={(width) => set({ width })} />
          <NumberField label="Длина" unit="мм" value={s.length} min={500} disabled={ro} onChange={(length) => set({ length })} />
          <NumberField label="Ступеней" value={s.steps} min={2} max={60} disabled={ro} onChange={(steps) => set({ steps: Math.round(steps) })} />
          <NumberField label="Направление" unit="°" hint="Куда идёт подъём: 0° — вправо по плану, 90° — вверх." value={s.angle} disabled={ro} onChange={(angle) => set({ angle })} />
        </div>
      </Section>
    );
  }

  if (sel.kind === "lift") {
    const lift = lifts.find((l) => l.id === sel.id);
    if (!lift) return null;
    const toggle = (key: "floor_ids" | "stop_ids", id: string, on: boolean) => {
      const list = on ? [...lift[key], id] : lift[key].filter((x) => x !== id);
      const patch: Partial<Lift> = { [key]: list };
      if (key === "floor_ids" && !on) patch.stop_ids = lift.stop_ids.filter((x) => x !== id);
      if (key === "floor_ids" && !list.length) return;
      onLiftChange(lift, patch);
    };
    return (
      <Section title={`Лифт${lift.name ? ` ${lift.name}` : ""}`} actions={!ro && <Button size="sm" variant="danger" onClick={() => onLiftDelete(lift)}><Trash2 /> Убрать лифт</Button>}>
        <TextField label="Обозначение" value={lift.name} placeholder="Л1" disabled={ro} onChange={(name) => onLiftChange(lift, { name })} />
        <div className={grid2}>
          <NumberField label="Шахта, ширина" unit="мм" value={lift.w} min={300} max={10000} disabled={ro} onChange={(w) => onLiftChange(lift, { w })} />
          <NumberField label="Шахта, глубина" unit="мм" value={lift.d} min={300} max={10000} disabled={ro} onChange={(d) => onLiftChange(lift, { d })} />
          <NumberField label="Поворот" unit="°" value={lift.angle} disabled={ro} onChange={(angle) => onLiftChange(lift, { angle })} />
        </div>
        <Segmented label="Двери" value={String(lift.door_side) as "0" | "1" | "2" | "3"} disabled={ro} onChange={(v) => onLiftChange(lift, { door_side: Number(v) })} options={[{ value: "0", title: "↑" }, { value: "1", title: "→" }, { value: "2", title: "↓" }, { value: "3", title: "←" }]} />
        <div className="flex flex-col gap-1 text-[12px] text-ink-2">
          Этажи: шахта · остановка
          {[...floors].reverse().map((f) => (
            <div key={f.id} className="flex items-center gap-3 text-[13px] text-ink">
              <label className="flex flex-1 items-center gap-2">
                <input type="checkbox" checked={lift.floor_ids.includes(f.id)} disabled={ro} onChange={(e) => toggle("floor_ids", f.id, e.target.checked)} />
                {f.name}
              </label>
              <label className="flex items-center gap-1.5 text-ink-2">
                <input type="checkbox" checked={lift.stop_ids.includes(f.id)} disabled={ro || !lift.floor_ids.includes(f.id)} onChange={(e) => toggle("stop_ids", f.id, e.target.checked)} />
                остановка
              </label>
            </div>
          ))}
        </div>
        <p className="m-0 text-[12px] text-ink-3">Лифт сохраняется сразу и виден на всех своих этажах.</p>
      </Section>
    );
  }
  return null;
}

