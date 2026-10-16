// Расчёты на плане (5.3.7): список модулей с сервера, включение переключателем, пересчёт по
// расстановке как на экране (и пока предмет тащат), рисование того, что вернул модуль, —
// многоугольники, клетки с раскраской, подписи, линии в 3D. Редактор не знает, какой это
// расчёт: новый модуль появляется в списке сам.

import { useQuery } from "@tanstack/react-query";
import { Calculator, Table2 } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import type { Item } from "./items";
import type { Pt } from "./plan";
import { useEditor, type EditorStore } from "./store";

export interface CalcParam {
  key: string;
  title: string;
  unit: string;
  low: number | null;
  high: number | null;
  hint: string;
}

export interface CalcInfo {
  key: string;
  title: string;
  about: string;
  needs: string[];
  type_ids: string[];
  params: CalcParam[];
  options: { key: string; title: string; choices: [string, string][]; default: string }[];
}

type Rings = number[][][];
export type Shape2D =
  | { kind: "polygon"; rings: Rings[]; fill: string; opacity?: number; hatch?: boolean; item_id?: string }
  | { kind: "cells"; size: number; cells: number[][]; scale?: [number, string][]; color?: string; hatch?: boolean; opacity?: number }
  | { kind: "label"; x: number; y: number; text: string; short?: string; width?: number; tone?: "ok" | "bad" | "muted" };

export interface Shape3D {
  kind: "lines";
  color: string;
  segments: number[][][];
}

export interface Pin {
  text: string;
  x?: number;
  y?: number;
  room_id?: string;
  item_id?: string;
}

export interface CalcResult {
  draw: Shape2D[];
  draw3d: Shape3D[];
  summary: string[];
  legend: { color: string; title: string; hatch?: boolean }[];
  table: { title: string; columns: string[]; rows: string[][]; item_ids?: string[]; room_ids?: string[] } | null;
  issues: { title: string; rows: Pin[] } | null;
  missing: Pin[];
  took_ms: number;
}

export const useCalcList = () => useQuery({ queryKey: ["calc-list"], queryFn: () => get<{ items: CalcInfo[] }>("/api/calc"), staleTime: 60_000 });

const ON = "calcs-on";

function savedOn(): string[] {
  try {
    return JSON.parse(localStorage.getItem(ON) ?? "[]") as string[];
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------- пересчёт

// Включённые расчёты пересчитываются, когда меняется расстановка, выбранное помещение или
// выбор в расчёте; запросы — не чаще раза в 120 мс и во время перетаскивания, ответ
// устаревшего запроса не рисуется
export function useCalcs(store: EditorStore, floorId: string) {
  const list = useCalcList();
  const items = useEditor(store, (s) => s.items);
  const on = useEditor(store, (s) => s.calcsOn);
  const options = useEditor(store, (s) => s.calcOptions);
  const room = useEditor(store, (s) => s.selection.find((x) => x.kind === "room")?.id ?? null);
  const seq = useRef<Record<string, number>>({});
  const sentAt = useRef(0);
  useEffect(() => {
    store.set({ calcsOn: savedOn() });
  }, [store]);
  const roomId = useMemo(() => {
    if (!room) return "";
    return store.state.check?.rooms.find((r) => r.label === room)?.id ?? (room.startsWith("new") ? "" : room);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [room]);
  useEffect(() => {
    const calcs = (list.data?.items ?? []).filter((c) => on.includes(c.key));
    const stale = Object.keys(store.state.calcResults).filter((k) => !on.includes(k));
    if (stale.length) store.set({ calcResults: Object.fromEntries(Object.entries(store.state.calcResults).filter(([k]) => on.includes(k))) });
    if (!calcs.length) return;
    // не чаще раза в 120 мс, но и пока предмет тащат без остановки — тоже
    const t = setTimeout(() => {
      sentAt.current = Date.now();
      for (const c of calcs) {
        const types = new Set(c.type_ids);
        const sent = items
          .filter((i) => types.has(i.type_id) && !i.parent_id)
          .map((i) => ({ id: i.id, type_id: i.type_id, model_id: i.model_id, x: i.x, y: i.y, z: i.z, angle: i.angle, params: i.params ?? {}, label: i.label }));
        const n = (seq.current[c.key] ?? 0) + 1;
        seq.current[c.key] = n;
        post<CalcResult>(`/api/calc/${c.key}/floors/${floorId}`, { items: sent, options: { ...options[c.key], room: roomId } })
          .then((r) => {
            if (seq.current[c.key] !== n || !store.state.calcsOn.includes(c.key)) return;
            store.set({ calcResults: { ...store.state.calcResults, [c.key]: r } });
          })
          .catch(() => {});
      }
    }, Math.max(0, 120 - (Date.now() - sentAt.current)));
    return () => clearTimeout(t);
  }, [items, on, options, roomId, list.data, floorId, store]);
  return list;
}

export function toggleCalc(store: EditorStore, key: string) {
  const on = store.state.calcsOn.includes(key) ? store.state.calcsOn.filter((k) => k !== key) : [...store.state.calcsOn, key];
  store.set({ calcsOn: on });
  try {
    localStorage.setItem(ON, JSON.stringify(on));
  } catch {
    /* не запомнится */
  }
}

// ---------------------------------------------------------------- 2D

const ringPath = (rings: Rings) => rings.map((ring) => `M${ring.map((p) => `${p[0]},${p[1]}`).join("L")}Z`).join("");

function colorAt(scale: [number, string][], v: number): string {
  let c = scale[0]![1];
  for (const [at, color] of scale) if (v >= at) c = color;
  return c;
}

// Клетки одного цвета — одним контуром: десятки тысяч точек освещённости не тормозят план
function cellPaths(shape: Extract<Shape2D, { kind: "cells" }>): [string, string][] {
  const half = shape.size / 2;
  const groups = new Map<string, string[]>();
  for (const c of shape.cells) {
    const color = shape.scale ? colorAt(shape.scale, c[2] ?? 0) : (shape.color ?? "#999");
    const d = `M${c[0]! - half},${c[1]! - half}h${shape.size}v${shape.size}h${-shape.size}Z`;
    const list = groups.get(color);
    if (list) list.push(d);
    else groups.set(color, [d]);
  }
  return [...groups.entries()].map(([color, parts]) => [color, parts.join("")]);
}

export const CalcWorld = memo(function CalcWorld({ results, px }: { results: Record<string, CalcResult>; px: number }) {
  const shapes = Object.values(results).flatMap((r) => r.draw);
  const cells = useMemo(() => shapes.map((s) => (s.kind === "cells" ? cellPaths(s) : null)), [shapes]);
  return (
    <g style={{ pointerEvents: "none" }} data-calc>
      <defs>
        <pattern id="calc-hatch" patternUnits="userSpaceOnUse" width={10 * px} height={10 * px} patternTransform="rotate(45)">
          <rect width={10 * px} height={10 * px} fill="#D32F2F" fillOpacity={0.12} />
          <line x1={0} y1={0} x2={0} y2={10 * px} stroke="#D32F2F" strokeWidth={3 * px} />
        </pattern>
      </defs>
      {shapes.map((s, i) => {
        if (s.kind === "polygon")
          return s.rings.map((rings, j) => (
            <path key={`${i}.${j}`} d={ringPath(rings)} fillRule="evenodd" fill={s.hatch ? "url(#calc-hatch)" : s.fill} fillOpacity={s.hatch ? 1 : (s.opacity ?? 0.3)} stroke={s.hatch ? "#D32F2F" : s.fill} strokeWidth={px} strokeOpacity={0.7} />
          ));
        if (s.kind === "cells")
          return cells[i]!.map(([color, d]) => <path key={`${i}${color}`} d={d} fill={s.hatch ? "url(#calc-hatch)" : color} fillOpacity={s.hatch ? 1 : (s.opacity ?? 0.5)} />);
        return null;
      })}
    </g>
  );
});

const TONE = { ok: "var(--ok)", bad: "var(--bad)", muted: "var(--ink-2)" } as const;

// Подпись — полная, короткая или никакой: смотря сколько места у помещения на экране
export function calcLabels(results: Record<string, CalcResult>, toScreen: (p: Pt) => [number, number], scale: number): ReactNode[] {
  return Object.entries(results).flatMap(([key, r]) =>
    r.draw
      .filter((s): s is Extract<Shape2D, { kind: "label" }> => s.kind === "label")
      .map((s, i) => {
        const room = s.width === undefined ? Infinity : s.width * scale;
        const full = s.text.length * 6.3 + 12;
        const text = full <= room ? s.text : s.short && s.short.length * 6.3 + 12 <= room ? s.short : null;
        if (!text) return null;
        const at = toScreen([s.x, s.y]);
        const w = text.length * 6.3 + 12;
        return (
          <g key={`calc${key}${i}`} transform={`translate(${at[0]} ${at[1] + 40})`} style={{ pointerEvents: "none" }}>
            <rect x={-w / 2} y={-10} width={w} height={18} rx={4} fill="var(--surface)" fillOpacity={0.9} stroke={TONE[s.tone ?? "muted"]} />
            <text textAnchor="middle" y={3} fontSize={11} fill={TONE[s.tone ?? "muted"]} className="font-mono">
              {text}
            </text>
          </g>
        );
      }),
  );
}

// ---------------------------------------------------------------- 3D

const M = 0.001;

export function CalcLines3D({ store }: { store: EditorStore }) {
  const results = useEditor(store, (s) => s.calcResults);
  const groups = useMemo(() => {
    const out: { color: string; geometry: THREE.BufferGeometry }[] = [];
    for (const r of Object.values(results))
      for (const s of r.draw3d) {
        const pts = s.segments.flatMap(([a, b]) => [a![0]! * M, a![2]! * M, -a![1]! * M, b![0]! * M, b![2]! * M, -b![1]! * M]);
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
        out.push({ color: s.color, geometry: g });
      }
    return out;
  }, [results]);
  return (
    <>
      {groups.map((g, i) => (
        <lineSegments key={i} geometry={g.geometry}>
          <lineBasicMaterial color={g.color} />
        </lineSegments>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- слева: переключатели и итоги

export function CalcSection({ store, list }: { store: EditorStore; list: CalcInfo[] }) {
  const on = useEditor(store, (s) => s.calcsOn);
  const results = useEditor(store, (s) => s.calcResults);
  const options = useEditor(store, (s) => s.calcOptions);
  const [table, setTable] = useState<string | null>(null);
  if (!list.length) return null;
  const go = (p: Pin) => {
    if (p.item_id) store.set({ selection: [{ kind: "item", id: p.item_id }] });
    else if (p.room_id) {
      const label = store.state.check?.rooms.find((r) => r.id === p.room_id)?.label ?? store.state.plan.rooms.find((r) => r.id === p.room_id)?.id;
      if (label) store.set({ selection: [{ kind: "room", id: label }] });
    }
    if (p.x !== undefined && p.y !== undefined) store.set({ focus: [p.x, p.y] });
  };
  const shown = list.find((c) => c.key === table);
  return (
    <section aria-label="Расчёты" className="max-h-[45%] shrink-0 overflow-y-auto border-b border-line p-2">
      <h3 className="m-0 flex items-center gap-1.5 px-1.5 pb-1 text-[12px] font-semibold tracking-wide text-ink-2 uppercase">
        <Calculator className="size-3.5" /> Расчёты
      </h3>
      {list.map((c) => {
        const active = on.includes(c.key);
        const r = results[c.key];
        return (
          <div key={c.key} className="flex flex-col gap-1.5 rounded-md px-1.5 py-1">
            <label className="flex cursor-pointer items-center gap-2 text-[13px]" title={c.about}>
              <input type="checkbox" checked={active} onChange={() => toggleCalc(store, c.key)} aria-label={c.title} />
              <span className="flex-1">{c.title}</span>
              {active && r && <span className="font-mono text-[10px] text-ink-3">{r.took_ms} мс</span>}
            </label>
            {active &&
              c.options.map((o) => (
                <select
                  key={o.key}
                  aria-label={o.title}
                  value={options[c.key]?.[o.key] ?? o.default}
                  onChange={(e) => store.set({ calcOptions: { ...options, [c.key]: { ...options[c.key], [o.key]: e.target.value } } })}
                  className="h-8 rounded-md border border-line-strong bg-surface px-1.5 text-[12px] max-md:h-10"
                >
                  {o.choices.map(([v, t]) => (
                    <option key={v} value={v}>
                      {o.title}: {t}
                    </option>
                  ))}
                </select>
              ))}
            {active && r && (
              <div className="flex flex-col gap-1.5 text-[12px]" aria-label={`Итоги: ${c.title}`}>
                {r.summary.map((s, i) => (
                  <p key={i} className="m-0 text-ink-2">
                    {s}
                  </p>
                ))}
                <ul className="m-0 flex list-none flex-wrap gap-x-2 gap-y-0.5 p-0">
                  {r.legend.map((l) => (
                    <li key={l.title} className="flex items-center gap-1 text-[11px] text-ink-2">
                      <span className="size-2.5 rounded-sm border" style={{ background: l.hatch ? `repeating-linear-gradient(45deg, ${l.color} 0 2px, transparent 2px 4px)` : l.color, borderColor: l.color }} />
                      {l.title}
                    </li>
                  ))}
                </ul>
                {r.issues && r.issues.rows.length > 0 && (
                  <div>
                    <p className="m-0 font-medium text-bad">{r.issues.title}</p>
                    <ul aria-label={r.issues.title} className="m-0 list-none p-0">
                      {r.issues.rows.map((p, i) => (
                        <li key={i}>
                          <button type="button" onClick={() => go(p)} className="w-full cursor-pointer rounded border-0 bg-transparent px-1 py-0.5 text-left text-[12px] text-ink hover:bg-surface-2">
                            {p.text}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {r.missing.length > 0 && (
                  <div>
                    <p className="m-0 font-medium text-warn">Не хватает данных</p>
                    <ul aria-label="Не хватает данных" className="m-0 list-none p-0">
                      {r.missing.slice(0, 20).map((p, i) => (
                        <li key={i}>
                          <button type="button" onClick={() => go(p)} className="w-full cursor-pointer rounded border-0 bg-transparent px-1 py-0.5 text-left text-[11px] text-ink-2 hover:bg-surface-2">
                            {p.text}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {r.table && (
                  <Button size="sm" variant="ghost" className="self-start" onClick={() => setTable(c.key)}>
                    <Table2 /> {r.table.title} ({r.table.rows.length})
                  </Button>
                )}
              </div>
            )}
          </div>
        );
      })}
      <Dialog open={!!shown && !!results[table ?? ""]?.table} onOpenChange={(o) => !o && setTable(null)} title={shown ? `${shown.title}: ${results[shown.key]?.table?.title ?? ""}` : ""} wide>
        {shown && results[shown.key]?.table && <CalcTable table={results[shown.key]!.table!} onPick={(p) => { setTable(null); go(p); }} />}
      </Dialog>
    </section>
  );
}

function CalcTable({ table, onPick }: { table: NonNullable<CalcResult["table"]>; onPick: (p: Pin) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="text-left text-xs text-ink-2">
            {table.columns.map((c) => (
              <th key={c} className="border-b border-line px-2 py-1.5 font-medium whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} className={cn((table.item_ids || table.room_ids) && "cursor-pointer hover:bg-surface-2")} onClick={() => onPick({ text: "", item_id: table.item_ids?.[i], room_id: table.room_ids?.[i] })}>
              {row.map((v, j) => (
                <td key={j} className={cn("border-b border-line px-2 py-1.5", j > 1 && "font-mono")}>
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- справа: параметры предмета

export function CalcParams({ item, list, onChange, readOnly }: { item: Item; list: CalcInfo[]; onChange: (params: Record<string, unknown>) => void; readOnly: boolean }) {
  const mine = list.filter((c) => c.type_ids.includes(item.type_id) && c.params.length);
  if (!mine.length) return null;
  return (
    <div className="grid grid-cols-2 gap-2" aria-label="Параметры расчётов">
      {mine.flatMap((c) =>
        c.params.map((p) => {
          const key = `${c.key}.${p.key}`;
          const v = item.params?.[key];
          return (
            <ParamField
              key={key}
              label={`${p.title}${p.unit ? `, ${p.unit}` : ""}`}
              hint={`${c.title}. ${p.hint}`}
              value={typeof v === "number" ? v : null}
              disabled={readOnly}
              onChange={(value) => {
                const next = { ...item.params };
                if (value === null) delete next[key];
                else next[key] = Math.min(p.high ?? Infinity, Math.max(p.low ?? -Infinity, value));
                onChange(next);
              }}
            />
          );
        }),
      )}
    </div>
  );
}

// Число или пусто — «по умолчанию» (что это значит, решает модуль расчёта)
function ParamField({ label, hint, value, disabled, onChange }: { label: string; hint: string; value: number | null; disabled: boolean; onChange: (v: number | null) => void }) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => setText(value === null ? "" : String(value)), [value]);
  const commit = () => {
    const t = text.trim().replace(",", ".");
    if (!t) {
      if (value !== null) onChange(null);
      return;
    }
    const v = Number.parseFloat(t);
    if (Number.isFinite(v)) {
      if (v !== value) onChange(v);
    } else setText(value === null ? "" : String(value));
  };
  return (
    <label className="flex flex-col gap-1 text-[12px] text-ink-2" title={hint}>
      {label}
      <input
        type="text"
        inputMode="decimal"
        value={text}
        disabled={disabled}
        placeholder="по умолчанию"
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
        className="h-8 w-full min-w-0 rounded-md border border-line-strong bg-surface px-2 font-mono text-[13px] text-ink max-md:h-11"
      />
    </label>
  );
}
