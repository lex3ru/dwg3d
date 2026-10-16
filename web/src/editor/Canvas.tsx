import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from "react";
import { footprint, gapsToWalls, normAngle, sizeOf, stickToWall, wallGeometry, type Gap, type Item, type WarningCode } from "./items";
import { CalcWorld, calcLabels } from "./calc";
import { GapLines, Ghosts, ItemShape, layerColor } from "./items2d";
import { itemState, placeAt, type Catalog } from "./placement";
import { addWall, nodeAt, snapPoint, splitWall, translate, wallAt, type Snap } from "./ops";
import {
  OPENING_DEFAULTS, add, band, bounds, centerline, dist, extend, formatM, joinExtensions, newId, pointAt, pointInPolygon, polylineLength, rect, rot, slice, toPath,
  type Lift, type Opening, type OpeningKind, type Plan, type Pt, type Room, type RoomShape, type Wall,
} from "./plan";
import { isSelected, useEditor, type EditorStore, type Sel } from "./store";
import { UnderlayImage, useUnderlayImage } from "./Underlay";

// План этажа в 2D: SVG, мир в миллиметрах с осью Y вверх; подписи — в экранных координатах.

export interface WallDefaults {
  thickness: number;
  kind: Wall["kind"];
}

interface Props {
  store: EditorStore;
  readOnly: boolean;
  floorId: string;
  dbRooms: Room[];
  wallDefaults: WallDefaults;
  onCreateLift: (p: Pt) => void;
  onLiftMoved: (lift: Lift, p: Pt) => void;
  onCalibrate: (a: Pt, b: Pt) => void;
  onLengthPrompt: (open: { at: [number, number]; apply: (mm: number) => void } | null) => void;
  walker?: { p: Pt; angle: number } | null;
  cat: Catalog | null;
  warnings: Map<string, WarningCode[]>;
  floorHeight: number;
}

type Drag =
  | { kind: "pan"; sx: number; sy: number; vx: number; vy: number }
  | { kind: "move"; start: Pt; base: Plan; sel: Sel[]; moved: boolean }
  | { kind: "node"; id: string; base: Plan; moved: boolean }
  | { kind: "opening"; id: string; base: Plan; moved: boolean }
  | { kind: "lift"; lift: Lift; start: Pt; moved: boolean; p: Pt }
  | { kind: "box"; start: Pt; now: Pt }
  | { kind: "items"; start: Pt; base: Item[]; ids: string[]; moved: boolean }
  | { kind: "rotate"; id: string; base: Item[] };

const OPENING_TOOLS: OpeningKind[] = ["door", "window", "passage", "glazing"];
const BROKEN = new Set(["broken", "repair"]);

export function Canvas({ store, readOnly, floorId, dbRooms, wallDefaults, onCreateLift, onLiftMoved, onCalibrate, onLengthPrompt, walker, cat, warnings, floorHeight }: Props) {
  const mode = useEditor(store, (s) => s.mode);
  const items = useEditor(store, (s) => s.items);
  const placing = useEditor(store, (s) => s.placing);
  const ghosts = useEditor(store, (s) => s.ghosts);
  const hiddenLayers = useEditor(store, (s) => s.hiddenLayers);
  const lockedLayers = useEditor(store, (s) => s.lockedLayers);
  const unitStates = useEditor(store, (s) => s.unitStates);
  const calcResults = useEditor(store, (s) => s.calcResults);
  const onlyBroken = useEditor(store, (s) => s.onlyBroken);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const plan = useEditor(store, (s) => s.plan);
  const view = useEditor(store, (s) => s.view);
  const tool = useEditor(store, (s) => s.tool);
  const selection = useEditor(store, (s) => s.selection);
  const check = useEditor(store, (s) => s.check);
  const snaps = useEditor(store, (s) => s.snaps);
  const lifts = useEditor(store, (s) => s.lifts);
  const focus = useEditor(store, (s) => s.focus);
  const svg = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [cursor, setCursor] = useState<Snap | null>(null);
  const [chain, setChain] = useState<Pt[]>([]); // начатая стена: точки щелчков
  const [measure, setMeasure] = useState<Pt[]>([]);
  const [box, setBox] = useState<[Pt, Pt] | null>(null);
  const drag = useRef<Drag | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ d: number; scale: number; cx: number; cy: number; vx: number; vy: number } | null>(null);
  const space = useRef(false);
  const { image } = useUnderlayImage(plan.underlay);
  const faces = useMemo(() => wallGeometry(plan).faces, [plan]);

  // ---------------------------------------------------------------- вид

  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setSize({ w: entry!.contentRect.width, h: entry!.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fit = useCallback(() => {
    const [minX, minY, maxX, maxY] = bounds(store.state.plan, lifts.map((l) => [l.x, l.y] as Pt));
    const w = Math.max(maxX - minX, 3000);
    const h = Math.max(maxY - minY, 3000);
    const scale = Math.min((size.w - 80) / w, (size.h - 80) / h);
    store.set({ view: { scale, x: size.w / 2 - ((minX + maxX) / 2) * scale, y: size.h / 2 + ((minY + maxY) / 2) * scale } });
  }, [store, size, lifts]);

  const fitted = useRef<string | null>(null);
  useEffect(() => {
    if (size.w > 100 && fitted.current !== floorId) {
      fitted.current = floorId;
      fit();
    }
  }, [floorId, size, fit]);

  useEffect(() => {
    if (!focus) return;
    store.set({ view: { ...store.state.view, x: size.w / 2 - focus[0] * store.state.view.scale, y: size.h / 2 + focus[1] * store.state.view.scale }, focus: null });
  }, [focus, size, store]);

  useEffect(() => {
    const onFit = () => fit();
    // обход: помещение во весь экран (6.5.12)
    const onFitRoom = (e: Event) => {
      const { outline, bottom = 0 } = (e as CustomEvent<{ outline: Pt[]; bottom?: number }>).detail;
      if (!outline?.length) return;
      const xs = outline.map((p) => p[0]);
      const ys = outline.map((p) => p[1]);
      const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
      // снизу экран занят панелью обхода
      const h = size.h - bottom;
      const scale = Math.min((size.w - 40) / Math.max(maxX - minX, 1000), (h - 40) / Math.max(maxY - minY, 1000));
      store.set({ view: { scale, x: size.w / 2 - ((minX + maxX) / 2) * scale, y: h / 2 + ((minY + maxY) / 2) * scale } });
    };
    window.addEventListener("editor:fit", onFit);
    window.addEventListener("editor:fit-room", onFitRoom);
    return () => {
      window.removeEventListener("editor:fit", onFit);
      window.removeEventListener("editor:fit-room", onFitRoom);
    };
  }, [fit, size, store]);

  useEffect(() => {
    setChain([]);
    setMeasure([]);
    onLengthPrompt(null);
  }, [tool, onLengthPrompt]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.code === "Space" && !(e.target instanceof HTMLInputElement)) space.current = true;
      if (e.key === "Escape") {
        setChain([]);
        setMeasure([]);
        onLengthPrompt(null);
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space") space.current = false;
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [onLengthPrompt]);

  const toWorld = (clientX: number, clientY: number): Pt => {
    const r = svg.current!.getBoundingClientRect();
    const v = store.state.view;
    return [(clientX - r.left - v.x) / v.scale, (v.y - (clientY - r.top)) / v.scale];
  };
  const toScreen = (p: Pt): [number, number] => [view.x + p[0] * view.scale, view.y - p[1] * view.scale];

  const onWheel = (e: React.WheelEvent) => {
    const r = svg.current!.getBoundingClientRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    const v = store.state.view;
    const k = Math.exp(-e.deltaY * 0.0015);
    const scale = Math.min(2, Math.max(0.002, v.scale * k));
    const f = scale / v.scale;
    store.set({ view: { scale, x: sx - (sx - v.x) * f, y: sy - (sy - v.y) * f } });
  };

  // ---------------------------------------------------------------- что под курсором

  const tol = 8 / view.scale;

  const hitTest = (p: Pt): Sel | null => {
    const s = store.state;
    const pl = s.plan;
    // узлы выделенных стен
    for (const sel of s.selection) {
      if (sel.kind !== "wall") continue;
      const w = pl.walls.find((x) => x.id === sel.id);
      for (const n of w ? [w.a, w.b] : []) if (pl.nodes[n] && dist(pl.nodes[n], p) <= tol) return { kind: "node", id: n };
    }
    for (const r of pl.rooms) if (dist([r.x, r.y], p) <= 14 / s.view.scale) return { kind: "room", id: r.id };
    for (const o of pl.openings) {
      const w = pl.walls.find((x) => x.id === o.wall);
      if (!w) continue;
      const line = centerline(pl, w);
      const c = pointAt(line, o.at).p;
      if (dist(c, p) <= Math.max(o.width / 2, tol) && wallAt(pl, p, tol)?.wall.id === w.id) return { kind: "opening", id: o.id };
    }
    for (const c of pl.columns) if (pointInPolygon(p, rect(c.x, c.y, c.w + tol, c.d + tol, c.angle))) return { kind: "column", id: c.id };
    for (const st of pl.stairs) {
      const center = add([st.x, st.y], rot([st.length / 2, 0], st.angle));
      if (pointInPolygon(p, rect(center[0], center[1], st.length, st.width, st.angle))) return { kind: "stair", id: st.id };
    }
    for (const l of s.lifts) if (l.floor_ids.includes(floorId) && pointInPolygon(p, rect(l.x, l.y, l.w, l.d, l.angle))) return { kind: "lift", id: l.id };
    const hit = wallAt(pl, p, tol);
    if (hit) return { kind: "wall", id: hit.wall.id };
    return null;
  };

  // предмет под курсором (сверху — последний поставленный); скрытые и заблокированные слои — мимо
  const hitItem = (p: Pt): Item | null => {
    if (!cat) return null;
    const list = store.state.items;
    for (let i = list.length - 1; i >= 0; i--) {
      const it = list[i]!;
      if (it.parent_id) continue;
      const st = itemState(store, cat, it);
      if (!st.shown || st.locked) continue;
      const t = cat.types.get(it.type_id);
      const { w, d } = sizeOf(t);
      const min = 12 / store.state.view.scale;
      if (pointInPolygon(p, footprint(it, t)) || (Math.max(w, d) < min && dist(p, [it.x ?? 0, it.y ?? 0]) < min / 2)) return it;
    }
    return null;
  };

  // ручка поворота выбранного предмета — у его передней стороны, на экране
  const rotateHandle = (): { id: string; at: [number, number] } | null => {
    const sel = store.state.selection;
    if (readOnly || sel.length !== 1 || sel[0]!.kind !== "item" || !cat) return null;
    const it = store.state.items.find((i) => i.id === sel[0]!.id);
    if (!it || it.parent_id) return null;
    const { d } = sizeOf(cat.types.get(it.type_id));
    const c = toScreen([it.x ?? 0, it.y ?? 0]);
    const f = toScreen(add([it.x ?? 0, it.y ?? 0], rot([0, d / 2], it.angle)));
    const len = Math.hypot(f[0] - c[0], f[1] - c[1]) || 1;
    return { id: it.id, at: [f[0] + ((f[0] - c[0]) / len) * 22, f[1] + ((f[1] - c[1]) / len) * 22] };
  };

  const onPlaceDown = (e: RPointerEvent<SVGSVGElement>, p: Pt) => {
    const s = store.state;
    const v = s.view;
    if (s.placing && cat && !readOnly) {
      const t = cat.types.get(s.placing);
      const unit = s.placingUnit ? { id: s.placingUnit, model_id: s.unitModels[s.placingUnit] ?? null } : undefined;
      if (t) placeAt(store, cat, t, p, faces, floorHeight, e.altKey, unit);
      if (!e.shiftKey || unit) store.set({ placing: null, placingUnit: null });
      return;
    }
    const r = svg.current!.getBoundingClientRect();
    const handle = rotateHandle();
    if (handle && Math.hypot(e.clientX - r.left - handle.at[0], e.clientY - r.top - handle.at[1]) < 10) {
      drag.current = { kind: "rotate", id: handle.id, base: s.items };
      return;
    }
    const hit = hitItem(p);
    if (!hit) {
      // подпись помещения — его свойства (и у «просмотра»)
      const room = s.plan.rooms.find((r) => dist([r.x, r.y], p) <= 14 / v.scale);
      if (room) {
        store.set({ selection: [{ kind: "room", id: room.id }] });
        drag.current = { kind: "pan", sx: e.clientX, sy: e.clientY, vx: v.x, vy: v.y };
        return;
      }
      if (!e.shiftKey && !s.multiSelect) store.set({ selection: [] });
      drag.current = readOnly || e.pointerType === "touch" ? { kind: "pan", sx: e.clientX, sy: e.clientY, vx: v.x, vy: v.y } : { kind: "box", start: p, now: p };
      return;
    }
    let sel = s.selection.filter((x) => x.kind === "item");
    if (e.shiftKey || s.multiSelect) sel = isSelected(sel, "item", hit.id) ? sel.filter((x) => x.id !== hit.id) : [...sel, { kind: "item", id: hit.id }];
    else if (!isSelected(sel, "item", hit.id)) sel = [{ kind: "item", id: hit.id }];
    store.set({ selection: sel });
    drag.current = readOnly ? { kind: "pan", sx: e.clientX, sy: e.clientY, vx: v.x, vy: v.y } : { kind: "items", start: p, base: s.items, ids: sel.map((x) => x.id), moved: false };
  };

  // ---------------------------------------------------------------- указатель

  const onPointerDown = (e: RPointerEvent<SVGSVGElement>) => {
    svg.current!.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const r = svg.current!.getBoundingClientRect();
      pinch.current = { d: Math.hypot(a!.x - b!.x, a!.y - b!.y), scale: view.scale, cx: (a!.x + b!.x) / 2 - r.left, cy: (a!.y + b!.y) / 2 - r.top, vx: view.x, vy: view.y };
      drag.current = null;
      return;
    }
    const p = toWorld(e.clientX, e.clientY);
    const v = store.state.view;
    if (e.button === 1 || e.button === 2 || space.current) {
      drag.current = { kind: "pan", sx: e.clientX, sy: e.clientY, vx: v.x, vy: v.y };
      return;
    }
    if (e.button !== 0) return;
    if (store.state.mode === "place") {
      onPlaceDown(e, p);
      return;
    }
    const s = store.state;
    const snap = snapPoint(s.plan, p, v.scale, s.snaps, chain[0] ? chain[chain.length - 1] : null);

    if (readOnly || tool === "select") {
      const hit = hitTest(p);
      if (readOnly) {
        store.set({ selection: hit && hit.kind !== "node" ? [hit] : [] });
        drag.current = { kind: "pan", sx: e.clientX, sy: e.clientY, vx: v.x, vy: v.y };
        return;
      }
      if (!hit) {
        if (!e.shiftKey) store.set({ selection: [] });
        drag.current = e.pointerType === "touch" ? { kind: "pan", sx: e.clientX, sy: e.clientY, vx: v.x, vy: v.y } : { kind: "box", start: p, now: p };
        return;
      }
      if (hit.kind === "node") {
        drag.current = { kind: "node", id: hit.id, base: s.plan, moved: false };
        return;
      }
      let sel = s.selection;
      if (e.shiftKey) sel = isSelected(sel, hit.kind, hit.id) ? sel.filter((x) => !(x.kind === hit.kind && x.id === hit.id)) : [...sel, hit];
      else if (!isSelected(sel, hit.kind, hit.id)) sel = [hit];
      store.set({ selection: sel });
      if (hit.kind === "opening") drag.current = { kind: "opening", id: hit.id, base: s.plan, moved: false };
      else if (hit.kind === "lift") {
        const lift = s.lifts.find((l) => l.id === hit.id)!;
        drag.current = { kind: "lift", lift, start: p, moved: false, p: [lift.x, lift.y] };
      } else drag.current = { kind: "move", start: p, base: s.plan, sel, moved: false };
      return;
    }

    const tolMm = 10 / v.scale;
    switch (tool) {
      case "wall": {
        const last = chain[chain.length - 1];
        if (!last) {
          setChain([snap.p]);
          break;
        }
        store.apply((pl) => {
          addWall(pl, last, snap.p, tolMm, wallDefaults);
        });
        // замкнули контур или попали в существующий узел — цепочка кончилась
        if (dist(snap.p, chain[0]!) < tolMm || (snap.kind === "node" && chain.length > 1)) setChain([]);
        else setChain([...chain, snap.p]);
        break;
      }
      case "arc": {
        if (chain.length < 2) {
          setChain([...chain, snap.p]);
          break;
        }
        const [a, b] = chain as [Pt, Pt];
        const bulge = bulgeFor(a, b, p);
        store.apply((pl) => {
          addWall(pl, a, b, tolMm, { ...wallDefaults, bulge });
        });
        setChain([]);
        break;
      }
      case "door":
      case "window":
      case "passage":
      case "glazing": {
        const hit = wallAt(s.plan, p, tolMm);
        if (!hit) break;
        const d = OPENING_DEFAULTS[tool];
        const width = Math.min(d.width, hit.length);
        const at = Math.min(Math.max(hit.s, width / 2), hit.length - width / 2);
        const id = newId("o");
        const opening: Opening = { id, wall: hit.wall.id, kind: tool, at, width, height: d.height, sill: d.sill, hinge: "start", side: "left" };
        store.apply((pl) => void pl.openings.push(opening), [{ kind: "opening", id }]);
        break;
      }
      case "column": {
        const id = newId("c");
        store.apply((pl) => void pl.columns.push({ id, x: snap.p[0], y: snap.p[1], w: 400, d: 400, angle: 0, round: false }), [{ kind: "column", id }]);
        break;
      }
      case "stair": {
        if (!chain.length) {
          setChain([snap.p]);
          break;
        }
        const a = chain[0]!;
        const length = dist(a, snap.p);
        if (length < 500) break;
        const id = newId("s");
        const angle = (Math.atan2(snap.p[1] - a[1], snap.p[0] - a[0]) * 180) / Math.PI;
        store.apply((pl) => void pl.stairs.push({ id, x: a[0], y: a[1], width: 1200, length, angle, steps: Math.max(2, Math.round(length / 300)) }), [{ kind: "stair", id }]);
        setChain([]);
        break;
      }
      case "lift":
        onCreateLift(snap.p);
        break;
      case "room": {
        const shapes = s.check?.rooms ?? [];
        const shape = shapes.find((r) => pointInPolygon(p, r.outline));
        if (!shape) break;
        if (shape.label) {
          store.set({ selection: [{ kind: "room", id: shape.label }] });
          break;
        }
        const id = newId("new");
        store.apply((pl) => void pl.rooms.push({ id, x: p[0], y: p[1], number: "", name: "", purpose_id: null }), [{ kind: "room", id }]);
        break;
      }
      case "cut": {
        const hit = wallAt(s.plan, p, tolMm);
        if (hit && hit.s > 10 && hit.s < hit.length - 10) store.apply((pl) => void splitWall(pl, hit.wall.id, hit.s));
        break;
      }
      case "measure":
        setMeasure(measure.length === 1 ? [measure[0]!, snap.p] : [snap.p]);
        break;
      case "calibrate":
        if (chain.length === 0) setChain([p]);
        else {
          onCalibrate(chain[0]!, p);
          setChain([]);
        }
        break;
    }
  };

  const onPointerMove = (e: RPointerEvent<SVGSVGElement>) => {
    if (pointers.current.has(e.pointerId)) pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const pc = pinch.current;
      const scale = Math.min(2, Math.max(0.002, (pc.scale * Math.hypot(a!.x - b!.x, a!.y - b!.y)) / pc.d));
      const f = scale / pc.scale;
      store.set({ view: { scale, x: pc.cx - (pc.cx - pc.vx) * f, y: pc.cy - (pc.cy - pc.vy) * f } });
      return;
    }
    const p = toWorld(e.clientX, e.clientY);
    const s = store.state;
    const d = drag.current;
    if (d?.kind === "pan") {
      store.set({ view: { ...s.view, x: d.vx + e.clientX - d.sx, y: d.vy + e.clientY - d.sy } });
      return;
    }
    if (d?.kind === "box") {
      d.now = p;
      setBox([d.start, p]);
      return;
    }
    if (d?.kind === "items" && cat) {
      let dx = p[0] - d.start[0];
      let dy = p[1] - d.start[1];
      if (s.snaps.grid) {
        dx = Math.round(dx / 10) * 10;
        dy = Math.round(dy / 10) * 10;
      }
      if (!d.moved && Math.hypot(dx, dy) * s.view.scale < 3) return;
      d.moved = true;
      const ids = new Set(d.ids);
      let one: Item | null = null;
      const next = d.base.map((it) => {
        if (!ids.has(it.id) || it.parent_id) return it;
        const moved = { ...it, x: (it.x ?? 0) + dx, y: (it.y ?? 0) + dy };
        if (ids.size === 1) {
          const t = cat.types.get(it.type_id);
          const { w, d: depth } = sizeOf(t);
          // к стене: настенный — всегда, напольный — когда спина у стены; Alt — свободно
          if (!e.altKey && t && t.mount !== "ceiling") {
            const stick = stickToWall(faces, [moved.x, moved.y], w, depth, t.mount === "wall" ? 1500 : 150);
            if (stick) Object.assign(moved, { x: stick.x, y: stick.y, angle: stick.angle });
          }
          one = moved;
        }
        return moved;
      });
      store.previewItems(next);
      const single = one as Item | null;
      if (single) {
        const { w, d: depth } = sizeOf(cat.types.get(single.type_id));
        setGaps(gapsToWalls(faces, single, w, depth));
      }
      return;
    }
    if (d?.kind === "rotate") {
      const it = d.base.find((i) => i.id === d.id);
      if (!it) return;
      let angle = (Math.atan2(p[1] - (it.y ?? 0), p[0] - (it.x ?? 0)) * 180) / Math.PI - 90;
      if (!e.altKey) angle = Math.round(angle / 15) * 15;
      store.previewItems(d.base.map((i) => (i.id === d.id ? { ...i, angle: normAngle(angle) } : i)));
      return;
    }
    if (d?.kind === "move") {
      let dx = p[0] - d.start[0];
      let dy = p[1] - d.start[1];
      if (s.snaps.grid) {
        dx = Math.round(dx / 10) * 10;
        dy = Math.round(dy / 10) * 10;
      }
      if (!d.moved && Math.hypot(dx, dy) * s.view.scale < 3) return;
      d.moved = true;
      const next = structuredClone(d.base);
      translate(next, d.base, d.sel, dx, dy);
      store.preview(next);
      return;
    }
    if (d?.kind === "node") {
      const snap = snapPoint(d.base, p, s.view.scale, s.snaps, null, new Set([d.id]));
      d.moved = true;
      const next = structuredClone(d.base);
      next.nodes[d.id] = snap.p;
      store.preview(next);
      setCursor(snap);
      return;
    }
    if (d?.kind === "opening") {
      const base = d.base;
      const op = base.openings.find((o) => o.id === d.id)!;
      const wall = base.walls.find((w) => w.id === op.wall)!;
      const line = centerline(base, wall);
      const length = polylineLength(line);
      const proj = wallAt({ ...base, walls: [wall] }, p, Infinity);
      if (!proj) return;
      let at = Math.min(Math.max(proj.s, op.width / 2), length - op.width / 2);
      if (s.snaps.grid) at = Math.round(at / 10) * 10;
      d.moved = true;
      const next = structuredClone(base);
      next.openings.find((o) => o.id === d.id)!.at = at;
      store.preview(next);
      return;
    }
    if (d?.kind === "lift") {
      d.moved = true;
      d.p = [d.lift.x + p[0] - d.start[0], d.lift.y + p[1] - d.start[1]];
      store.set({ lifts: s.lifts.map((l) => (l.id === d.lift.id ? { ...l, x: d.p[0], y: d.p[1] } : l)) });
      return;
    }
    if (!readOnly && tool !== "select") {
      const from = chain.length && (tool === "wall" || tool === "stair") ? chain[chain.length - 1] : tool === "measure" && measure.length === 1 ? measure[0] : null;
      setCursor(tool === "calibrate" ? { p, kind: "free" } : snapPoint(s.plan, p, s.view.scale, s.snaps, from));
    } else setCursor(null);
  };

  const onPointerUp = (e: RPointerEvent<SVGSVGElement>) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    const s = store.state;
    if ((d.kind === "move" || d.kind === "node" || d.kind === "opening") && d.moved) {
      const next = s.plan;
      store.preview(d.base);
      if (d.kind === "node") {
        // узел, отпущенный на другой узел, сливается с ним
        const target = nodeAt(d.base, next.nodes[d.id]!, 1, new Set([d.id]));
        if (target) {
          const merged = structuredClone(next);
          for (const w of merged.walls) {
            if (w.a === d.id) w.a = target;
            if (w.b === d.id) w.b = target;
          }
          merged.walls = merged.walls.filter((w) => w.a !== w.b);
          delete merged.nodes[d.id];
          store.commit(merged);
        } else store.commit(next);
        setCursor(null);
      } else store.commit(next);
    }
    if (d.kind === "lift" && d.moved) onLiftMoved(d.lift, d.p);
    if ((d.kind === "items" && d.moved) || d.kind === "rotate") {
      const next = s.items;
      store.previewItems(d.base);
      store.changeItems(next);
      setGaps([]);
      return;
    }
    if (d.kind === "box") {
      setBox(null);
      const [a, b] = [d.start, d.now];
      if (dist(a, b) * s.view.scale < 4) return;
      const [x0, x1] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
      const [y0, y1] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
      const inside = (p: Pt) => p[0] >= x0 && p[0] <= x1 && p[1] >= y0 && p[1] <= y1;
      const pl = s.plan;
      if (s.mode === "place") {
        const picked: Sel[] = cat
          ? s.items.filter((it) => !it.parent_id && inside([it.x ?? 0, it.y ?? 0]) && itemState(store, cat, it).shown && !itemState(store, cat, it).locked).map((it) => ({ kind: "item" as const, id: it.id }))
          : [];
        store.set({ selection: e.shiftKey ? [...s.selection, ...picked] : picked });
        return;
      }
      const sel: Sel[] = [
        ...pl.walls.filter((w) => inside(pl.nodes[w.a]!) && inside(pl.nodes[w.b]!)).map((w) => ({ kind: "wall" as const, id: w.id })),
        ...pl.columns.filter((c) => inside([c.x, c.y])).map((c) => ({ kind: "column" as const, id: c.id })),
        ...pl.stairs.filter((c) => inside([c.x, c.y])).map((c) => ({ kind: "stair" as const, id: c.id })),
        ...pl.rooms.filter((c) => inside([c.x, c.y])).map((c) => ({ kind: "room" as const, id: c.id })),
      ];
      store.set({ selection: e.shiftKey ? [...s.selection, ...sel] : sel });
    }
  };

  const onDoubleClick = () => {
    if (tool === "wall") setChain([]);
  };

  // ввод длины с клавиатуры (Enter) при рисовании стены
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || tool !== "wall" || !chain.length || !cursor || e.target instanceof HTMLInputElement) return;
      e.preventDefault();
      const last = chain[chain.length - 1]!;
      const dir = Math.atan2(cursor.p[1] - last[1], cursor.p[0] - last[0]);
      onLengthPrompt({
        at: toScreen(cursor.p),
        apply: (mm) => {
          const end: Pt = [last[0] + Math.cos(dir) * mm, last[1] + Math.sin(dir) * mm];
          store.apply((pl) => void addWall(pl, last, end, 10 / store.state.view.scale, wallDefaults));
          setChain([...chain, end]);
          onLengthPrompt(null);
        },
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ---------------------------------------------------------------- рисование

  const px = 1 / view.scale; // миллиметров в пикселе
  const shapes: (RoomShape | { outline: Pt[]; label: string | null; number: string; name: string; area: number; x: number; y: number; id: string | null })[] =
    check?.rooms ?? dbRooms.map((r) => ({ ...r, label: r.id }));
  const labelOf = new Map(plan.rooms.map((r) => [r.id, r]));

  const world: ReactNode[] = [];
  const overlay: ReactNode[] = [];

  // сетка
  if (snaps.grid || readOnly) {
    const step = view.scale > 0.15 ? 100 : 1000;
    const [x0, y1] = [(-view.x) / view.scale, view.y / view.scale];
    const [x1, y0] = [(size.w - view.x) / view.scale, (view.y - size.h) / view.scale];
    const lines: string[] = [];
    if ((x1 - x0) / step < 400 && (y1 - y0) / step < 400) {
      for (let x = Math.floor(x0 / step) * step; x <= x1; x += step) lines.push(`M${x},${y0}V${y1}`);
      for (let y = Math.floor(y0 / step) * step; y <= y1; y += step) lines.push(`M${x0},${y}H${x1}`);
    }
    world.push(<path key="grid" d={lines.join("")} stroke="var(--line)" strokeWidth={px} fill="none" />);
  }

  if (plan.underlay) world.push(<UnderlayImage key="underlay" underlay={plan.underlay} image={image} />);

  for (const [i, r] of shapes.entries()) {
    const selected = r.label ? isSelected(selection, "room", r.label) : false;
    world.push(
      <path
        key={`room${i}`}
        d={toPath(r.outline)}
        fill={selected ? "var(--accent-soft)" : r.label ? "color-mix(in srgb, var(--accent) 5%, transparent)" : "color-mix(in srgb, var(--warn) 8%, transparent)"}
        stroke={r.label ? "none" : "var(--warn)"}
        strokeDasharray={r.label ? undefined : `${6 * px} ${4 * px}`}
        strokeWidth={px}
      />,
    );
    const label = r.label ? labelOf.get(r.label) : null;
    const at = toScreen(label ? [label.x, label.y] : [r.x, r.y]);
    // мелко — только номер; название и площадь, когда помещаются
    const xs = r.outline.map((p) => p[0]);
    const widthPx = (Math.max(...xs) - Math.min(...xs)) * view.scale;
    const showName = !!label?.name && widthPx > label.name.length * 6.2 + 8;
    const showArea = widthPx > 64;
    overlay.push(
      <g key={`rl${i}`} transform={`translate(${at[0]} ${at[1]})`} style={{ pointerEvents: "none" }}>
        {label ? (
          <>
            <circle r={3} fill={selected ? "var(--accent)" : "var(--ink-3)"} />
            <text y={-6} textAnchor="middle" fontSize={13} fontWeight={600} fill="var(--ink)">
              {label.number || "—"}
            </text>
            {showName && (
              <text y={10} textAnchor="middle" fontSize={11} fill="var(--ink-2)">
                {label.name}
              </text>
            )}
            {showArea && (
              <text y={showName ? 24 : 10} textAnchor="middle" fontSize={11} className="font-mono" fill="var(--ink-3)">
                {r.area.toLocaleString("ru-RU")} м²
              </text>
            )}
          </>
        ) : (
          <text textAnchor="middle" fontSize={11} fill="var(--warn)">
            новое · {r.area.toLocaleString("ru-RU")} м²
          </text>
        )}
      </g>,
    );
  }

  // расчёты (5.3.7): зоны обзора, освещённость — над помещениями, под предметами
  if (mode === "place" && Object.keys(calcResults).length) {
    world.push(<CalcWorld key="calc" results={calcResults} px={px} />);
    overlay.push(...calcLabels(calcResults, toScreen, view.scale));
  }

  // подписи, не попавшие ни в одно помещение
  const placed = new Set(shapes.flatMap((r) => ("labels" in r ? r.labels : [r.label])));
  for (const r of plan.rooms) {
    if (placed.has(r.id)) continue;
    const at = toScreen([r.x, r.y]);
    overlay.push(
      <g key={`lost${r.id}`} transform={`translate(${at[0]} ${at[1]})`} style={{ pointerEvents: "none" }}>
        <circle r={4} fill="var(--bad)" />
        <text y={-7} textAnchor="middle" fontSize={12} fill="var(--bad)">
          {r.number || r.name || "подпись"}
        </text>
      </g>,
    );
  }

  // колонны, лестницы, лифты
  for (const c of plan.columns) {
    const sel = isSelected(selection, "column", c.id);
    world.push(
      c.round ? (
        <ellipse key={c.id} cx={c.x} cy={c.y} rx={c.w / 2} ry={c.d / 2} fill="var(--ink-2)" stroke={sel ? "var(--accent)" : "none"} strokeWidth={3 * px} />
      ) : (
        <path key={c.id} d={toPath(rect(c.x, c.y, c.w, c.d, c.angle))} fill="var(--ink-2)" stroke={sel ? "var(--accent)" : "none"} strokeWidth={3 * px} />
      ),
    );
  }
  for (const st of plan.stairs) world.push(<StairShape key={st.id} stair={st} px={px} selected={isSelected(selection, "stair", st.id)} />);
  for (const l of lifts) {
    if (!l.floor_ids.includes(floorId)) continue;
    world.push(<LiftShape key={l.id} lift={l} px={px} stops={l.stop_ids.includes(floorId)} selected={isSelected(selection, "lift", l.id)} />);
  }

  // стены и проёмы
  const ext = joinExtensions(plan);
  for (const w of plan.walls) {
    const line = centerline(plan, w);
    if (line.length < 2) continue;
    const length = polylineLength(line);
    const ops = plan.openings.filter((o) => o.wall === w.id).sort((a, b) => a.at - b.at);
    const pieces: [number, number][] = [];
    let cursorS = 0;
    for (const o of ops) {
      const s0 = Math.max(0, o.at - o.width / 2);
      if (s0 > cursorS) pieces.push([cursorS, s0]);
      cursorS = Math.max(cursorS, Math.min(length, o.at + o.width / 2));
    }
    if (cursorS < length) pieces.push([cursorS, length]);
    const sel = isSelected(selection, "wall", w.id);
    const fill = w.kind === "bearing" ? "var(--ink)" : "var(--ink-3)";
    for (const [k, [a, b]] of pieces.entries()) {
      const piece = extend(slice(line, a, b), a === 0 ? (ext.get(w.a) ?? 0) : 0, b === length ? (ext.get(w.b) ?? 0) : 0);
      world.push(<path key={`${w.id}:${k}`} d={toPath(band(piece, w.thickness))} fill={sel ? "var(--accent)" : fill} />);
    }
    for (const o of ops) world.push(<OpeningShape key={o.id} opening={o} wall={w} line={line} px={px} selected={isSelected(selection, "opening", o.id)} />);
  }

  // предметы (5.3.2); в «Строительстве» — бледно
  if (cat) {
    const contents = new Map<string, number>();
    for (const it of items) if (it.parent_id) contents.set(it.parent_id, (contents.get(it.parent_id) ?? 0) + 1);
    for (const it of items) {
      if (it.parent_id) continue;
      const t = cat.types.get(it.type_id);
      if (t?.layer_id && hiddenLayers.includes(t.layer_id)) continue;
      world.push(
        <ItemShape
          key={`i${it.id}`}
          item={it}
          type={t}
          color={layerColor(cat.layers, t)}
          px={px}
          selected={isSelected(selection, "item", it.id)}
          warn={mode === "place" && warnings.has(it.id)}
          pale={mode === "build" || (!!t?.layer_id && lockedLayers.includes(t.layer_id)) || (onlyBroken && !BROKEN.has(unitStates[it.unit_id ?? ""] ?? ""))}
          contents={contents.get(it.id) ?? 0}
          unit={it.unit_id ? (unitStates[it.unit_id] ?? "in_use") : undefined}
        />,
      );
      if (it.label && mode === "place") {
        const at = toScreen([it.x ?? 0, it.y ?? 0]);
        overlay.push(
          <text key={`il${it.id}`} x={at[0]} y={at[1] + 4} textAnchor="middle" fontSize={11} fill="var(--ink)" stroke="var(--surface)" strokeWidth={3} paintOrder="stroke" style={{ pointerEvents: "none" }}>
            {it.label}
          </text>,
        );
      }
    }
    if (mode === "place") {
      const handle = rotateHandle();
      if (handle) overlay.push(<circle key="rot" cx={handle.at[0]} cy={handle.at[1]} r={7} fill="var(--surface)" stroke="var(--accent)" strokeWidth={2} style={{ cursor: "grab" }}><title>Повернуть (шаг 15°, Alt — свободно)</title></circle>);
      if (gaps.length) overlay.push(<GapLines key="gaps" gaps={gaps} toScreen={toScreen} />);
      const sel = selection.length === 1 ? items.find((i) => i.id === selection[0]!.id) : null;
      if (ghosts.length && sel) world.push(<Ghosts key="ghosts" points={ghosts} item={sel} type={cat.types.get(sel.type_id)} px={px} />);
    }
  }

  // узлы выделенных стен
  if (!readOnly)
    for (const s of selection) {
      if (s.kind !== "wall") continue;
      const w = plan.walls.find((x) => x.id === s.id);
      for (const n of w ? [w.a, w.b] : []) {
        const at = toScreen(plan.nodes[n]!);
        overlay.push(<rect key={`h${s.id}${n}`} x={at[0] - 5} y={at[1] - 5} width={10} height={10} fill="var(--surface)" stroke="var(--accent)" strokeWidth={2} />);
      }
    }

  // замечания проверки
  if (!readOnly)
    for (const [i, issue] of (check?.issues ?? []).entries()) {
      const at = toScreen([issue.x, issue.y]);
      overlay.push(
        <g key={`issue${i}`} transform={`translate(${at[0]} ${at[1]})`}>
          <circle r={9} fill="none" stroke={issue.auto ? "var(--warn)" : "var(--bad)"} strokeWidth={2} />
          <title>{issue.message}</title>
        </g>,
      );
    }

  // начатое построение
  if (cursor && !readOnly && tool !== "select") {
    const c = toScreen(cursor.p);
    const last = chain[chain.length - 1];
    if ((tool === "wall" || tool === "stair") && last) {
      if (tool === "wall") world.push(<path key="ghost" d={toPath(band([last, cursor.p], wallDefaults.thickness))} fill="var(--accent)" opacity={0.4} />);
      else world.push(<line key="ghost" x1={last[0]} y1={last[1]} x2={cursor.p[0]} y2={cursor.p[1]} stroke="var(--accent)" strokeWidth={2 * px} />);
      const mid = toScreen([(last[0] + cursor.p[0]) / 2, (last[1] + cursor.p[1]) / 2]);
      overlay.push(<Tag key="len" x={mid[0]} y={mid[1] - 14} text={`${formatM(dist(last, cursor.p))} м`} />);
    }
    if (tool === "arc" && chain.length) {
      const pts = chain.length === 2 ? centerlinePts(chain[0]!, chain[1]!, bulgeFor(chain[0]!, chain[1]!, cursor.p)) : [chain[0]!, cursor.p];
      world.push(<path key="ghost" d={toPath(band(pts, wallDefaults.thickness), true)} fill="var(--accent)" opacity={0.4} />);
    }
    if (OPENING_TOOLS.includes(tool as OpeningKind)) {
      const hit = wallAt(plan, cursor.p, 10 / view.scale);
      if (hit) {
        const width = Math.min(OPENING_DEFAULTS[tool as OpeningKind].width, hit.length);
        const at = Math.min(Math.max(hit.s, width / 2), hit.length - width / 2);
        const line = centerline(plan, hit.wall);
        world.push(<path key="ghost" d={toPath(band(slice(line, at - width / 2, at + width / 2), hit.wall.thickness + 40))} fill="var(--accent)" opacity={0.5} />);
      }
    }
    if (tool === "measure" && measure.length === 1) {
      world.push(<line key="m" x1={measure[0]![0]} y1={measure[0]![1]} x2={cursor.p[0]} y2={cursor.p[1]} stroke="var(--accent)" strokeWidth={2 * px} strokeDasharray={`${6 * px} ${4 * px}`} />);
      overlay.push(<Tag key="mlen" x={c[0]} y={c[1] - 18} text={`${formatM(dist(measure[0]!, cursor.p))} м`} />);
    }
    if (tool === "calibrate" && chain.length === 1) {
      world.push(<line key="cal" x1={chain[0]![0]} y1={chain[0]![1]} x2={cursor.p[0]} y2={cursor.p[1]} stroke="var(--bad)" strokeWidth={2 * px} />);
    }
    overlay.push(
      <g key="cursor" transform={`translate(${c[0]} ${c[1]})`} style={{ pointerEvents: "none" }}>
        {cursor.kind === "node" ? <rect x={-6} y={-6} width={12} height={12} fill="none" stroke="var(--accent)" strokeWidth={2} /> : cursor.kind === "middle" ? <path d="M0,-7L7,6L-7,6Z" fill="none" stroke="var(--accent)" strokeWidth={2} /> : <path d="M-7,0H7M0,-7V7" stroke="var(--accent)" strokeWidth={1.5} />}
      </g>,
    );
  }
  if (measure.length === 2) {
    world.push(<line key="m" x1={measure[0]![0]} y1={measure[0]![1]} x2={measure[1]![0]} y2={measure[1]![1]} stroke="var(--accent)" strokeWidth={2 * px} />);
    const m = toScreen([(measure[0]![0] + measure[1]![0]) / 2, (measure[0]![1] + measure[1]![1]) / 2]);
    overlay.push(<Tag key="mres" x={m[0]} y={m[1] - 14} text={`${formatM(dist(measure[0]!, measure[1]!))} м`} />);
  }
  if (box) {
    const [a, b] = [toScreen(box[0]), toScreen(box[1])];
    overlay.push(<rect key="box" x={Math.min(a[0], b[0])} y={Math.min(a[1], b[1])} width={Math.abs(a[0] - b[0])} height={Math.abs(a[1] - b[1])} fill="var(--accent-soft)" fillOpacity={0.4} stroke="var(--accent)" strokeDasharray="4 3" />);
  }
  if (walker) {
    const at = toScreen(walker.p);
    overlay.push(
      <g key="walker" transform={`translate(${at[0]} ${at[1]}) rotate(${-walker.angle})`} style={{ pointerEvents: "none" }}>
        <path d="M0,0L26,-12A28,28 0 0 1 26,12Z" fill="var(--accent)" opacity={0.35} />
        <circle r={7} fill="var(--accent)" stroke="white" strokeWidth={2} />
      </g>,
    );
  }

  const cursorStyle = mode === "place" ? (placing ? "copy" : "default") : readOnly || tool === "select" ? (drag.current?.kind === "pan" ? "grabbing" : "default") : "crosshair";

  // перетаскивание типа из каталога слева — или единицы из «Неразмещённых» (С12)
  const onDrop = (e: React.DragEvent) => {
    const typeId = e.dataTransfer.getData("application/x-item-type");
    if (!typeId || !cat || readOnly) return;
    e.preventDefault();
    const t = cat.types.get(typeId);
    const unitId = e.dataTransfer.getData("application/x-unit");
    const unit = unitId ? { id: unitId, model_id: store.state.unitModels[unitId] ?? null } : undefined;
    if (t) placeAt(store, cat, t, toWorld(e.clientX, e.clientY), faces, floorHeight, e.altKey, unit);
  };
  return (
    <svg
      ref={svg}
      className="block h-full w-full touch-none bg-surface select-none"
      style={{ cursor: cursorStyle }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onPointerLeave={() => setCursor(null)}
      onWheel={onWheel}
      onDoubleClick={onDoubleClick}
      onContextMenu={(e) => e.preventDefault()}
      onDragOver={(e) => {
        if (mode === "place" && !readOnly && e.dataTransfer.types.includes("application/x-item-type")) e.preventDefault();
      }}
      onDrop={onDrop}
      role="img"
      aria-label="План этажа"
    >
      <g transform={`translate(${view.x} ${view.y}) scale(${view.scale} ${-view.scale})`}>{world}</g>
      <g className="font-sans">{overlay}</g>
      <ScaleBar scale={view.scale} height={size.h} />
    </svg>
  );
}

function centerlinePts(a: Pt, b: Pt, bulge: number): Pt[] {
  return centerline({ nodes: { a, b }, walls: [], openings: [], columns: [], stairs: [], rooms: [], underlay: null }, { id: "", a: "a", b: "b", thickness: 0, kind: "partition", bulge });
}

// bulge дуги через a и b, проходящей через p (стрелка дуги — расстояние p от хорды)
export function bulgeFor(a: Pt, b: Pt, p: Pt): number {
  const chord = dist(a, b);
  if (chord < 1) return 0;
  const dx = (b[0] - a[0]) / chord;
  const dy = (b[1] - a[1]) / chord;
  // справа от a → b — положительная стрелка
  const sagitta = (p[0] - a[0]) * dy - (p[1] - a[1]) * dx;
  return Math.max(-1, Math.min(1, (2 * sagitta) / chord));
}

function OpeningShape({ opening: o, wall, line, px, selected }: { opening: Opening; wall: Wall; line: Pt[]; px: number; selected: boolean }) {
  const { p: c, dir } = pointAt(line, o.at);
  const n: Pt = [-dir[1], dir[0]]; // влево от a → b
  const half = o.width / 2;
  const t = wall.thickness / 2;
  const color = selected ? "var(--accent)" : "var(--ink)";
  const a = add(c, [-dir[0] * half, -dir[1] * half]);
  const b = add(c, [dir[0] * half, dir[1] * half]);
  const off = (p: Pt, k: number): Pt => [p[0] + n[0] * k, p[1] + n[1] * k];
  const lines: ReactNode[] = [
    <line key="j1" x1={off(a, t)[0]} y1={off(a, t)[1]} x2={off(a, -t)[0]} y2={off(a, -t)[1]} stroke={color} strokeWidth={1.5 * px} />,
    <line key="j2" x1={off(b, t)[0]} y1={off(b, t)[1]} x2={off(b, -t)[0]} y2={off(b, -t)[1]} stroke={color} strokeWidth={1.5 * px} />,
  ];
  if (o.kind === "window" || o.kind === "glazing") {
    const ks = o.kind === "window" ? [-t / 3, t / 3] : [-t / 2, 0, t / 2];
    for (const k of ks) lines.push(<line key={`w${k}`} x1={off(a, k)[0]} y1={off(a, k)[1]} x2={off(b, k)[0]} y2={off(b, k)[1]} stroke={color} strokeWidth={1.2 * px} />);
  }
  if (o.kind === "passage") lines.push(<line key="p" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={color} strokeWidth={px} strokeDasharray={`${5 * px} ${4 * px}`} />);
  if (o.kind === "door") {
    const hinge = o.hinge === "start" ? a : b;
    const free = o.hinge === "start" ? b : a;
    const k = (o.side === "left" ? 1 : -1) * (t);
    const h = off(hinge, k);
    const leaf = off(hinge, k + (o.side === "left" ? 1 : -1) * o.width);
    const f = off(free, k);
    const sweep = (o.hinge === "start") === (o.side === "left") ? 0 : 1;
    lines.push(<line key="leaf" x1={h[0]} y1={h[1]} x2={leaf[0]} y2={leaf[1]} stroke={color} strokeWidth={2 * px} />);
    lines.push(<path key="swing" d={`M${leaf[0]},${leaf[1]}A${o.width},${o.width} 0 0 ${sweep} ${f[0]},${f[1]}`} fill="none" stroke={color} strokeWidth={px} />);
  }
  if (selected) lines.push(<path key="hl" d={toPath(band([a, b], wall.thickness + 6 * px))} fill="var(--accent)" opacity={0.25} />);
  return <g>{lines}</g>;
}

function StairShape({ stair: s, px, selected }: { stair: { x: number; y: number; width: number; length: number; angle: number; steps: number }; px: number; selected: boolean }) {
  const toW = (u: number, v: number) => add([s.x, s.y], rot([u, v], s.angle));
  const outline = [toW(0, -s.width / 2), toW(s.length, -s.width / 2), toW(s.length, s.width / 2), toW(0, s.width / 2)];
  const steps: string[] = [];
  for (let i = 1; i < s.steps; i++) {
    const u = (s.length * i) / s.steps;
    const [p, q] = [toW(u, -s.width / 2), toW(u, s.width / 2)];
    steps.push(`M${p[0]},${p[1]}L${q[0]},${q[1]}`);
  }
  const [a, b] = [toW(s.length * 0.1, 0), toW(s.length * 0.9, 0)];
  const [h1, h2] = [toW(s.length * 0.9 - 250, 150), toW(s.length * 0.9 - 250, -150)];
  const color = selected ? "var(--accent)" : "var(--ink-2)";
  return (
    <g>
      <path d={toPath(outline)} fill="var(--surface)" stroke={color} strokeWidth={1.5 * px} />
      <path d={steps.join("")} stroke={color} strokeWidth={px} />
      <path d={`M${a[0]},${a[1]}L${b[0]},${b[1]}M${h1[0]},${h1[1]}L${b[0]},${b[1]}L${h2[0]},${h2[1]}`} stroke={color} strokeWidth={1.5 * px} fill="none" />
    </g>
  );
}

function LiftShape({ lift: l, px, stops, selected }: { lift: Lift; px: number; stops: boolean; selected: boolean }) {
  const r = rect(l.x, l.y, l.w, l.d, l.angle);
  const color = selected ? "var(--accent)" : "var(--ink-2)";
  const sides: [Pt, Pt][] = [[r[3]!, r[2]!], [r[2]!, r[1]!], [r[1]!, r[0]!], [r[0]!, r[3]!]];
  const [p, q] = sides[l.door_side] ?? sides[0]!;
  const mid: Pt = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
  const dir: Pt = [(q[0] - p[0]) / dist(p, q), (q[1] - p[1]) / dist(p, q)];
  const half = Math.min(450, dist(p, q) / 3);
  return (
    <g>
      <path d={toPath(r)} fill="var(--surface-2)" stroke={color} strokeWidth={2 * px} />
      <path d={`M${r[0]![0]},${r[0]![1]}L${r[2]![0]},${r[2]![1]}M${r[1]![0]},${r[1]![1]}L${r[3]![0]},${r[3]![1]}`} stroke={color} strokeWidth={px} />
      {stops && <line x1={mid[0] - dir[0] * half} y1={mid[1] - dir[1] * half} x2={mid[0] + dir[0] * half} y2={mid[1] + dir[1] * half} stroke="var(--accent)" strokeWidth={5 * px} />}
    </g>
  );
}

function Tag({ x, y, text }: { x: number; y: number; text: string }) {
  const w = text.length * 7 + 12;
  return (
    <g transform={`translate(${x} ${y})`} style={{ pointerEvents: "none" }}>
      <rect x={-w / 2} y={-11} width={w} height={20} rx={4} fill="var(--ink)" />
      <text textAnchor="middle" y={4} fontSize={12} fill="var(--surface)" className="font-mono">
        {text}
      </text>
    </g>
  );
}

function ScaleBar({ scale, height }: { scale: number; height: number }) {
  const options = [100, 200, 500, 1000, 2000, 5000, 10000, 20000];
  const mm = options.find((o) => o * scale >= 60) ?? 20000;
  const w = mm * scale;
  return (
    <g transform={`translate(16 ${height - 20})`} style={{ pointerEvents: "none" }}>
      <path d={`M0,-6V0H${w}V-6`} fill="none" stroke="var(--ink-2)" strokeWidth={1.5} />
      <text x={w + 6} y={0} fontSize={11} fill="var(--ink-2)">
        {mm >= 1000 ? `${mm / 1000} м` : `${mm} мм`}
      </text>
    </g>
  );
}
