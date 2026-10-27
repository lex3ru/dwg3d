// Каталог — как его отдаёт сервер (server/app/modules/catalog/api.py)

export interface Layer {
  id: string;
  name: string;
  color: string;
  icon: string;
  note: string;
  position: number;
  visible: boolean;
  types: number;
  version: number;
}

export type Kind = "text" | "number" | "date" | "bool" | "choice";
export type Level = "type" | "model" | "item";

export interface Characteristic {
  id: string;
  set_id: string | null;
  type_id: string | null;
  name: string;
  kind: Kind;
  unit: string;
  choices: string[];
  level: Level;
  required: boolean;
  note: string;
  position: number;
  version: number;
}

export interface CharSet {
  id: string;
  name: string;
  position: number;
  types: number;
  characteristics: Characteristic[];
  version: number;
}

export type Mount = "floor" | "wall" | "ceiling" | "none";

export interface TypeBrief {
  id: string;
  name: string;
  layer_id: string | null;
  mount: Mount;
  width: number | null;
  depth: number | null;
  height: number | null;
  mount_height: number | null;
  accounting: "piece" | "quantity";
  unit: string;
  container: boolean;
  top_view: "box" | "icon";
  icon: string;
  model_url: string | null;
  model_transform: { rx?: number; ry?: number; rz?: number; scale?: number; fit?: boolean };
  model_size: [number, number, number] | null;
  model_credit: string | null;
  archived: boolean;
  price?: number | null;
  version: number;
}

export interface ModelInfo {
  id: string;
  type_id: string;
  manufacturer: string;
  name: string;
  article: string;
  supplier: string;
  price?: number | null;
  archived: boolean;
  version: number;
  values: Record<string, unknown>;
}

export interface TypeFull extends TypeBrief {
  set_ids: string[];
  characteristics: Characteristic[];
  values: Record<string, unknown>;
  models: ModelInfo[];
  life_months: number | null;
  used: number;
  accounted: number; // единиц и движений остатков по типу — вид учёта не меняется (R-024)
}

export interface Purpose {
  id: string;
  name: string;
  surface: number;
  norm: number;
  note: string;
  position: number;
  archived: boolean;
  version: number;
}

export interface Tree {
  layers: Layer[];
  sets: CharSet[];
  types: TypeBrief[];
  purposes: Purpose[];
}

export const MOUNTS: Record<Mount, string> = { floor: "на пол", wall: "на стену", ceiling: "на потолок", none: "не ставится" };
export const KINDS: Record<Kind, string> = { text: "текст", number: "число", date: "дата", bool: "да/нет", choice: "выбор из списка" };
export const LEVELS: Record<Level, string> = { type: "у типа", model: "у модели", item: "у каждой вещи" };

export const rub = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;

export function showValue(c: Characteristic, v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (c.kind === "bool") return v ? "да" : "нет";
  if (c.kind === "date") return new Date(String(v)).toLocaleDateString("ru-RU");
  if (c.kind === "number") return `${Number(v).toLocaleString("ru-RU")}${c.unit ? ` ${c.unit}` : ""}`;
  return String(v);
}
