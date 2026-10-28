import { useQuery } from "@tanstack/react-query";
import {
  AlignCenterHorizontal, AlignCenterVertical, AlignEndHorizontal, AlignEndVertical, AlignHorizontalSpaceAround, AlignStartHorizontal, AlignStartVertical,
  AlignVerticalSpaceAround, Copy, PackageOpen, PackagePlus, Rows3, Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { TypeFull } from "@/catalog/types";
import { Link } from "react-router";
import { get } from "@/lib/api";
import { journalUrl } from "@/lib/journal";
import { useMe } from "@/lib/auth";
import { Button } from "@/ui/button";
import { align, arrayCopies, distribute, fitAlong, footprint, sizeOf, WARNING_TEXT, type Align, type Item, type Placed, type WarningCode } from "./items";
import { CalcParams, type CalcInfo } from "./calc";
import { registrable, UnitBlock, type LinkView } from "./link";
import { copiesAt, copyItems, requestRemove, standalone, type Catalog } from "./placement";
import { type Pt, type Room } from "./plan";
import { NumberField, Segmented, TextField } from "./Properties";
import { useEditor, type EditorStore } from "./store";

function Section({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-b border-line px-4 py-4">
      <h3 className="m-0 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

const roomTitle = (r: Room | undefined) => (r ? [r.number, r.name].filter(Boolean).join(" ") || "помещение без номера" : "вне помещений");

// Справа в «Расстановке» (5.3.1, 5.3.2): свойства выбранного предмета или нескольких
export function ItemPanel({ store, cat, rooms, readOnly, warnings, link, onRegister, calcs }: { store: EditorStore; cat: Catalog; rooms: Room[]; readOnly: boolean; warnings: Map<string, WarningCode[]>; link: LinkView | undefined; onRegister: (ids: string[]) => void; calcs: CalcInfo[] }) {
  const items = useEditor(store, (s) => s.items);
  const selection = useEditor(store, (s) => s.selection);
  const chosen = useMemo(() => {
    const ids = new Set(selection.filter((s) => s.kind === "item").map((s) => s.id));
    return items.filter((i) => ids.has(i.id));
  }, [items, selection]);
  const roomsById = useMemo(() => new Map(rooms.map((r) => [r.id, r])), [rooms]);

  if (chosen.length === 1)
    return <OneItem key={chosen[0]!.id} item={chosen[0]!} store={store} cat={cat} roomsById={roomsById} readOnly={readOnly} warnings={warnings.get(chosen[0]!.id) ?? []} link={link} onRegister={onRegister} calcs={calcs} />;
  if (chosen.length > 1) return <ManyItems items={chosen} store={store} cat={cat} readOnly={readOnly} onRegister={onRegister} link={link} />;
  return <FloorSummary store={store} cat={cat} roomsById={roomsById} warnings={warnings} />;
}

function OneItem({ item, store, cat, roomsById, readOnly, warnings, link, onRegister, calcs }: { item: Item; store: EditorStore; cat: Catalog; roomsById: Map<string, Room>; readOnly: boolean; warnings: WarningCode[]; link: LinkView | undefined; onRegister: (ids: string[]) => void; calcs: CalcInfo[] }) {
  const items = useEditor(store, (s) => s.items);
  const t = cat.types.get(item.type_id);
  const layer = t?.layer_id ? cat.layers.get(t.layer_id) : undefined;
  const full = useQuery({ queryKey: ["catalog-type", item.type_id], queryFn: () => get<TypeFull>(`/api/catalog/types/${item.type_id}`), staleTime: 60_000 });
  const parent = item.parent_id ? items.find((i) => i.id === item.parent_id) : undefined;
  const contents = items.filter((i) => i.parent_id === item.id);
  const set = (patch: Partial<Item>) => store.changeItems(store.state.items.map((i) => (i.id === item.id ? { ...i, ...patch } : i)));
  // вместилища рядом: в том же помещении
  const containers = t?.container ? [] : items.filter((i) => i.id !== item.id && !i.parent_id && cat.types.get(i.type_id)?.container && i.room_id === (parent?.room_id ?? item.room_id));
  const room = roomsById.get((parent ?? item).room_id ?? "");
  const models = (full.data?.models ?? []).filter((m) => !m.archived || m.id === item.model_id);
  const nameOf = (i: Item) => cat.types.get(i.type_id)?.name ?? "предмет";
  const admin = useMe().role === "admin";

  return (
    <>
      <Section
        title={
          <span className="flex items-center gap-2">
            <span className="size-2.5 rounded-full" style={{ background: layer?.color ?? "#607D8B" }} />
            {t?.name ?? "Предмет"}
          </span>
        }
      >
        <div className="text-[13px] text-ink-2">
          {layer?.name ?? "без слоя"} · {roomTitle(room)}
          {admin && (
            <>
              {" · "}
              <Link to={journalUrl(`item:${item.id}`, `${t?.name ?? "предмет"}, ${roomTitle(room)}`)}>История</Link>
            </>
          )}
          {t?.width ? <span className="block font-mono text-[12px] text-ink-3">{`${t.width} × ${t.depth ?? "?"} × ${t.height ?? "?"} мм`}</span> : null}
        </div>
        {warnings.length > 0 && (
          <ul className="m-0 flex list-none flex-col gap-1 rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">
            {warnings.map((w) => (
              <li key={w}>Предмет {WARNING_TEXT[w]}</li>
            ))}
          </ul>
        )}
        <label className="flex flex-col gap-1 text-[12px] text-ink-2">
          Модель
          <select
            aria-label="Модель"
            disabled={readOnly}
            value={item.model_id ?? ""}
            onChange={(e) => set({ model_id: e.target.value || null })}
            className="h-8 rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink max-md:h-11"
          >
            <option value="">не выбрана — просто тип</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {[m.manufacturer, m.name].filter(Boolean).join(" ")}
              </option>
            ))}
          </select>
        </label>
        {parent ? (
          <div className="flex items-center gap-2 text-[13px]">
            <PackageOpen className="size-4 text-ink-2" /> Лежит в «{nameOf(parent)}»
            {!readOnly && standalone(t) && (
              <Button size="sm" className="ml-auto" onClick={() => set({ parent_id: null, x: parent.x, y: parent.y })}>
                Вынуть
              </Button>
            )}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2.5">
              <NumberField label="X" unit="мм" value={item.x ?? 0} disabled={readOnly} onChange={(x) => set({ x })} />
              <NumberField label="Y" unit="мм" value={item.y ?? 0} disabled={readOnly} onChange={(y) => set({ y })} />
              <NumberField label="Поворот" unit="°" value={item.angle} disabled={readOnly} onChange={(angle) => set({ angle: ((angle % 360) + 360) % 360 })} />
              <NumberField label={t?.mount === "ceiling" ? "Высота низа" : "Высота установки"} unit="мм" value={item.z} min={0} disabled={readOnly} onChange={(z) => set({ z })} />
            </div>
            {!readOnly && (
              <div className="flex gap-1.5">
                {[-90, -15, 15, 90].map((a) => (
                  <Button key={a} size="sm" className="flex-1 px-1" onClick={() => set({ angle: (((item.angle + a) % 360) + 360) % 360 })}>
                    {a > 0 ? `+${a}°` : `${a}°`}
                  </Button>
                ))}
              </div>
            )}
          </>
        )}
        {!item.parent_id && <CalcParams item={item} list={calcs} readOnly={readOnly} onChange={(params) => set({ params })} />}
        <TextField label="Подпись на плане" hint="Видна рядом с предметом и в отчётах, например «К-3» у камеры." value={item.label} placeholder="необязательно" disabled={readOnly} onChange={(label) => set({ label })} />
        {!readOnly && !parent && containers.length > 0 && (
          <label className="flex flex-col gap-1 text-[12px] text-ink-2">
            Положить в
            <select
              aria-label="Положить в"
              value=""
              onChange={(e) => e.target.value && set({ parent_id: e.target.value, x: null, y: null })}
              className="h-8 rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink max-md:h-11"
            >
              <option value="">— выберите вместилище —</option>
              {containers.map((c) => (
                <option key={c.id} value={c.id}>
                  {nameOf(c)}
                  {c.label ? ` «${c.label}»` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {!readOnly && (
          <div className="flex flex-wrap gap-2">
            {!parent && (
              <Button size="sm" onClick={() => copyItems(store, [item], [500, -500])}>
                <Copy /> Копия
              </Button>
            )}
            <Button size="sm" variant="danger" onClick={() => requestRemove(store, new Set([item.id]), cat)}>
              <Trash2 /> Убрать
            </Button>
          </div>
        )}
        <UnitBlock item={item} link={link} cat={cat} onRegister={() => onRegister([item.id])} readOnly={readOnly} />
      </Section>
      {t?.container && (
        <Section title={`Внутри (${contents.length})`}>
          {contents.length ? (
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
              {contents.map((c) => (
                <li key={c.id} className="flex items-center gap-2 text-[13px]">
                  <button type="button" className="min-w-0 flex-1 cursor-pointer truncate border-0 bg-transparent p-0 text-left text-ink" onClick={() => store.set({ selection: [{ kind: "item", id: c.id }] })}>
                    {nameOf(c)}
                  </button>
                  {!readOnly && standalone(cat.types.get(c.type_id)) && (
                    <Button size="sm" variant="ghost" onClick={() => store.changeItems(store.state.items.map((i) => (i.id === c.id ? { ...i, parent_id: null, x: item.x, y: (item.y ?? 0) - sizeOf(t).d } : i)))}>
                      Вынуть
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="m-0 text-[12px] text-ink-3">Пусто. Перетащите предмет из каталога прямо на него или выберите «Положить в» у предмета.</p>
          )}
        </Section>
      )}
      {!readOnly && !parent && <CopiesSection item={item} store={store} cat={cat} room={room} />}
    </>
  );
}

// Ряд и сетка с заданным шагом и числом (С8: светильник до конца коридора с шагом 3 м)
function CopiesSection({ item, store, cat, room }: { item: Item; store: EditorStore; cat: Catalog; room: Room | undefined }) {
  const { w, d } = sizeOf(cat.types.get(item.type_id));
  const [along, setAlong] = useState(1);
  const [stepAlong, setStepAlong] = useState(Math.round(w + 200));
  const [across, setAcross] = useState(1);
  const [stepAcross, setStepAcross] = useState(Math.round(d + 200));
  const points = useMemo(() => arrayCopies(item, along, stepAlong, across, stepAcross), [item, along, stepAlong, across, stepAcross]);
  useEffect(() => {
    store.set({ ghosts: points });
    return () => store.set({ ghosts: [] });
  }, [points, store]);
  return (
    <Section title={<span className="flex items-center gap-2"><Rows3 className="size-4" /> Ряд и сетка</span>}>
      <p className="m-0 text-[12px] text-ink-3">Вдоль — по ширине предмета (его поворот задаёт направление), поперёк — по глубине.</p>
      <div className="grid grid-cols-2 gap-2.5">
        <NumberField label="Вдоль, штук" value={along} min={1} max={500} onChange={(v) => setAlong(Math.round(v))} />
        <NumberField label="Шаг вдоль" unit="мм" value={stepAlong} onChange={setStepAlong} />
        <NumberField label="Поперёк, штук" value={across} min={1} max={200} onChange={(v) => setAcross(Math.round(v))} />
        <NumberField label="Шаг поперёк" unit="мм" value={stepAcross} onChange={setStepAcross} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={!room} title={room ? undefined : "Предмет вне помещений"} onClick={() => setAlong(fitAlong(item, room?.outline as Pt[] | undefined, stepAlong))}>
          До конца помещения
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={!points.length}
          onClick={() => {
            copiesAt(store, item, points);
            setAlong(1);
            setAcross(1);
          }}
        >
          Поставить копии ({points.length})
        </Button>
      </div>
    </Section>
  );
}

function ManyItems({ items, store, cat, readOnly, onRegister, link }: { items: Item[]; store: EditorStore; cat: Catalog; readOnly: boolean; onRegister: (ids: string[]) => void; link: LinkView | undefined }) {
  const unlinked = registrable(link, items, cat);
  const free = items.filter((i) => !i.parent_id);
  const placed: Placed[] = free.map((i) => ({ item: i, type: cat.types.get(i.type_id), poly: footprint(i, cat.types.get(i.type_id)) }));
  const move = (to: Map<string, Pt>) => store.changeItems(store.state.items.map((i) => (to.has(i.id) ? { ...i, x: to.get(i.id)![0], y: to.get(i.id)![1] } : i)));
  const aligns: [Align, string, typeof AlignStartVertical][] = [
    ["left", "По левому краю", AlignStartVertical],
    ["hcenter", "По центру (по горизонтали)", AlignCenterVertical],
    ["right", "По правому краю", AlignEndVertical],
    ["top", "По верхнему краю", AlignStartHorizontal],
    ["vcenter", "По центру (по вертикали)", AlignCenterHorizontal],
    ["bottom", "По нижнему краю", AlignEndHorizontal],
  ];
  const [axis, setAxis] = useState<"x" | "y">("x");
  return (
    <Section title={`Выбрано предметов: ${items.length}`}>
      {!readOnly && (
        <>
          <div className="flex flex-col gap-1 text-[12px] text-ink-2">
            Выровнять
            <div className="grid grid-cols-6 gap-1">
              {aligns.map(([how, title, Icon]) => (
                <Button key={how} size="icon" aria-label={title} title={title} disabled={placed.length < 2} onClick={() => move(align(placed, how))}>
                  <Icon />
                </Button>
              ))}
            </div>
          </div>
          <Segmented label="Равный шаг" value={axis} onChange={setAxis} options={[{ value: "x", title: "по горизонтали" }, { value: "y", title: "по вертикали" }]} />
          <Button size="sm" disabled={placed.length < 3} onClick={() => move(distribute(placed, axis))}>
            {axis === "x" ? <AlignHorizontalSpaceAround /> : <AlignVerticalSpaceAround />} Расставить с равным шагом
          </Button>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => copyItems(store, free, [500, -500])}>
              <Copy /> Копии
            </Button>
            <Button size="sm" variant="danger" onClick={() => requestRemove(store, new Set(items.map((i) => i.id)), cat)}>
              <Trash2 /> Убрать
            </Button>
          </div>
          {link && (
            <Button size="sm" disabled={!unlinked.length} onClick={() => onRegister(unlinked.map((i) => i.id))}>
              <PackagePlus /> Поставить на учёт ({unlinked.length})
            </Button>
          )}
        </>
      )}
    </Section>
  );
}

function FloorSummary({ store, cat, roomsById, warnings }: { store: EditorStore; cat: Catalog; roomsById: Map<string, Room>; warnings: Map<string, WarningCode[]> }) {
  const items = useEditor(store, (s) => s.items);
  const byId = new Map(items.map((i) => [i.id, i]));
  const list = [...warnings.entries()].slice(0, 50);
  return (
    <>
      <Section title="Расстановка этажа">
        <p className="m-0 text-[13px] text-ink-2">
          Предметов: {items.length}. Перетащите тип из каталога слева на план или в 3D; выбранный предмет двигается мышью, поворачивается ручкой (шаг 15°, Alt — свободно), Delete — убрать, Ctrl+D — копия.
        </p>
      </Section>
      <section className="flex flex-col gap-2 px-4 py-4" aria-label="Предупреждения расстановки">
        <h3 className="m-0 flex items-center justify-between text-sm font-semibold">
          Предупреждения
          <span className={warnings.size ? "text-[12px] font-normal text-warn" : "text-[12px] font-normal text-ok"}>{warnings.size ? `предметов: ${warnings.size}` : "нет"}</span>
        </h3>
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {list.map(([id, codes]) => {
            const it = byId.get(id);
            if (!it) return null;
            return (
              <li key={id} className="flex items-center gap-2 text-[13px]">
                <span className="size-2 shrink-0 rounded-full bg-warn" />
                <span className="min-w-0 flex-1">
                  {cat.types.get(it.type_id)?.name ?? "предмет"}
                  <span className="block text-[11px] text-ink-3">
                    {codes.map((c) => WARNING_TEXT[c]).join(", ")} · {roomTitle(roomsById.get(it.room_id ?? ""))}
                  </span>
                </span>
                <Button size="sm" variant="ghost" onClick={() => store.set({ selection: [{ kind: "item", id }], focus: [it.x ?? 0, it.y ?? 0] })}>
                  Показать
                </Button>
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}
