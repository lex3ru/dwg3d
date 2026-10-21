// Связь планировки и учёта в редакторе (5.5): «Неразмещённые», сверка количественного
// учёта, единица у предмета, постановка на учёт с плана, удаление связанных предметов.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, PackagePlus, Printer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import type { TypeBrief } from "@/catalog/types";
import { ApiError, get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { PlacePicker, printLabels, StateChip } from "@/inventory/parts";
import { today, type State } from "@/inventory/types";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Choice, Field, FormError, Input } from "@/ui/form";
import type { Item } from "./items";
import { markDraggedType, removeItems, type Catalog } from "./placement";
import { useEditor, type EditorStore } from "./store";

export interface LinkUnit {
  id: string;
  number: string;
  title: string;
  type_id: string;
  model_id: string | null;
  parent_id: string | null;
  state: State;
  place: string;
  room_id: string | null;
  room_title: string;
  item_id: string | null;
  placeable: boolean;
}

export interface Mismatch {
  room_id: string;
  room_title: string;
  type_id: string;
  type_name: string;
  unit: string;
  on_plan: number;
  in_stock: number;
}

export interface LinkView {
  units: LinkUnit[];
  unplaced: string[];
  mismatch: Mismatch[];
}

// Количественный учёт (5.5): на плане больше, чем по учёту, — сколько не хватает; null —
// предмет учитывается поштучно
export function stockGap(link: LinkView | undefined, item: Item, cat: Catalog): number | null {
  if (cat.types.get(item.type_id)?.accounting !== "quantity") return null;
  const m = link?.mismatch.find((x) => x.room_id === item.room_id && x.type_id === item.type_id);
  return m ? m.on_plan - m.in_stock : 0;
}

// Что из выбранного можно поставить на учёт: поштучные без связи и количественные, которых
// по учёту меньше, чем на плане
export function registrable(link: LinkView | undefined, items: Item[], cat: Catalog): Item[] {
  return items.filter((i) => {
    const gap = stockGap(link, i, cat);
    return gap === null ? !i.unit_id : gap > 0;
  });
}

export const useLink = (floorId: string) => useQuery({ queryKey: ["link", floorId], queryFn: () => get<LinkView>(`/api/link/floors/${floorId}`) });

// Состояния и модели единиц — в хранилище редактора: значки на предметах, модель у
// поставленной из «Неразмещённых»
export function useLinkInStore(store: EditorStore, link: LinkView | undefined) {
  useEffect(() => {
    if (!link) return;
    store.set({
      unitStates: Object.fromEntries(link.units.map((u) => [u.id, u.state])),
      unitModels: Object.fromEntries(link.units.map((u) => [u.id, u.model_id])),
    });
  }, [link, store]);
}

// ---------------------------------------------------------------- слева: неразмещённые и сверка

export function UnplacedSection({ store, cat, link, readOnly }: { store: EditorStore; cat: Catalog; link: LinkView | undefined; readOnly: boolean }) {
  const placingUnit = useEditor(store, (s) => s.placingUnit);
  const onlyBroken = useEditor(store, (s) => s.onlyBroken);
  const units = useMemo(() => {
    const ids = new Set(link?.unplaced ?? []);
    return (link?.units ?? []).filter((u) => ids.has(u.id));
  }, [link]);
  const broken = (link?.units ?? []).filter((u) => u.item_id && (u.state === "broken" || u.state === "repair")).length;
  // по помещениям: сначала то, где ждут больше
  const groups = useMemo(() => {
    const out = new Map<string, LinkUnit[]>();
    for (const u of units) {
      const list = out.get(u.room_title);
      if (list) list.push(u);
      else out.set(u.room_title, [u]);
    }
    return [...out.entries()].sort((x, y) => y[1].length - x[1].length || x[0].localeCompare(y[0], "ru", { numeric: true }));
  }, [units]);
  if (!link) return null;
  const head = "m-0 flex items-center justify-between px-1.5 pb-1 text-[12px] font-semibold tracking-wide text-ink-2 uppercase";
  return (
    <>
      <label className="flex cursor-pointer items-center gap-2 border-b border-line px-3.5 py-2 text-[12px] text-ink-2">
        <input type="checkbox" checked={onlyBroken} onChange={(e) => store.set({ onlyBroken: e.target.checked })} />
        Только неисправное на плане{broken ? ` (${broken})` : ""}
      </label>
      {link.mismatch.length > 0 && (
        <section aria-label="Сверка с учётом" className="border-b border-line p-2">
          <h3 className={head}>
            Количество: план и учёт <span className="font-mono font-normal text-warn">{link.mismatch.length}</span>
          </h3>
          <p className="m-0 px-1.5 pb-1 text-[11px] leading-snug text-ink-3">
            Стулья, светильники и другое, что учитывается количеством, с планом поштучно не связываются — сверяется, сколько стоит в помещении на плане и сколько там числится. Не хватает на плане — поставьте недостающее (или, если вещей правда меньше, спишите лишнее в «Складе»); на плане больше — поставьте разницу на учёт.
          </p>
          <ul className="m-0 list-none p-0 text-[12px]">
            {link.mismatch.map((m) => {
              const n = (v: number) => v.toLocaleString("ru-RU");
              const fewer = m.on_plan < m.in_stock;
              const diff = Math.abs(m.in_stock - m.on_plan);
              return (
                <li key={`${m.room_id}${m.type_id}`} className="flex flex-col gap-1 rounded-md px-1.5 py-1.5 hover:bg-surface-2">
                  <span>
                    <span className="text-ink">{m.type_name}</span> <span className="text-ink-3">· {m.room_title}</span>
                  </span>
                  <span className="text-warn">
                    {fewer
                      ? `Числится ${n(m.in_stock)} ${m.unit}, на плане ${n(m.on_plan)} — не хватает на плане ${n(diff)}`
                      : `На плане ${n(m.on_plan)}, числится ${n(m.in_stock)} ${m.unit} — ${n(diff)} не на учёте`}
                  </span>
                  {!readOnly && (
                    <span className="flex gap-1.5">
                      {fewer ? (
                        <Button size="sm" onClick={() => store.set({ placing: m.type_id, placingUnit: null, selection: [] })}>
                          Поставить
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          onClick={() =>
                            store.set({
                              placing: null,
                              selection: store.state.items.filter((i) => i.type_id === m.type_id && i.room_id === m.room_id && !i.parent_id).map((i) => ({ kind: "item" as const, id: i.id })),
                            })
                          }
                        >
                          Выбрать на плане
                        </Button>
                      )}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
      <section aria-label="Неразмещённые" className="p-2">
        <h3 className={head}>
          Неразмещённые
          <span className="font-mono font-normal text-ink-3">{units.length}</span>
        </h3>
        {units.length === 0 ? (
          <p className="m-0 px-1.5 text-[12px] text-ink-3">Всё, что числится на этаже, стоит на плане.</p>
        ) : (
          <>
            <p className="m-0 px-1.5 pb-1.5 text-[11px] text-ink-3">Перетащите на план или в 3D — или выберите и щёлкните там.</p>
            <ul aria-label="Неразмещённые единицы" className="m-0 list-none p-0">
              {groups.map(([room, list]) => (
                <li key={room} className="pb-1.5">
                  <div className="sticky top-0 z-10 bg-surface px-1.5 py-1 text-[11px] font-medium text-ink-2">
                    {room || "без помещения"} <span className="font-mono font-normal text-ink-3">{list.length}</span>
                  </div>
                  <ul className="m-0 list-none p-0">
                    {list.map((u) => {
                      const t = cat.types.get(u.type_id);
                      const active = placingUnit === u.id;
                      return (
                        <li key={u.id}>
                          <button
                            type="button"
                            draggable={!readOnly}
                            disabled={readOnly}
                            onDragStart={(e) => {
                              markDraggedType(e.dataTransfer, u.type_id);
                              e.dataTransfer.setData("application/x-unit", u.id);
                              e.dataTransfer.effectAllowed = "copy";
                            }}
                            onClick={() => store.set(active ? { placing: null, placingUnit: null } : { placing: u.type_id, placingUnit: u.id, selection: [] })}
                            aria-pressed={active}
                            title={`${u.title}${u.number ? ` № ${u.number}` : ""} — ${u.room_title}`}
                            className={cn(
                              "flex w-full cursor-grab items-baseline gap-1 rounded-md border-0 px-1.5 py-1 text-left text-[13px] max-md:py-2.5",
                              active ? "bg-accent-soft text-accent-ink" : "bg-transparent text-ink hover:bg-surface-2",
                            )}
                          >
                            <span className="min-w-0 flex-1 truncate">{t?.name ?? u.title}</span>
                            {u.number && <span className="shrink-0 font-mono text-[11px] text-ink-3">{u.number}</span>}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </>
  );
}

// ---------------------------------------------------------------- справа: единица у предмета

export function UnitBlock({ item, link, cat, onRegister, readOnly }: { item: Item; link: LinkView | undefined; cat: Catalog; onRegister: () => void; readOnly: boolean }) {
  // в проекте учёта нет: что выдать со склада и что купить — при применении проекта
  if (!link) return null;
  const unit = item.unit_id ? link?.units.find((u) => u.id === item.unit_id) : undefined;
  const gap = stockGap(link, item, cat);
  if (gap !== null) {
    const m = link?.mismatch.find((x) => x.room_id === item.room_id && x.type_id === item.type_id);
    return (
      <div className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-[12px] text-ink-2" aria-label="Учёт">
        Учитывается остатком помещения, поштучно не связывается.
        {m && (
          <span className="text-warn">
            На плане {m.on_plan}, по учёту {m.in_stock.toLocaleString("ru-RU")} {m.unit}
          </span>
        )}
        {!readOnly && gap > 0 && (
          <Button size="sm" onClick={onRegister} className="self-start">
            <PackagePlus /> Оприходовать недостающее
          </Button>
        )}
      </div>
    );
  }
  if (item.unit_id) {
    return (
      <div className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface-2 px-3 py-2.5" aria-label="Учёт">
        <div className="flex items-center justify-between gap-2 text-[13px]">
          <span className="font-medium">{unit?.number ? `Инв. № ${unit.number}` : "Числится в учёте"}</span>
          {unit && <StateChip state={unit.state} />}
        </div>
        {unit && <span className="text-[12px] text-ink-2">{unit.title}</span>}
        <Link to={`?card=unit:${item.unit_id}`} className="inline-flex items-center gap-1 text-[13px]">
          <ExternalLink className="size-3.5" /> Карточка единицы
        </Link>
      </div>
    );
  }
  if (readOnly) return null;
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-dashed border-line-strong px-3 py-2.5 text-[12px] text-ink-2">
      Не связан с учётом — вещь не учитывается или ещё не куплена.
      <Button size="sm" onClick={onRegister} className="self-start">
        <PackagePlus /> Поставить на учёт
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------- постановка на учёт (С10)

interface Group {
  key: string;
  type: TypeBrief | undefined;
  count: number;
  price: number;
}

export function RegisterDialog({ open, onClose, floorId, items, cat, onDone }: { open: boolean; onClose: () => void; floorId: string; items: Item[]; cat: Catalog; onDone: (r: Registered) => void }) {
  const [kind, setKind] = useState<"opening" | "receipt">("opening");
  const [date, setDate] = useState(today());
  const [supplier, setSupplier] = useState("");
  const [responsible, setResponsible] = useState("");
  const [department, setDepartment] = useState("");
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // количественные — остатком, сервер оприходует только недостающее до числа на плане
  const free = items.filter((i) => !i.unit_id);
  const groups = useMemo(() => {
    const out = new Map<string, Group>();
    for (const i of free) {
      const key = i.type_id;
      const t = cat.types.get(i.type_id);
      const g = out.get(key) ?? { key, type: t, count: 0, price: Number(t?.price ?? 0) };
      g.count += 1;
      out.set(key, g);
    }
    return [...out.values()];
  }, [free, cat]);
  useEffect(() => {
    if (open) {
      setPrices({});
      setError(null);
    }
  }, [open]);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await post<Registered>("/api/link/register", {
        floor_id: floorId,
        item_ids: free.map((i) => i.id),
        kind,
        date,
        supplier: kind === "receipt" ? supplier : "",
        responsible,
        department,
        prices: Object.fromEntries(groups.map((g) => [g.key, Number(prices[g.key] ?? g.price) || 0])),
      });
      onDone(r);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={`Поставить на учёт: ${free.length}`}
      description="Система выдаст инвентарные номера и свяжет предметы на плане с новыми единицами; количественный учёт ляжет остатком в помещение."
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy || !free.length} onClick={() => void submit()}>
            <PackagePlus /> Провести
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2 max-sm:grid-cols-1">
          <Choice name="register-kind" value="opening" checked={kind === "opening"} onChange={() => setKind("opening")} title="Ввод остатков" description="Вещь уже есть — начальная постановка на учёт" />
          <Choice name="register-kind" value="receipt" checked={kind === "receipt"} onChange={() => setKind("receipt")} title="Приход" description="Вещь только что поступила" />
        </div>
        <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
          <Field label="Дата">{(p) => <Input {...p} type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} />}</Field>
          {kind === "receipt" && <Field label="Поставщик">{(p) => <Input {...p} value={supplier} onChange={(e) => setSupplier(e.target.value)} />}</Field>}
          <Field label="Ответственный">{(p) => <Input {...p} value={responsible} onChange={(e) => setResponsible(e.target.value)} />}</Field>
          <Field label="Подразделение">{(p) => <Input {...p} value={department} onChange={(e) => setDepartment(e.target.value)} />}</Field>
        </div>
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="text-left text-xs text-ink-2">
              <th className="border-b border-line py-1.5 font-medium">Тип</th>
              <th className="border-b border-line py-1.5 font-medium">Сколько</th>
              <th className="border-b border-line py-1.5 font-medium">Цена, ₽</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.key}>
                <td className="border-b border-line py-1.5">
                  {g.type?.name ?? "—"}
                  {g.type?.accounting === "quantity" && <span className="block text-[11px] text-ink-3">остатком, {g.type.unit}</span>}
                </td>
                <td className="border-b border-line py-1.5 font-mono">{g.count}</td>
                <td className="border-b border-line py-1.5">
                  <Input aria-label={`Цена: ${g.type?.name ?? ""}`} type="number" min={0} step="0.01" value={prices[g.key] ?? String(g.price)} onChange={(e) => setPrices({ ...prices, [g.key]: e.target.value })} className="h-8 w-32" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length > free.length && <p className="m-0 text-[12px] text-ink-3">Уже на учёте и не войдут: {items.length - free.length}.</p>}
        <FormError message={error} />
      </div>
    </Dialog>
  );
}

// Поставлено на учёт — предложить метки
export interface Registered {
  document: { title: string };
  unit_ids: string[];
  items: Item[];
  stock: { type_name: string; qty: number; unit: string; room_title: string }[];
}

export function LabelsOffer({ result, onClose }: { result: Registered | null; onClose: () => void }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog
      open={!!result}
      onOpenChange={(o) => !o && onClose()}
      title="Поставлено на учёт"
      description={result ? `Проведён «${result.document.title}»${result.unit_ids.length ? `, новых единиц: ${result.unit_ids.length}` : ""}.` : undefined}
      footer={
        <>
          <Button onClick={onClose}>Готово</Button>
          {!!result?.unit_ids.length && (
            <Button
              variant="primary"
              onClick={() => {
                setError(null);
                printLabels({ unit_ids: result.unit_ids }).catch((e: Error) => setError(e.message));
              }}
            >
              <Printer /> Напечатать метки ({result.unit_ids.length})
            </Button>
          )}
        </>
      }
    >
      {!!result?.stock.length && (
        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[13px]">
          {result.stock.map((s, i) => (
            <li key={i}>
              {s.type_name} — {s.qty} {s.unit} остатком <span className="text-ink-3">· {s.room_title}</span>
            </li>
          ))}
        </ul>
      )}
      <FormError message={error} />
    </Dialog>
  );
}

// ---------------------------------------------------------------- связанный предмет убирают

export function RemoveDialog({ store, cat, onDone }: { store: EditorStore; cat: Catalog; onDone: (text: string, deleted: string[]) => void }) {
  const ask = useEditor(store, (s) => s.askRemove);
  const [mode, setMode] = useState<"plan" | "return" | "writeoff">("plan");
  const [to, setTo] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const client = useQueryClient();
  useEffect(() => {
    if (ask) {
      setMode("plan");
      setError(null);
    }
  }, [ask]);
  const ids = new Set(ask ?? []);
  const linked = store.state.items.filter((i) => ids.has(i.id) && i.unit_id);
  const close = () => store.set({ askRemove: null });
  const apply = async () => {
    if (mode === "plan") {
      removeItems(store, ids, cat);
      close();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ document: { title: string }; deleted: string[] }>("/api/link/remove", { item_ids: linked.map((i) => i.id), mode, to_place: to, reason });
      // несвязанные из выбранных убираются как обычно
      const rest = new Set([...ids].filter((id) => !linked.some((i) => i.id === id)));
      const gone = new Set(r.deleted);
      store.set({ items: store.state.items.filter((i) => !gone.has(i.id)), selection: [], askRemove: null, itemPast: [], itemFuture: [] });
      if (rest.size) removeItems(store, rest, cat);
      client.invalidateQueries({ queryKey: ["inventory"] });
      onDone(`Проведён «${r.document.title}».`, r.deleted);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={!!ask}
      onOpenChange={(o) => !o && close()}
      title="Убрать учтённое с плана"
      description={`Среди выбранного числится в учёте: ${linked.length}. Что сделать с этими единицами?`}
      footer={
        <>
          <Button onClick={close}>Отмена</Button>
          <Button variant={mode === "writeoff" ? "danger" : "primary"} disabled={busy || (mode === "return" && !to)} onClick={() => void apply()}>
            {mode === "plan" ? "Убрать с плана" : mode === "return" ? "Вернуть" : "Списать"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-2">
        <Choice name="remove-mode" value="plan" checked={mode === "plan"} onChange={() => setMode("plan")} title="Только убрать с плана" description="Единицы остаются числиться в помещении и попадают в «Неразмещённые»" />
        <Choice name="remove-mode" value="return" checked={mode === "return"} onChange={() => setMode("return")} title="Вернуть на склад" description="Документ «Перемещение» на выбранный склад" />
        {mode === "return" && <PlacePicker value={to} onChange={setTo} label="Куда вернуть" onlyStorage emptyTitle="— выберите склад —" />}
        <Choice name="remove-mode" value="writeoff" checked={mode === "writeoff"} onChange={() => setMode("writeoff")} title="Списать" description="Документ «Списание» с причиной" />
        {mode === "writeoff" && <Input aria-label="Причина списания" placeholder="Причина списания" value={reason} onChange={(e) => setReason(e.target.value)} />}
        <FormError message={error} />
      </div>
    </Dialog>
  );
}
