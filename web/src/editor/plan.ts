// План этажа — тот же документ, что на сервере (server/app/modules/building/plan.py).
// Миллиметры; X вправо, Y вверх.

export type Pt = [number, number];

export interface Wall {
  id: string;
  a: string;
  b: string;
  thickness: number;
  kind: "bearing" | "partition";
  bulge: number;
}

export type OpeningKind = "door" | "window" | "passage" | "glazing";

export interface Opening {
  id: string;
  wall: string;
  kind: OpeningKind;
  at: number;
  width: number;
  height: number;
  sill: number;
  hinge: "start" | "end";
  side: "left" | "right";
  label?: string | null;
}

export interface Column {
  id: string;
  x: number;
  y: number;
  w: number;
  d: number;
  angle: number;
  round: boolean;
}

export interface Stair {
  id: string;
  x: number;
  y: number;
  width: number;
  length: number;
  angle: number;
  steps: number;
}

export interface RoomLabel {
  id: string;
  x: number;
  y: number;
  number: string;
  name: string;
  purpose_id: string | null;
}

export interface Underlay {
  file_id: string;
  page: number;
  x: number;
  y: number;
  scale: number;
  angle: number;
  opacity: number;
  visible: boolean;
}

export interface Plan {
  nodes: Record<string, Pt>;
  walls: Wall[];
  openings: Opening[];
  columns: Column[];
  stairs: Stair[];
  rooms: RoomLabel[];
  underlay: Underlay | null;
}

export interface Lift {
  id: string;
  name: string;
  x: number;
  y: number;
  w: number;
  d: number;
  angle: number;
  door_side: number;
  floor_ids: string[];
  stop_ids: string[];
}

export interface Issue {
  code: string;
  message: string;
  x: number;
  y: number;
  ids: string[];
  auto: boolean;
}

export interface RoomShape {
  index: number;
  id: string | null;
  label: string | null;
  labels: string[];
  number: string;
  name: string;
  area: number;
  outline: Pt[];
  x: number;
  y: number;
  status: "kept" | "new" | "merged";
}

export interface RoomBrief {
  id: string;
  number: string;
  name: string;
  title: string;
}

// что числится в убираемом помещении: единиц и позиций остатков (R-023, ADR-0008)
export interface RoomProperty {
  units: number;
  stock: number;
}

export interface Check {
  issues: Issue[];
  rooms: RoomShape[];
  merges: { index: number; rooms: RoomBrief[]; keep: string | null }[];
  splits: { index: number; from: RoomBrief }[];
  removed: (RoomBrief & { property: RoomProperty | null })[];
  needs_confirmation: boolean;
  slabs: Pt[][];
}

export interface FloorInfo {
  id: string;
  building_id: string;
  name: string;
  position: number;
  elevation: number;
  height: number;
  rooms: number;
  walls: number;
  plan_version: number;
  plan_saved_at: string | null;
  version: number;
}

export interface Room {
  id: string;
  floor_id: string;
  number: string;
  name: string;
  purpose_id: string | null;
  area: number;
  outline: Pt[];
  x: number;
  y: number;
}

export interface PlanView {
  floor: FloorInfo;
  building: { id: string; name: string; address: string; archived: boolean };
  floors: FloorInfo[];
  plan: Plan;
  plan_version: number;
  rooms: Room[];
  slabs: Pt[][];
  issues: Issue[];
  lifts: Lift[];
  label_ids?: Record<string, string>;
}

export const emptyPlan = (): Plan => ({ nodes: {}, walls: [], openings: [], columns: [], stairs: [], rooms: [], underlay: null });

let counter = 0;
export const newId = (prefix: string) => `${prefix}${Date.now().toString(36)}${(counter++).toString(36)}`;

// ---------------------------------------------------------------- геометрия

export const dist = (a: Pt, b: Pt) => Math.hypot(b[0] - a[0], b[1] - a[1]);
export const add = (a: Pt, b: Pt): Pt => [a[0] + b[0], a[1] + b[1]];
export const sub = (a: Pt, b: Pt): Pt => [a[0] - b[0], a[1] - b[1]];
export const mul = (a: Pt, k: number): Pt => [a[0] * k, a[1] * k];
export const rot = (p: Pt, deg: number): Pt => {
  const r = (deg * Math.PI) / 180;
  return [p[0] * Math.cos(r) - p[1] * Math.sin(r), p[0] * Math.sin(r) + p[1] * Math.cos(r)];
};

// Осевая линия стены: прямая — две точки, дуга — по bulge, как на сервере (geometry.arc_points)
export function arcPoints(a: Pt, b: Pt, bulge: number, step = 100): Pt[] {
  if (Math.abs(bulge) < 1e-9) return [a, b];
  const chord = dist(a, b);
  if (chord < 1e-9) return [a, b];
  const theta = 4 * Math.atan(bulge);
  const radius = chord / (2 * Math.sin(Math.abs(theta) / 2));
  const m: Pt = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const d: Pt = [(b[0] - a[0]) / chord, (b[1] - a[1]) / chord];
  const h = radius * Math.cos(theta / 2);
  const sign = bulge > 0 ? 1 : -1;
  const c: Pt = [m[0] - d[1] * h * sign, m[1] + d[0] * h * sign];
  const start = Math.atan2(a[1] - c[1], a[0] - c[0]);
  const n = Math.max(8, Math.floor((Math.abs(theta) * radius) / step) + 1);
  const out: Pt[] = [];
  for (let i = 0; i <= n; i++) {
    const t = start + (theta * i) / n;
    out.push([c[0] + radius * Math.cos(t), c[1] + radius * Math.sin(t)]);
  }
  return out;
}

export function centerline(plan: Plan, wall: Wall): Pt[] {
  const a = plan.nodes[wall.a];
  const b = plan.nodes[wall.b];
  if (!a || !b) return [];
  return arcPoints(a, b, wall.bulge);
}

export function polylineLength(points: Pt[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += dist(points[i - 1]!, points[i]!);
  return total;
}

// Точка и направление на полилинии на расстоянии s от начала
export function pointAt(points: Pt[], s: number): { p: Pt; dir: Pt } {
  let left = Math.max(0, s);
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!;
    const b = points[i]!;
    const len = dist(a, b);
    if (left <= len || i === points.length - 1) {
      const t = len ? Math.min(left / len, 1) : 0;
      const dir: Pt = len ? [(b[0] - a[0]) / len, (b[1] - a[1]) / len] : [1, 0];
      return { p: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], dir };
    }
    left -= len;
  }
  return { p: points[0] ?? [0, 0], dir: [1, 0] };
}

// Часть полилинии между s0 и s1
export function slice(points: Pt[], s0: number, s1: number): Pt[] {
  const out: Pt[] = [pointAt(points, s0).p];
  let acc = 0;
  for (let i = 1; i < points.length; i++) {
    acc += dist(points[i - 1]!, points[i]!);
    if (acc > s0 && acc < s1) out.push(points[i]!);
  }
  out.push(pointAt(points, s1).p);
  return out;
}

// Насколько продлить стену за узел, где сходятся несколько стен: углы смыкаются без щели
export function joinExtensions(plan: Plan): Map<string, number> {
  const degree = new Map<string, { n: number; t: number }>();
  for (const w of plan.walls)
    for (const id of [w.a, w.b]) {
      const d = degree.get(id) ?? { n: 0, t: 0 };
      degree.set(id, { n: d.n + 1, t: Math.max(d.t, w.thickness) });
    }
  const out = new Map<string, number>();
  for (const [id, d] of degree) if (d.n >= 2) out.set(id, d.t / 2);
  return out;
}

// Продлить полилинию на e0 в начале и на e1 в конце по касательной
export function extend(points: Pt[], e0: number, e1: number): Pt[] {
  if (points.length < 2 || (!e0 && !e1)) return points;
  const out = [...points];
  if (e0) {
    const [a, b] = [points[0]!, points[1]!];
    const d = dist(a, b) || 1;
    out[0] = [a[0] - ((b[0] - a[0]) / d) * e0, a[1] - ((b[1] - a[1]) / d) * e0];
  }
  if (e1) {
    const [a, b] = [points[points.length - 2]!, points[points.length - 1]!];
    const d = dist(a, b) || 1;
    out[out.length - 1] = [b[0] + ((b[0] - a[0]) / d) * e1, b[1] + ((b[1] - a[1]) / d) * e1];
  }
  return out;
}

// Контур полосы шириной width вдоль полилинии (тело стены)
export function band(points: Pt[], width: number): Pt[] {
  if (points.length < 2) return [];
  const half = width / 2;
  const left: Pt[] = [];
  const right: Pt[] = [];
  for (let i = 0; i < points.length; i++) {
    const prev = points[Math.max(0, i - 1)]!;
    const next = points[Math.min(points.length - 1, i + 1)]!;
    const len = dist(prev, next) || 1;
    const n: Pt = [-(next[1] - prev[1]) / len, (next[0] - prev[0]) / len];
    left.push([points[i]![0] + n[0] * half, points[i]![1] + n[1] * half]);
    right.push([points[i]![0] - n[0] * half, points[i]![1] - n[1] * half]);
  }
  return [...left, ...right.reverse()];
}

// Ближайшая точка отрезка
export function projectOnSegment(p: Pt, a: Pt, b: Pt): { p: Pt; t: number; d: number } {
  const ab = sub(b, a);
  const len2 = ab[0] * ab[0] + ab[1] * ab[1];
  const t = len2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / len2)) : 0;
  const q: Pt = [a[0] + ab[0] * t, a[1] + ab[1] * t];
  return { p: q, t, d: dist(p, q) };
}

// Ближайшая точка полилинии: где она и сколько от начала
export function projectOnPolyline(p: Pt, points: Pt[]): { p: Pt; s: number; d: number } {
  let best = { p: points[0] ?? p, s: 0, d: Infinity };
  let acc = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!;
    const b = points[i]!;
    const r = projectOnSegment(p, a, b);
    if (r.d < best.d) best = { p: r.p, s: acc + r.t * dist(a, b), d: r.d };
    acc += dist(a, b);
  }
  return best;
}

// Прямоугольник w × d с центром (x, y), повернутый на angle
export function rect(x: number, y: number, w: number, d: number, angle: number): Pt[] {
  return ([[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]] as Pt[]).map((p) => add([x, y], rot(p, angle)));
}

export function pointInPolygon(p: Pt, poly: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]!;
    const [xj, yj] = poly[j]!;
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export const toPath = (points: Pt[], close = true) =>
  points.length ? `M${points.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L")}${close ? "Z" : ""}` : "";

export function bounds(plan: Plan, extra: Pt[] = []): [number, number, number, number] {
  const pts: Pt[] = [...Object.values(plan.nodes), ...extra];
  for (const c of plan.columns) pts.push([c.x, c.y]);
  for (const s of plan.stairs) pts.push([s.x, s.y]);
  if (!pts.length) return [-1000, -1000, 15000, 10000];
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of pts) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return [minX, minY, maxX, maxY];
}

export const formatM = (mm: number, digits = 2) =>
  (mm / 1000).toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const OPENING_TITLES: Record<OpeningKind, string> = {
  door: "Дверь",
  window: "Окно",
  passage: "Проход",
  glazing: "Витраж",
};

export const OPENING_DEFAULTS: Record<OpeningKind, Pick<Opening, "width" | "height" | "sill">> = {
  door: { width: 900, height: 2100, sill: 0 },
  window: { width: 1500, height: 1500, sill: 800 },
  passage: { width: 1200, height: 2100, sill: 0 },
  glazing: { width: 3000, height: 2700, sill: 0 },
};
