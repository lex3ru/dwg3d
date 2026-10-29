// 3D из плана (5.1.7): стены на высоту этажа с проёмами, перекрытия, колонны, лестницы,
// шахты лифтов. Метры; ось Y вверх; X плана → x, Y плана → −z.

import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { add, centerline, extend, joinExtensions, pointAt, polylineLength, rot, type Lift, type Plan, type Pt } from "./plan";

export const SLAB = 0.2; // толщина перекрытия, м
const M = 0.001;

// В узле стены перекрываются: верх перегородки совпадает с верхом несущей стены, торец — с её
// гранью, колонна в стене — с верхом стены. Такие грани разных материалов «дерутся» в буфере
// глубины и мерцают при повороте (R-029). При равной глубине видна грань с меньшим сдвигом
// (polygonOffset материала): колонна, затем несущая стена, затем перегородка.
export const DEPTH_OFFSET = { columns: 0, bearing: 1, partition: 2 } as const;

// Ближняя плоскость камеры, м. В прогулке — у самых стен; в обзоре — по расстоянию до цели:
// точность глубины около d² / (near · 2²⁴), с near 0,05 м на 150 м неразличимы грани ближе 3 см
export const WALK_NEAR = 0.05;
export function orbitNear(distance: number): number {
  return Math.min(5, Math.max(WALK_NEAR, distance / 200));
}

export interface FloorGeometry {
  bearing: THREE.BufferGeometry | null;
  partition: THREE.BufferGeometry | null;
  glass: THREE.BufferGeometry | null;
  slab: THREE.BufferGeometry | null;
  columns: THREE.BufferGeometry | null;
  stairs: THREE.BufferGeometry | null;
}

// Отрезок стены для столкновений при прогулке: проходимые проёмы — разрывы
export interface Blocker {
  a: Pt; // мм
  b: Pt;
  half: number; // полутолщина, мм
}

function box(a: Pt, b: Pt, thickness: number, y0: number, y1: number): THREE.BufferGeometry | null {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (len < 1 || y1 - y0 < 1) return null;
  const g = new THREE.BoxGeometry(len * M, (y1 - y0) * M, thickness * M);
  g.rotateY(Math.atan2(b[1] - a[1], b[0] - a[0]));
  g.translate(((a[0] + b[0]) / 2) * M, ((y0 + y1) / 2) * M, (-(a[1] + b[1]) / 2) * M);
  return g;
}

function merge(parts: (THREE.BufferGeometry | null)[]): THREE.BufferGeometry | null {
  const list = parts.filter((g): g is THREE.BufferGeometry => g !== null).map((g) => (g.index ? g.toNonIndexed() : g));
  if (!list.length) return null;
  for (const g of list) {
    for (const name of Object.keys(g.attributes)) if (!["position", "normal"].includes(name)) g.deleteAttribute(name);
  }
  return mergeGeometries(list);
}

// Куски стены вдоль осевой линии: [s0, s1, низ, верх] в мм
function wallPieces(plan: Plan, wallId: string, length: number, height: number): [number, number, number, number][] {
  const ops = plan.openings.filter((o) => o.wall === wallId).sort((a, b) => a.at - b.at);
  const out: [number, number, number, number][] = [];
  let s = 0;
  for (const o of ops) {
    const s0 = Math.max(0, o.at - o.width / 2);
    const s1 = Math.min(length, o.at + o.width / 2);
    if (s0 > s) out.push([s, s0, 0, height]);
    if (o.sill > 0) out.push([s0, s1, 0, Math.min(o.sill, height)]);
    const top = o.sill + o.height;
    if (top < height) out.push([s0, s1, top, height]);
    s = Math.max(s, s1);
  }
  if (s < length) out.push([s, length, 0, height]);
  return out;
}

function along(line: Pt[], s0: number, s1: number): [Pt, Pt][] {
  // прямую стену — одним куском, дугу — по отрезкам разбиения
  if (line.length === 2) return [[pointAt(line, s0).p, pointAt(line, s1).p]];
  const out: [Pt, Pt][] = [];
  const n = Math.max(1, Math.ceil((s1 - s0) / 150));
  for (let i = 0; i < n; i++) out.push([pointAt(line, s0 + ((s1 - s0) * i) / n).p, pointAt(line, s0 + ((s1 - s0) * (i + 1)) / n).p]);
  return out;
}

export function buildFloor(plan: Plan, height: number, slabs: Pt[][], nextElevationDelta: number | null): FloorGeometry {
  const bearing: (THREE.BufferGeometry | null)[] = [];
  const partition: (THREE.BufferGeometry | null)[] = [];
  const glass: (THREE.BufferGeometry | null)[] = [];
  const ext = joinExtensions(plan);
  for (const w of plan.walls) {
    const line = centerline(plan, w);
    if (line.length < 2) continue;
    const length = polylineLength(line);
    const target = w.kind === "bearing" ? bearing : partition;
    for (const [s0, s1, y0, y1] of wallPieces(plan, w.id, length, height)) {
      const segs = along(line, s0, s1);
      // углы: крайние куски продлеваются за узел, где сходятся стены
      if (s0 === 0 && y0 === 0) segs[0] = extend(segs[0]!, ext.get(w.a) ?? 0, 0) as [Pt, Pt];
      if (s1 === length && y0 === 0) segs[segs.length - 1] = extend(segs[segs.length - 1]!, 0, ext.get(w.b) ?? 0) as [Pt, Pt];
      for (const [a, b] of segs) target.push(box(a, b, w.thickness, y0, y1));
    }
    for (const o of plan.openings) {
      if (o.wall !== w.id || (o.kind !== "window" && o.kind !== "glazing")) continue;
      for (const [a, b] of along(line, o.at - o.width / 2, o.at + o.width / 2)) glass.push(box(a, b, 20, o.sill, Math.min(o.sill + o.height, height)));
    }
  }
  const slabParts = slabs.map((outline) => {
    const shape = new THREE.Shape(outline.map(([x, y]) => new THREE.Vector2(x * M, y * M)));
    const g = new THREE.ExtrudeGeometry(shape, { depth: SLAB, bevelEnabled: false });
    g.rotateX(-Math.PI / 2); // плоскость XY плана → пол XZ; выдавливание вверх
    g.translate(0, -SLAB, 0);
    return g;
  });
  const columns = plan.columns.map((c) => {
    const g = c.round ? new THREE.CylinderGeometry((c.w / 2) * M, (c.w / 2) * M, height * M, 24) : new THREE.BoxGeometry(c.w * M, height * M, c.d * M);
    g.rotateY((c.angle * Math.PI) / 180);
    g.translate(c.x * M, (height / 2) * M, -c.y * M);
    return g;
  });
  const stairs: THREE.BufferGeometry[] = [];
  const rise = nextElevationDelta ?? height;
  for (const s of plan.stairs) {
    const step = s.length / s.steps;
    for (let i = 0; i < s.steps; i++) {
      const top = (rise * (i + 1)) / s.steps;
      const c = add([s.x, s.y], rot([step * (i + 0.5), 0], s.angle));
      const g = new THREE.BoxGeometry(step * M, Math.max(top, 20) * M, s.width * M);
      g.rotateY((s.angle * Math.PI) / 180);
      g.translate(c[0] * M, (top / 2) * M, -c[1] * M);
      stairs.push(g);
    }
  }
  return { bearing: merge(bearing), partition: merge(partition), glass: merge(glass), slab: merge(slabParts), columns: merge(columns), stairs: merge(stairs) };
}

export function liftGeometry(lift: Lift, bottom: number, top: number): THREE.BufferGeometry {
  const g = new THREE.BoxGeometry(lift.w * M, (top - bottom) * M, lift.d * M);
  g.rotateY((lift.angle * Math.PI) / 180);
  g.translate(lift.x * M, ((bottom + top) / 2) * M, -lift.y * M);
  return g;
}

export function blockers(plan: Plan): Blocker[] {
  const out: Blocker[] = [];
  for (const w of plan.walls) {
    const line = centerline(plan, w);
    if (line.length < 2) continue;
    const length = polylineLength(line);
    const open = plan.openings.filter((o) => o.wall === w.id && (o.kind === "door" || o.kind === "passage")).sort((a, b) => a.at - b.at);
    let s = 0;
    const spans: [number, number][] = [];
    for (const o of open) {
      if (o.at - o.width / 2 > s) spans.push([s, o.at - o.width / 2]);
      s = Math.max(s, o.at + o.width / 2);
    }
    if (s < length) spans.push([s, length]);
    for (const [s0, s1] of spans) for (const [a, b] of along(line, s0, s1)) out.push({ a, b, half: w.thickness / 2 });
  }
  for (const c of plan.columns) {
    const r = Math.max(c.w, c.d) / 2;
    out.push({ a: [c.x - 1, c.y], b: [c.x + 1, c.y], half: r });
  }
  return out;
}
