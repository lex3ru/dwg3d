import { useSyncExternalStore } from "react";
import type { Check, Lift, Plan, Pt } from "./plan";

// Состояние редактора: план, выделение, инструмент, отмена и повтор (5.1.4 п. 7).
// Несохранённые правки живут в браузере и переживают закрытие вкладки (6.5.2).

export type Kind = "wall" | "node" | "opening" | "column" | "stair" | "room" | "lift";
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
}

type Listener = () => void;
const LIMIT = 200;

export class EditorStore {
  state: EditorState;
  private listeners = new Set<Listener>();

  constructor(floorId: string, plan: Plan, baseVersion: number, lifts: Lift[]) {
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
    };
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
