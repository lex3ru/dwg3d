import { useEffect, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { placeModel, transformOf } from "@/catalog/model3d";
import type { TypeBrief } from "@/catalog/types";
import { sizeOf } from "./items";

// Вид сверху на 2D-плане (5.3.2): предмет рисуется чертежом из той же 3D-модели, что в 3D, —
// как мебель на архитектурном плане: силуэт заливкой в цвете слоя и видимые сверху рёбра
// линиями. Модель снимается один раз на тип ортогональной камерой сверху: силуэт — по маске,
// какие рёбра видны (а какие скрыты под сиденьем, столешницей) — по карте высот. Получаются
// пути SVG в координатах предмета (мм): x вправо, y — к передней стороне, вверх.

export interface TopView {
  fill: string; // силуэт
  coarse: string; // он же грубее — для мелкого масштаба
  lines: string; // видимые рёбра
}

const SIDE = 320; // пикселей по большей стороне снимка
const EDGE_ANGLE = 35; // ребро — где грани сходятся под углом больше
const done = new Map<string, TopView | null>();
const pending = new Map<string, Promise<TopView | null>>();
let renderer: THREE.WebGLRenderer | null = null;
let queue: Promise<unknown> = Promise.resolve();
const loader = new GLTFLoader();

const keyOf = (t: TypeBrief) => `${t.model_url}|${JSON.stringify(t.model_transform ?? {})}|${t.width}|${t.depth}|${t.height}`;

// у типа есть 3D-модель и он рисуется контуром (не значком) — рисуем видом сверху
export const hasTopView = (t: TypeBrief | undefined): t is TypeBrief => !!t?.model_url && t.top_view !== "icon";

// высота точки в цвет (R — старшая часть, G — младшая): точность в 1/65 000 высоты модели
const heightMaterial = (minY: number, maxY: number) =>
  new THREE.ShaderMaterial({
    side: THREE.DoubleSide,
    uniforms: { minY: { value: minY }, span: { value: Math.max(maxY - minY, 1e-6) } },
    vertexShader: "varying float vY; void main() { vec4 w = modelMatrix * vec4(position, 1.0); vY = w.y; gl_Position = projectionMatrix * viewMatrix * w; }",
    fragmentShader:
      "uniform float minY; uniform float span; varying float vY; void main() { float h = clamp((vY - minY) / span, 0.0, 1.0) * 255.0; gl_FragColor = vec4(floor(h) / 255.0, fract(h), 0.0, 1.0); }",
  });

async function render(t: TypeBrief): Promise<TopView | null> {
  const gltf = await loader.loadAsync(t.model_url!);
  const { w, d, h } = sizeOf(t);
  const model = placeModel(gltf.scene, transformOf(t.model_transform), [w, h, d]);
  model.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(model);
  if (box.isEmpty()) return null;
  const width = box.max.x - box.min.x;
  const depth = box.max.z - box.min.z;
  if (width <= 0 || depth <= 0) return null;
  const k = SIDE / Math.max(width, depth); // пикселей на метр
  const W = Math.max(8, Math.round(width * k));
  const H = Math.max(8, Math.round(depth * k));

  // карта высот сверху: камера смотрит вниз, вверх на снимке — передняя сторона (−Z сцены)
  renderer ??= new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  const target = new THREE.WebGLRenderTarget(W, H);
  const mat = heightMaterial(box.min.y, box.max.y);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0, 0, 1); // синий — пусто
  scene.add(model);
  model.traverse((o) => {
    if ((o as THREE.Mesh).isMesh) (o as THREE.Mesh).material = mat;
  });
  const camera = new THREE.OrthographicCamera(box.min.x, box.max.x, -box.min.z, -box.max.z, 0.01, 100);
  camera.up.set(0, 0, -1);
  camera.position.set(0, box.max.y + 1, 0);
  camera.lookAt(0, 0, 0);
  renderer.setRenderTarget(target);
  renderer.render(scene, camera);
  const px = new Uint8Array(W * H * 4);
  renderer.readRenderTargetPixels(target, 0, 0, W, H, px);
  renderer.setRenderTarget(null);
  target.dispose();
  mat.dispose();
  // снимок читается снизу вверх: строка 0 — задняя сторона (сцена +Z)
  const filled = (i: number, j: number) => i >= 0 && j >= 0 && i < W && j < H && px[(j * W + i) * 4 + 2]! < 128;
  const heightAt = (i: number, j: number) => {
    const o = (j * W + i) * 4;
    return box.min.y + ((px[o]! + px[o + 1]! / 255) / 255) * (box.max.y - box.min.y);
  };

  // мм в координатах предмета: x вправо, y вперёд (сцена −Z)
  const mmX = (x: number) => Math.round(x * 10000) / 10;
  const mmY = (z: number) => Math.round(-z * 10000) / 10;
  const pixToX = (i: number) => box.min.x + (i / W) * width;
  const pixToZ = (j: number) => box.max.z - (j / H) * depth;

  const outline = contours(W, H, filled);
  const toPath = (polys: [number, number][][]) =>
    polys
      .filter((poly) => poly.length >= 3)
      .map((poly) => "M" + poly.map(([i, j]) => `${mmX(pixToX(i))},${mmY(pixToZ(j))}`).join("L") + "Z")
      .join("");
  const fill = toPath(outline.map((poly) => simplify(poly, 0.8)));
  const coarse = toPath(outline.filter((poly) => poly.length > 12).map((poly) => simplify(poly, SIDE / 60)));

  // видимые сверху рёбра: точка ребра видна, если она не ниже поверхности под ней
  const eps = Math.max((box.max.y - box.min.y) * 0.02, 0.004);
  const parts: string[] = [];
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const p = new THREE.Vector3();
  model.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    const edges = new THREE.EdgesGeometry(mesh.geometry, EDGE_ANGLE);
    const pos = edges.getAttribute("position");
    for (let e = 0; e < pos.count; e += 2) {
      a.fromBufferAttribute(pos, e).applyMatrix4(mesh.matrixWorld);
      b.fromBufferAttribute(pos, e + 1).applyMatrix4(mesh.matrixWorld);
      const len = Math.hypot((b.x - a.x) * k, (b.z - a.z) * k);
      if (len < 1) continue;
      const steps = Math.max(2, Math.ceil(len / 2));
      let run: [number, number] | null = null;
      const flush = (to: number) => {
        if (run && (to - run[0]) * len >= 2) {
          const s = new THREE.Vector3().lerpVectors(a, b, run[0]);
          const f = new THREE.Vector3().lerpVectors(a, b, to);
          parts.push(`M${mmX(s.x)},${mmY(s.z)}L${mmX(f.x)},${mmY(f.z)}`);
        }
        run = null;
      };
      for (let s = 0; s <= steps; s++) {
        const tt = s / steps;
        p.lerpVectors(a, b, tt);
        const i = Math.min(W - 1, Math.max(0, Math.floor(((p.x - box.min.x) / width) * W)));
        const j = Math.min(H - 1, Math.max(0, Math.floor(((box.max.z - p.z) / depth) * H)));
        // среди соседних пикселей — самая низкая поверхность: ребро на краю не теряется
        let surface = Infinity;
        for (const [di, dj] of [[0, 0], [1, 0], [-1, 0], [0, 1], [0, -1]] as const) if (filled(i + di, j + dj)) surface = Math.min(surface, heightAt(i + di, j + dj));
        const visible = surface === Infinity || p.y >= surface - eps;
        if (visible && !run) run = [tt, tt];
        else if (!visible) flush(tt);
      }
      flush(1);
    }
    edges.dispose();
  });
  return { fill, coarse: coarse || fill, lines: parts.join("") };
}

// Контуры маски (marching squares) — замкнутые многоугольники в пикселях, упрощённые. Точки —
// на серединах между центрами соседних пикселей; у каждой ровно два соседа, обход —
// без направления (дыры — заливкой even-odd)
function contours(W: number, H: number, inside: (i: number, j: number) => boolean): [number, number][][] {
  const key = (p: [number, number]) => `${p[0] * 2},${p[1] * 2}`;
  const links = new Map<string, string[]>();
  const point = new Map<string, [number, number]>();
  const seg = (p: [number, number], q: [number, number]) => {
    const a = key(p);
    const b = key(q);
    point.set(a, p);
    point.set(b, q);
    (links.get(a) ?? links.set(a, []).get(a)!).push(b);
    (links.get(b) ?? links.set(b, []).get(b)!).push(a);
  };
  for (let j = -1; j < H; j++)
    for (let i = -1; i < W; i++) {
      const c = (inside(i, j) ? 1 : 0) | (inside(i + 1, j) ? 2 : 0) | (inside(i + 1, j + 1) ? 4 : 0) | (inside(i, j + 1) ? 8 : 0);
      if (c === 0 || c === 15) continue;
      const B: [number, number] = [i + 1, j + 0.5];
      const R: [number, number] = [i + 1.5, j + 1];
      const T: [number, number] = [i + 1, j + 1.5];
      const L: [number, number] = [i + 0.5, j + 1];
      if (c === 5) {
        seg(L, T);
        seg(R, B);
      } else if (c === 10) {
        seg(B, L);
        seg(T, R);
      } else {
        const sides = [((c & 1) ^ ((c >> 1) & 1)) ? B : null, (((c >> 1) & 1) ^ ((c >> 2) & 1)) ? R : null, (((c >> 2) & 1) ^ ((c >> 3) & 1)) ? T : null, (((c >> 3) & 1) ^ (c & 1)) ? L : null].filter(Boolean) as [number, number][];
        if (sides.length === 2) seg(sides[0]!, sides[1]!);
      }
    }
  const out: [number, number][][] = [];
  const seen = new Set<string>();
  for (const start of links.keys()) {
    if (seen.has(start)) continue;
    const poly: [number, number][] = [];
    let prev = "";
    let k = start;
    while (k && !seen.has(k)) {
      seen.add(k);
      poly.push(point.get(k)!);
      const n = (links.get(k) ?? []).find((x) => x !== prev && !seen.has(x)) ?? "";
      prev = k;
      k = n;
    }
    if (poly.length >= 3) out.push(poly);
  }
  return out;
}

// Дуглас — Пейкер для замкнутого контура
function simplify(poly: [number, number][], tol: number): [number, number][] {
  const keep = new Uint8Array(poly.length);
  const dist = (p: [number, number], a: [number, number], b: [number, number]) => {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const l = Math.hypot(dx, dy) || 1;
    return Math.abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / l;
  };
  const stack: [number, number][] = [[0, poly.length - 1]];
  keep[0] = keep[poly.length - 1] = 1;
  while (stack.length) {
    const [s, e] = stack.pop()!;
    let best = -1;
    let far = 0;
    for (let i = s + 1; i < e; i++) {
      const dd = dist(poly[i]!, poly[s]!, poly[e]!);
      if (dd > far) {
        far = dd;
        best = i;
      }
    }
    if (best > 0 && far > tol) {
      keep[best] = 1;
      stack.push([s, best], [best, e]);
    }
  }
  return poly.filter((_, i) => keep[i]);
}

// по очереди: один рисующий контекст на все типы
export function topView(t: TypeBrief): Promise<TopView | null> {
  const key = keyOf(t);
  if (done.has(key)) return Promise.resolve(done.get(key)!);
  let p = pending.get(key);
  if (!p) {
    p = (queue = queue.then(() => render(t)).catch(() => null)) as Promise<TopView | null>;
    void p.then((v) => {
      done.set(key, v);
      pending.delete(key);
    });
    pending.set(key, p);
  }
  return p;
}

export function useTopView(t: TypeBrief | undefined): TopView | null {
  const key = hasTopView(t) ? keyOf(t) : null;
  const [view, setView] = useState<TopView | null>(() => (key ? (done.get(key) ?? null) : null));
  useEffect(() => {
    if (!key || !t) {
      setView(null);
      return;
    }
    if (done.has(key)) {
      setView(done.get(key)!);
      return;
    }
    let live = true;
    void topView(t).then((v) => live && setView(v));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return view;
}
