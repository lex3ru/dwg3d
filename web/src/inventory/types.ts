// Учёт имущества — как его отдаёт сервер (server/app/modules/inventory)

export type State = "in_use" | "broken" | "repair" | "storage" | "not_found" | "written_off";
export type DocKind = "opening" | "receipt" | "transfer" | "repair" | "writeoff" | "revaluation" | "inventory";

export const STATES: Record<State, string> = {
  in_use: "в работе",
  broken: "неисправна",
  repair: "в ремонте",
  storage: "на хранении",
  not_found: "не найдена",
  written_off: "списана",
};

export const KINDS: Record<DocKind, string> = {
  opening: "Ввод остатков",
  receipt: "Приход",
  transfer: "Перемещение",
  repair: "Ремонт",
  writeoff: "Списание",
  revaluation: "Переоценка",
  inventory: "Инвентаризация",
};

// документы, которые заводятся из «Документов»; инвентаризация — своим экраном (6.5.8)
export const NEW_KINDS: DocKind[] = ["opening", "receipt", "transfer", "repair", "writeoff", "revaluation"];

export interface PlaceRef {
  key: string;
  kind: "room" | "warehouse" | "cell";
  title: string;
  short: string;
  building_id: string | null;
  floor_id: string | null;
  room_id: string | null;
  warehouse_id: string | null;
}

export interface UnitBrief {
  id: string;
  number?: string;
  label_code?: string;
  type_id: string;
  type_name: string;
  model_id: string | null;
  model_name: string;
  title: string;
  layer_id: string | null;
  serial: string;
  place: PlaceRef | null;
  state: State;
  state_title: string;
  responsible: string;
  department: string;
  commissioned_on: string;
  parent_id: string | null;
  photo_url: string | null;
  price?: number;
  value?: number;
  life_months?: number | null;
  version: number;
}

export interface UnitChar {
  id: string;
  name: string;
  kind: "text" | "number" | "date" | "bool" | "choice";
  unit: string;
  choices: string[];
  level: "type" | "model" | "item";
  required: boolean;
  value: unknown;
}

export interface UnitFull extends UnitBrief {
  characteristics: UnitChar[];
  note: string;
  written_off_on: string | null;
  writeoff_reason: string;
  files: { id: string; link_id: string; name: string; size: number; content_type: string; url: string; kind: "photo" | "doc" }[];
  parent: { id: string; title: string; number: string | null } | null;
  children: { id: string; title: string; number: string | null }[];
  changes: { id: string; at: string; actor: string; before: Record<string, unknown>; after: Record<string, unknown>; rolled_back: boolean; can_roll_back: boolean }[];
  movements: { document_id: string; title: string; kind: DocKind; status: string; date: string; from: string; to: string }[];
  value_base?: number | null;
  value_date?: string | null;
}

export interface Registry {
  total: number;
  items: UnitBrief[];
  sum_price?: number;
  sum_value?: number;
}

export interface Warehouse {
  id: string;
  key: string;
  name: string;
  building_id: string | null;
  room_id: string | null;
  note: string;
  label_code: string;
  archived: boolean;
  cells: { id: string; key: string; name: string; label_code: string }[];
  version: number;
}

export interface PlaceTree {
  buildings: { id: string; name: string; floors: { id: string; name: string; rooms: { key: string; title: string; number: string; name: string }[] }[] }[];
  warehouses: Warehouse[];
}

export interface Balance {
  place: string;
  place_title: string;
  type_id: string;
  type_name: string;
  model_id: string | null;
  model_name: string;
  unit: string;
  qty: number;
  amount?: number;
  avg_price?: number;
}

export interface DocLine {
  id?: string;
  unit_id?: string | null;
  number?: string;
  unit_state?: State | null;
  unit_place?: string | null;
  type_id?: string | null;
  type_name?: string;
  accounting?: "piece" | "quantity";
  unit?: string;
  model_id?: string | null;
  model_name?: string;
  qty?: number;
  price?: number | null;
  amount?: number;
  value?: number | null;
  serial?: string;
  responsible?: string;
  department?: string;
  state?: string | null;
  commissioned_on?: string | null;
  life_months?: number | null;
  note?: string;
  from_place?: string | null;
  from_title?: string;
  to_place?: string | null;
  to_title?: string;
  reason?: string;
  new_value?: number | null;
  created_units?: { id: string; number: string }[];
}

export interface Doc {
  id: string;
  kind: DocKind;
  kind_title: string;
  number: number;
  title: string;
  status: "draft" | "posted" | "cancelled";
  date: string;
  from_place: string | null;
  from_title: string;
  to_place: string | null;
  to_title: string;
  basis: string;
  supplier: string;
  contractor: string;
  repair: "send" | "return" | null;
  repair_cost: number | null;
  reason: string;
  note: string;
  cancels_id: string | null;
  warnings?: string[];
  cancelled_by_id: string | null;
  created_by: string;
  posted_by: string;
  posted_at: string | null;
  lines: DocLine[];
  total: number;
  files: { id: string; file_id: string; url: string }[];
  version: number;
}

export const money = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽`;

export const dateRu = (iso: string | null | undefined) => (iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("ru-RU") : "—");

export const today = () => new Date().toLocaleDateString("sv-SE"); // ГГГГ-ММ-ДД по местному времени
