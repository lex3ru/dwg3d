import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTree } from "@/catalog/parts";
import type { TypeBrief } from "@/catalog/types";
import { get, query } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Tone } from "@/ui/misc";
import { Chip } from "@/ui/misc";
import { STATES, type PlaceTree, type Registry, type State, type UnitBrief } from "./types";

export const usePlaceTree = () => useQuery({ queryKey: ["inventory", "places"], queryFn: () => get<PlaceTree>("/api/inventory/places"), staleTime: 30_000 });

export function useInvalidateInventory() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["inventory"] });
}

const STATE_TONES: Record<State, Tone> = { in_use: "ok", broken: "bad", repair: "warn", storage: "muted", written_off: "muted" };

// Состояние выглядит одинаково везде: в списке, на плане и в карточке (6.1 п. 4)
export function StateChip({ state }: { state: State }) {
  return <Chip tone={STATE_TONES[state]}>{STATES[state]}</Chip>;
}

const selectCls = "h-9 w-full rounded-lg border border-line-strong bg-surface px-2 text-sm text-ink max-md:h-11";

// Место хранения: помещения по зданиям и этажам, склады с ячейками
export function PlacePicker({ value, onChange, label = "Место", allowEmpty, emptyTitle = "— не выбрано —", className, onlyStorage }: {
  value: string | null | undefined;
  onChange: (key: string | null) => void;
  label?: string;
  allowEmpty?: boolean;
  emptyTitle?: string;
  className?: string;
  onlyStorage?: boolean;
}) {
  const tree = usePlaceTree();
  return (
    <select aria-label={label} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} className={cn(selectCls, className)}>
      {(allowEmpty || !value) && <option value="">{emptyTitle}</option>}
      {tree.data?.warehouses.map((w) => (
        <optgroup key={w.id} label={`Склад «${w.name}»`}>
          <option value={w.key}>Склад «{w.name}»</option>
          {w.cells.map((c) => (
            <option key={c.id} value={c.key}>
              {w.name} › {c.name}
            </option>
          ))}
        </optgroup>
      ))}
      {!onlyStorage &&
        tree.data?.buildings.flatMap((b) =>
          b.floors.map((f) => (
            <optgroup key={f.id} label={`${b.name} · ${f.name}`}>
              {f.rooms.map((r) => (
                <option key={r.key} value={r.key}>
                  {r.title}
                </option>
              ))}
            </optgroup>
          )),
        )}
    </select>
  );
}

// Тип каталога с поиском
export function TypePicker({ value, onChange, label = "Тип", filter, autoFocus }: { value: string | null | undefined; onChange: (t: TypeBrief | null) => void; label?: string; filter?: (t: TypeBrief) => boolean; autoFocus?: boolean }) {
  const tree = useTree();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const types = useMemo(() => (tree.data?.types ?? []).filter((t) => !t.archived && (!filter || filter(t))), [tree.data, filter]);
  const current = types.find((t) => t.id === value);
  const found = useMemo(() => {
    const q = text.trim().toLowerCase();
    return types.filter((t) => !q || t.name.toLowerCase().includes(q)).slice(0, 30);
  }, [types, text]);
  return (
    <div className="relative">
      <input
        aria-label={label}
        autoFocus={autoFocus}
        value={open ? text : (current?.name ?? "")}
        placeholder="Найти тип…"
        onFocus={() => {
          setText("");
          setOpen(true);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => setText(e.target.value)}
        className={selectCls}
      />
      {open && (
        <ul role="listbox" aria-label={`${label}: варианты`} className="absolute top-full z-20 m-0 mt-1 max-h-64 w-full list-none overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-lg">
          {found.map((t) => (
            <li key={t.id}>
              <button
                type="button"
                role="option"
                aria-selected={t.id === value}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(t);
                  setOpen(false);
                }}
                className="flex w-full cursor-pointer items-center justify-between gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-[13px] hover:bg-surface-2"
              >
                {t.name}
                <span className="text-[11px] text-ink-3">{t.accounting === "quantity" ? `количеством, ${t.unit}` : "поштучно"}</span>
              </button>
            </li>
          ))}
          {!found.length && <li className="px-2 py-1.5 text-[13px] text-ink-3">Ничего не нашлось</li>}
        </ul>
      )}
    </div>
  );
}

// Инвентарная единица: поиск по названию, номеру, серийному
export function UnitPicker({ onPick, place, label = "Добавить единицу", exclude = [], states }: { onPick: (u: UnitBrief) => void; place?: string | null; label?: string; exclude?: string[]; states?: State[] }) {
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setDebounced(text.trim()), 250);
  }, [text]);
  const found = useQuery({
    queryKey: ["inventory", "pick", debounced, place],
    queryFn: () => get<Registry>(`/api/inventory/units${query({ q: debounced, place: place ?? undefined, limit: 20 })}`),
    enabled: debounced.length >= 2 || !!place,
  });
  const items = (found.data?.items ?? []).filter((u) => !exclude.includes(u.id) && (!states || states.includes(u.state)));
  return (
    <div className="relative">
      <label className="flex h-9 items-center gap-2 rounded-lg border border-line-strong bg-surface px-2.5 max-md:h-11">
        <Search className="size-4 text-ink-3" />
        <input aria-label={label} placeholder={`${label}: название, инв. или серийный номер`} value={text} onChange={(e) => setText(e.target.value)} className="min-w-0 flex-1 border-0 bg-transparent text-sm outline-none" />
      </label>
      {(debounced.length >= 2 || (place && text)) && (
        <ul role="listbox" aria-label="Найденные единицы" className="absolute top-full z-20 m-0 mt-1 max-h-72 w-full list-none overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-lg">
          {items.map((u) => (
            <li key={u.id}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                onClick={() => {
                  onPick(u);
                  setText("");
                }}
                className="flex w-full cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-[13px] hover:bg-surface-2"
              >
                <span className="font-mono text-[12px] text-ink-2">{u.number}</span>
                <span className="min-w-0 flex-1 truncate">{u.title}</span>
                <span className="truncate text-[11px] text-ink-3">{u.place?.short}</span>
              </button>
            </li>
          ))}
          {!items.length && <li className="px-2 py-1.5 text-[13px] text-ink-3">{found.isLoading ? "Ищу…" : "Ничего не нашлось"}</li>}
        </ul>
      )}
    </div>
  );
}

// Печать QR-меток: листом А4 или на принтер этикеток (5.4.7)
export async function printLabels(body: { unit_ids?: string[]; codes?: string[]; room_ids?: string[] }, mode: "sheet" | "printer" = "sheet") {
  const r = await fetch("/api/inventory/labels.pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-With": "app" },
    credentials: "same-origin",
    body: JSON.stringify({ ...body, mode, origin: window.location.origin }),
  });
  if (!r.ok) {
    const e = await r.json().catch(() => null);
    throw new Error(e?.error?.message ?? "Метки не напечатались.");
  }
  const url = URL.createObjectURL(await r.blob());
  window.open(url, "_blank");
}
