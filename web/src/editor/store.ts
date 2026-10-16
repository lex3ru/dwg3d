import { useSyncExternalStore } from "react";
import type { CalcResult } from "./calc";
import type { Item } from "./items";
import type { Check, Lift, Plan, Pt } from "./plan";

// Состояние редактора: план, выделение, инструмент, отмена и повтор (5.1.4 п. 7).
// Несохранённые правки живут в браузере и переживают закрытие вкладки (6.5.2).

export type Kind = "wall" | "node" | "opening" | "column" | "stair" | "room" | "lift" | "item";
// «Строительство» — стены, проёмы, помещения; «Расстановка» — предметы (6.5.2)
export type Mode = "build" | "place";
export interface Sel {
  kind: Kind;
  id: string;
}

export type Tool =
  | "select"
  | "wall"
  | "arc"
  | "door"
  | "window"
  | "passage"
  | "glazing"
  | "column"
  | "stair"
  | "lift"
  | "room"
  | "cut"
  | "measure"
  | "calibrate";

export interface Snaps {
  nodes: boolean;
  angles: boolean;
  grid: boolean;
}

export interface View {
  scale: number; // пикселей на мм
  x: number; // где на экране точка (0, 0) плана
  y: number;
}

export interface EditorState {
  floorId: string;
  plan: Plan;
  baseVersion: number;
  edits: number;
  past: Plan[];
  future: Plan[];
  selection: Sel[];
  tool: Tool;
  snaps: Snaps;
  view: View;
  check: Check | null;
  lifts: Lift[];
  focus: Pt | null; // куда показать (замечание проверки)
  mode: Mode;
  items: Item[];
  itemPast: ItemOp[];
  itemFuture: ItemOp[];
  placing: string | null; // тип, который ставится щелчком по плану
  placingUnit: string | null; // …и инвентарная единица из «Неразмещённых» (5.5)
  unitStates: Record<string, string>; // состояние связанных единиц — значок на предмете
  unitModels: Record<string, string | null>; // модель единицы — предмет встаёт с ней
  onlyBroken: boolean; // фильтр «показать только неисправное» (6.5.2)
  askRemove: string[] | null; // убирают связанные предметы — спросить, что с единицами
  multiSelect: boolean; // на телефоне касание добавляет к выбранному (вместо Shift)
  project: { id: string; name: string } | null; // режим проекта (5.3.6): правки — в проект
  removedItems: Item[]; // что проект убирает из расстановки — пунктиром
  calcsOn: string[]; // включённые расчёты (5.3.7)
  calcOptions: Record<string, Record<string, string>>;
  calcResults: Record<string, CalcResult>;
  ghosts: Pt[]; // где встанут копии (ряд, сетка)
  hiddenLayers: string[];
  lockedLayers: string[];
}

// Действие расстановки: что было и что стало с затронутыми предметами (null — не было)
export interface ItemOp {
  before: Record<string, Item | null>;
  after: Record<string, Item | null>;
}

type Listener = () => void;
const LIMIT = 200;

export class EditorStore {
  state: EditorState;
  private listeners = new Set<Listener>();

  // отправка действий расстановки на сервер (ставит Loaded)
  sendItems: (op: ItemOp) => void = () => {};

  constructor(floorId: string, plan: Plan, baseVersion: number, lifts: Lift[], items: Item[] = [], mode: Mode = "build") {
    this.state = {
      floorId,
      plan,
      baseVersion,
      edits: 0,
      past: [],
      future: [],
      selection: [],
      tool: "select",
      snaps: { nodes: true, angles: true, grid: true },
      view: { scale: 0.05, x: 80, y: 600 },
      check: null,
      lifts,
      focus: null,
      mode,
      items,
      itemPast: [],
      itemFuture: [],
      placing: null,
      placingUnit: null,
      unitStates: {},
      unitModels: {},
      onlyBroken: false,
      askRemove: null,
      multiSelect: false,
      project: null,
      removedItems: [],
      calcsOn: [],
      calcOptions: {},
      calcResults: {},
      ghosts: [],
      ...layerView(),
    };
  }

  // ---------------------------------------------------------------- расстановка

  // Предварительный вид при перетаскивании предметов — без шага отмены
  previewItems(items: Item[]) {
    this.set({ items });
  }

  // Одно действие расстановки: изменения сразу видны и уходят на сервер (6.5.2)
  changeItems(next: Item[], selection?: Sel[], base: Item[] = this.state.items) {
    const before: Record<string, Item | null> = {};
    const after: Record<string, Item | null> = {};
    const was = new Map(base.map((i) => [i.id, i]));
    const now = new Map(next.map((i) => [i.id, i]));
    for (const [id, item] of now) {
      const old = was.get(id);
      if (old !== item && JSON.stringify(old) !== JSON.stringify(item)) {
        before[id] = old ?? null;
        after[id] = item;
      }
    }
    for (const [id, old] of was) if (!now.has(id)) {
      before[id] = old;
      after[id] = null;
    }
    if (!Object.keys(after).length) {
      this.set({ items: next, selection: selection ?? this.state.selection });
      return;
    }
    const op = { before, after };
    this.set({ items: next, itemPast: [...this.state.itemPast, op].slice(-LIMIT), itemFuture: [], selection: selection ?? this.state.selection });
    this.sendItems(op);
  }

  private replay(op: ItemOp) {
    const map = new Map(this.state.items.map((i) => [i.id, i]));
    for (const [id, item] of Object.entries(op.after)) {
      if (item) map.set(id, { ...item, version: map.get(id)?.version ?? item.version });
      else map.delete(id);
    }
    return [...map.values()];
  }

  undoItems() {
    const past = [...this.state.itemPast];
    const op = past.pop();
    if (!op) return;
    const back = { before: op.after, after: op.before };
    this.set({ items: this.replay(back), itemPast: past, itemFuture: [op, ...this.state.itemFuture], selection: [] });
    this.sendItems(back);
  }

  redoItems() {
    const [op, ...future] = this.state.itemFuture;
    if (!op) return;
    this.set({ items: this.replay(op), itemPast: [...this.state.itemPast, op], itemFuture: future, selection: [] });
    this.sendItems(op);
  }

  // ответ сервера: версии и помещения предметов
  itemsSaved(items: Item[], deleted: string[]) {
    const fresh = new Map(items.map((i) => [i.id, i]));
    const gone = new Set(deleted);
    this.set({
      items: this.state.items.filter((i) => !gone.has(i.id) || fresh.has(i.id)).map((i) => {
        const f = fresh.get(i.id);
        return f ? { ...i, version: f.version, room_id: f.room_id, state: f.state } : i;
      }),
    });
  }

  setLayers(hiddenLayers: string[], lockedLayers: string[]) {
    this.set({ hiddenLayers, lockedLayers });
    try {
      localStorage.setItem("layer-view", JSON.stringify({ hidden: hiddenLayers, locked: lockedLayers }));
    } catch {
      /* не запомнится */
    }
  }

  subscribe = (listener: Listener) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  get = () => this.state;

  set(patch: Partial<EditorState>) {
    this.state = { ...this.state, ...patch };
    for (const l of this.listeners) l();
  }

  // Изменить план одним шагом отмены
  apply(change: (plan: Plan) => void, selection?: Sel[]) {
    const next = structuredClone(this.state.plan);
    change(next);
    this.commit(next, selection);
  }

  commit(next: Plan, selection?: Sel[]) {
    const past = [...this.state.past, this.state.plan].slice(-LIMIT);
    this.set({ plan: next, past, future: [], edits: this.state.edits + 1, selection: selection ?? this.state.selection });
    this.saveDraft();
  }

  // Предварительный вид при перетаскивании — без шага отмены; шаг — в конце (finish)
  preview(next: Plan) {
    this.set({ plan: next });
  }

  undo() {
    const past = [...this.state.past];
    const prev = past.pop();
    if (!prev) return;
    this.set({ plan: prev, past, future: [this.state.plan, ...this.state.future], edits: this.state.edits + 1, selection: [] });
    this.saveDraft();
  }

  redo() {
    const [next, ...future] = this.state.future;
    if (!next) return;
    this.set({ plan: next, past: [...this.state.past, this.state.plan], future, edits: this.state.edits + 1, selection: [] });
    this.saveDraft();
  }

  saved(plan: Plan, version: number) {
    this.set({ plan, baseVersion: version, edits: 0, past: [], future: [] });
    clearDraft(this.state.floorId);
  }

  private saveDraft() {
    try {
      localStorage.setItem(draftKey(this.state.floorId), JSON.stringify({ base: this.state.baseVersion, edits: this.state.edits, plan: this.state.plan, at: new Date().toISOString() }));
    } catch {
      /* хранилище недоступно или полно — правки живут до закрытия вкладки */
    }
  }
}

const draftKey = (floorId: string) => `plan-draft:${floorId}`;

// Какие слои скрыты и заблокированы — у каждого человека своё, в браузере. null — ещё
// не трогали: тогда по видимости слоя из каталога.
function layerView(): { hiddenLayers: string[]; lockedLayers: string[]; layersTouched?: boolean } {
  try {
    const raw = localStorage.getItem("layer-view");
    if (raw) {
      const v = JSON.parse(raw) as { hidden: string[]; locked: string[] };
      return { hiddenLayers: v.hidden ?? [], lockedLayers: v.locked ?? [] };
    }
  } catch {
    /* по умолчанию */
  }
  return { hiddenLayers: [], lockedLayers: [] };
}

export const layersChosen = () => {
  try {
    return localStorage.getItem("layer-view") !== null;
  } catch {
    return false;
  }
};

export interface Draft {
  base: number;
  edits: number;
  plan: Plan;
  at: string;
}

export function readDraft(floorId: string): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(floorId));
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    return null;
  }
}

export function clearDraft(floorId: string) {
  try {
    localStorage.removeItem(draftKey(floorId));
  } catch {
    /* нечего чистить */
  }
}

export function useEditor<T>(store: EditorStore, pick: (s: EditorState) => T): T {
  return useSyncExternalStore(store.subscribe, () => pick(store.state));
}

export const isSelected = (selection: Sel[], kind: Kind, id: string) => selection.some((s) => s.kind === kind && s.id === id);
