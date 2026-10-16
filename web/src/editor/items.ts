// Предметы на плане (5.3.2): контур, прилипание к стене, размеры до стен, предупреждения,
// ряды и выравнивание. Мм плана, Y вверх; angle — градусы против часовой; у предмета
// ширина — вдоль его оси X, глубина — вдоль Y, «спина» — сторона −Y.

import type { TypeBrief } from "@/catalog/types";
import { add, band, centerline, dist, joinExtensions, extend, pointAt, pointInPolygon, polylineLength, rect, rot, slice, sub, type Plan, type Pt } from "./plan";

export interface Item {
  id: string;
  floor_id: string;
  room_id: string | null;
  type_id: string;
  model_id: string | null;
  parent_id: string | null;
  x: number | null;
  y: number | null;
  angle: number;
  z: number;
  label: string;
  unit_id: string | null; // связанная инвентарная единица (5.5)
  params?: Record<string, unknown>; // параметры для расчётов: «модуль.параметр» (5.3.4)
  state?: "added" | "moved" | "changed" | null; // в проекте: что с ним по сравнению с расстановкой
  version: number;
}

export const DEFAULT_SIZE = 500;

export const sizeOf = (t: TypeBrief | undefined) => ({
  w: t?.width || DEFAULT_SIZE,
  d: t?.depth || DEFAULT_SIZE,
  h: t?.height || DEFAULT_SIZE,
});

export function footprint(item: Item, t: TypeBrief | undefined): Pt[] {
  const { w, d } = sizeOf(t);
  return rect(item.x ?? 0, item.y ?? 0, w, d, item.angle);
}

export const normAngle = (a: number) => ((a % 360) + 360) % 360;

// Высота установки по умолчанию (как на сервере): на полу — 0, на стене — из типа,
// на потолке — под потолком
export function defaultZ(t: TypeBrief, floorHeight: number): number {
  if (t.mount === "wall") return t.mount_height || 1500;
  if (t.mount === "ceiling") return t.mount_height || Math.max(0, floorHeight - (t.height || 0));
  return 0;
}

// ---------------------------------------------------------------- стены как отрезки граней

export interface Face {
  a: Pt;
  b: Pt;
  n: Pt; // нормаль наружу от тела стены (в сторону помещения)
  wall: string;
}

export interface WallSeg {
  a: Pt; // осевая
  b: Pt;
  half: number;
  wall: string;
}

// Осевые отрезки стен (дуги — ломаной) и грани тела стен без проёмов
export function wallGeometry(plan: Plan): { segs: WallSeg[]; faces: Face[]; bodies: Pt[][] } {
  const segs: WallSeg[] = [];
  const faces: Face[] = [];
  const bodies: Pt[][] = [];
  const ext = joinExtensions(plan);
  for (const w of plan.walls) {
    const line = centerline(plan, w);
    if (line.length < 2) continue;
    for (let i = 1; i < line.length; i++) segs.push({ a: line[i - 1]!, b: line[i]!, half: w.thickness / 2, wall: w.id });
    const length = polylineLength(line);
    const ops = plan.openings.filter((o) => o.wall === w.id).sort((a, b) => a.at - b.at);
    let s = 0;
    const pieces: [number, number][] = [];
    for (const o of ops) {
      const s0 = Math.max(0, o.at - o.width / 2);
      if (s0 > s) pieces.push([s, s0]);
      s = Math.max(s, Math.min(length, o.at + o.width / 2));
    }
    if (s < length) pieces.push([s, length]);
    for (const [s0, s1] of pieces) {
      const piece = extend(slice(line, s0, s1), s0 === 0 ? (ext.get(w.a) ?? 0) : 0, s1 === length ? (ext.get(w.b) ?? 0) : 0);
      for (let i = 1; i < piece.length; i++) {
        const [a, b] = [piece[i - 1]!, piece[i]!];
        const len = dist(a, b);
        if (len < 1) continue;
        const n: Pt = [-(b[1] - a[1]) / len, (b[0] - a[0]) / len];
        const h = w.thickness / 2;
        const off = (p: Pt, k: number): Pt => [p[0] + n[0] * k, p[1] + n[1] * k];
        faces.push({ a: off(a, h), b: off(b, h), n, wall: w.id });
        faces.push({ a: off(b, -h), b: off(a, -h), n: [-n[0], -n[1]], wall: w.id });
        bodies.push(band([a, b], w.thickness));
      }
    }
  }
  return { segs, faces, bodies };
}

// ---------------------------------------------------------------- прилипание к стене (5.3.2 п. 1)

export interface Stick {
  x: number;
  y: number;
  angle: number;
  wall: string;
}

// Куда встать предмету спиной к ближайшей стене. reach — насколько далеко искать стену
// (от спины предмета до грани стены).
export function stickToWall(faces: Face[], p: Pt, w: number, d: number, reach: number): Stick | null {
  let best: { face: Face; q: Pt; gap: number } | null = null;
  for (const f of faces) {
    const ab = sub(f.b, f.a);
    const len = Math.hypot(ab[0], ab[1]);
    if (len < w * 0.5) continue;
    const u: Pt = [ab[0] / len, ab[1] / len];
    // проекция центра на грань; предмет должен уместиться по ширине вдоль грани
    const t = (p[0] - f.a[0]) * u[0] + (p[1] - f.a[1]) * u[1];
    const margin = Math.min(w / 2, len / 2);
    const tc = Math.min(Math.max(t, margin), len - margin);
    if (Math.abs(t - tc) > w) continue;
    const q: Pt = [f.a[0] + u[0] * tc, f.a[1] + u[1] * tc];
    // по какую сторону грани центр: только со стороны помещения
    const side = (p[0] - q[0]) * f.n[0] + (p[1] - q[1]) * f.n[1];
    if (side < -d / 2) continue;
    const gap = Math.abs(side - d / 2);
    if (gap > reach) continue;
    if (!best || gap < best.gap) best = { face: f, q, gap };
  }
  if (!best) return null;
  const { face, q } = best;
  const angle = normAngle((Math.atan2(face.n[1], face.n[0]) * 180) / Math.PI - 90);
  return { x: q[0] + face.n[0] * (d / 2), y: q[1] + face.n[1] * (d / 2), angle, wall: face.wall };
}

// ---------------------------------------------------------------- размеры до стен (С6)

export interface Gap {
  from: Pt; // край предмета
  to: Pt; // грань стены
  mm: number;
}

function raySegment(o: Pt, dir: Pt, a: Pt, b: Pt): number | null {
  const e = sub(b, a);
  const den = dir[0] * e[1] - dir[1] * e[0];
  if (Math.abs(den) < 1e-9) return null;
  const ao = sub(a, o);
  const t = (ao[0] * e[1] - ao[1] * e[0]) / den;
  const s = (ao[0] * dir[1] - ao[1] * dir[0]) / den;
  return t > 0 && s >= 0 && s <= 1 ? t : null;
}

// Расстояния от четырёх сторон предмета до ближайших стен по его осям
export function gapsToWalls(faces: Face[], item: Item, w: number, d: number, limit = 15000): Gap[] {
  const c: Pt = [item.x ?? 0, item.y ?? 0];
  const out: Gap[] = [];
  for (const [lx, ly, half] of [[1, 0, w / 2], [-1, 0, w / 2], [0, 1, d / 2], [0, -1, d / 2]] as const) {
    const dir = rot([lx, ly], item.angle);
    let best = Infinity;
    for (const f of faces) {
      // грань смотрит навстречу лучу
      if (f.n[0] * dir[0] + f.n[1] * dir[1] > -0.1) continue;
      const t = raySegment(c, dir, f.a, f.b);
      if (t !== null && t < best) best = t;
    }
    if (best < limit && best > half - 1) {
      const from = add(c, [dir[0] * half, dir[1] * half]);
      const to = add(c, [dir[0] * best, dir[1] * best]);
      out.push({ from, to, mm: Math.max(0, best - half) });
    }
  }
  return out;
}

// ---------------------------------------------------------------- предупреждения (5.3.2 п. 6)

export type WarningCode = "wall" | "door" | "outside" | "overlap";
export const WARNING_TEXT: Record<WarningCode, string> = {
  wall: "пересекает стену",
  door: "перекрывает проём двери",
  outside: "стоит вне помещений",
  overlap: "стоит на другом предмете",
};

function axes(poly: Pt[]): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i < poly.length; i++) {
    const [a, b] = [poly[i]!, poly[(i + 1) % poly.length]!];
    out.push([-(b[1] - a[1]), b[0] - a[0]]);
  }
  return out;
}

// Пересекаются ли два выпуклых многоугольника (с допуском: касание — не пересечение)
export function convexOverlap(p: Pt[], q: Pt[], tolerance = 5): boolean {
  for (const axis of [...axes(p), ...axes(q)]) {
    const len = Math.hypot(axis[0], axis[1]) || 1;
    const n: Pt = [axis[0] / len, axis[1] / len];
    const proj = (poly: Pt[]) => poly.map((v) => v[0] * n[0] + v[1] * n[1]);
    const a = proj(p);
    const b = proj(q);
    if (Math.max(...a) - tolerance <= Math.min(...b) || Math.max(...b) - tolerance <= Math.min(...a)) return false;
  }
  return true;
}

function bbox(poly: Pt[]): [number, number, number, number] {
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of poly) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  return [x0, y0, x1, y1];
}

// Зона двери: полотно открывается в квадрат ширина × ширина; проход — полоса по обе стороны
function doorZones(plan: Plan): { zone: Pt[]; top: number }[] {
  const out: { zone: Pt[]; top: number }[] = [];
  for (const o of plan.openings) {
    if (o.kind !== "door" && o.kind !== "passage") continue;
    const w = plan.walls.find((x) => x.id === o.wall);
    if (!w) continue;
    const line = centerline(plan, w);
    if (line.length < 2) continue;
    const { p, dir } = pointAt(line, o.at);
    const n: Pt = [-dir[1], dir[0]];
    const ang = (Math.atan2(dir[1], dir[0]) * 180) / Math.PI;
    const t = w.thickness / 2;
    const sides = o.kind === "door" ? [o.side === "left" ? 1 : -1] : [1, -1];
    for (const k of sides) {
      const depth = o.kind === "door" ? o.width : 600;
      const c = add(p, [n[0] * k * (t + depth / 2), n[1] * k * (t + depth / 2)]);
      out.push({ zone: rect(c[0], c[1], o.width, depth, ang), top: o.sill + o.height });
    }
  }
  return out;
}

export interface Placed {
  item: Item;
  type: TypeBrief | undefined;
  poly: Pt[];
}

// Предупреждения по предметам этажа. Вложенные не проверяются — они внутри вместилища.
export function warningsFor(plan: Plan, rooms: Pt[][], placed: Placed[]): Map<string, WarningCode[]> {
  const out = new Map<string, WarningCode[]>();
  const push = (id: string, code: WarningCode) => {
    const list = out.get(id) ?? [];
    if (!list.includes(code)) list.push(code);
    out.set(id, list);
  };
  const { bodies } = wallGeometry(plan);
  const bodyBoxes = bodies.map(bbox);
  const doors = doorZones(plan);
  // сетка для «на другом предмете»: 2 м
  const CELL = 2000;
  const grid = new Map<string, number[]>();
  const boxes = placed.map((p) => bbox(p.poly));
  boxes.forEach((b, i) => {
    for (let gx = Math.floor(b[0] / CELL); gx <= Math.floor(b[2] / CELL); gx++)
      for (let gy = Math.floor(b[1] / CELL); gy <= Math.floor(b[3] / CELL); gy++) {
        const key = `${gx}:${gy}`;
        const cell = grid.get(key);
        if (cell) cell.push(i);
        else grid.set(key, [i]);
      }
  });
  const hit = (a: [number, number, number, number], b: [number, number, number, number]) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
  placed.forEach((p, i) => {
    const box = boxes[i]!;
    const { h } = sizeOf(p.type);
    const z0 = p.item.z;
    const z1 = p.item.z + h;
    // стена: тело стены без проёмов
    for (let k = 0; k < bodies.length; k++) if (hit(box, bodyBoxes[k]!) && convexOverlap(p.poly, bodies[k]!, 10)) push(p.item.id, "wall");
    // дверь: только то, что ниже верха проёма
    for (const dz of doors) if (z0 < dz.top && convexOverlap(p.poly, dz.zone, 10)) push(p.item.id, "door");
    // вне помещений: центр не попал ни в одно
    const c: Pt = [p.item.x ?? 0, p.item.y ?? 0];
    if (rooms.length && !rooms.some((r) => pointInPolygon(c, r))) push(p.item.id, "outside");
    // на другом предмете: контуры пересекаются и по высоте тоже
    const seen = new Set<number>();
    for (let gx = Math.floor(box[0] / CELL); gx <= Math.floor(box[2] / CELL); gx++)
      for (let gy = Math.floor(box[1] / CELL); gy <= Math.floor(box[3] / CELL); gy++)
        for (const j of grid.get(`${gx}:${gy}`) ?? []) {
          if (j <= i || seen.has(j)) continue;
          seen.add(j);
          const q = placed[j]!;
          const qz0 = q.item.z;
          const qz1 = q.item.z + sizeOf(q.type).h;
          if (z0 >= qz1 || qz0 >= z1) continue;
          if (hit(box, boxes[j]!) && convexOverlap(p.poly, q.poly, 10)) {
            push(p.item.id, "overlap");
            push(q.item.id, "overlap");
          }
        }
  });
  return out;
}

// ---------------------------------------------------------------- ряды и выравнивание (5.3.2 п. 3)

// Копии предмета рядами вдоль его осей: along × across штук с шагами (мм)
export function arrayCopies(item: Item, along: number, stepAlong: number, across: number, stepAcross: number): Pt[] {
  const out: Pt[] = [];
  for (let j = 0; j < Math.max(1, across); j++)
    for (let i = 0; i < Math.max(1, along); i++) {
      if (i === 0 && j === 0) continue;
      out.push(add([item.x ?? 0, item.y ?? 0], rot([i * stepAlong, j * stepAcross], item.angle)));
    }
  return out;
}

// Сколько копий помещается вдоль оси предмета до стены помещения (С8: «до конца коридора»)
export function fitAlong(item: Item, room: Pt[] | undefined, step: number): number {
  if (!room || step === 0) return 1;
  let n = 1;
  while (n < 500) {
    const p = add([item.x ?? 0, item.y ?? 0], rot([n * step, 0], item.angle));
    if (!pointInPolygon(p, room)) break;
    n++;
  }
  return n;
}

export type Align = "left" | "right" | "top" | "bottom" | "hcenter" | "vcenter";

// Выравнивание выбранных по краю или центру их общих рамок; равный шаг — по осям плана
export function align(placed: Placed[], how: Align): Map<string, Pt> {
  const boxes = placed.map((p) => bbox(p.poly));
  const all = [Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1])), Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))];
  const out = new Map<string, Pt>();
  placed.forEach((p, i) => {
    const b = boxes[i]!;
    let [dx, dy] = [0, 0];
    if (how === "left") dx = all[0]! - b[0];
    if (how === "right") dx = all[2]! - b[2];
    if (how === "bottom") dy = all[1]! - b[1];
    if (how === "top") dy = all[3]! - b[3];
    if (how === "hcenter") dx = (all[0]! + all[2]!) / 2 - (b[0] + b[2]) / 2;
    if (how === "vcenter") dy = (all[1]! + all[3]!) / 2 - (b[1] + b[3]) / 2;
    out.set(p.item.id, [(p.item.x ?? 0) + dx, (p.item.y ?? 0) + dy]);
  });
  return out;
}

export function distribute(placed: Placed[], axis: "x" | "y"): Map<string, Pt> {
  const k = axis === "x" ? 0 : 1;
  const sorted = [...placed].sort((a, b) => (axis === "x" ? (a.item.x ?? 0) - (b.item.x ?? 0) : (a.item.y ?? 0) - (b.item.y ?? 0)));
  const out = new Map<string, Pt>();
  if (sorted.length < 3) return out;
  const first = axis === "x" ? sorted[0]!.item.x! : sorted[0]!.item.y!;
  const last = axis === "x" ? sorted[sorted.length - 1]!.item.x! : sorted[sorted.length - 1]!.item.y!;
  const step = (last - first) / (sorted.length - 1);
  sorted.forEach((p, i) => {
    const at: Pt = [p.item.x ?? 0, p.item.y ?? 0];
    at[k] = first + step * i;
    out.set(p.item.id, at);
  });
  return out;
}

export const newItemId = () => crypto.randomUUID();
