import { useQueries } from "@tanstack/react-query";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Footprints, Orbit as OrbitIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { get } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button } from "@/ui/button";
import { SLAB, blockers, buildFloor, liftGeometry, type Blocker } from "./build3d";
import type { Item } from "./items";
import { Items3D } from "./items3d";
import type { Catalog } from "./placement";
import { CalcLines3D } from "./calc";
import { useEditor, type EditorStore } from "./store";
import { pointInPolygon, projectOnSegment, rect, rot, type FloorInfo, type Lift, type Plan, type PlanView, type Pt } from "./plan";

// 3D-вид (5.1.7): обзор и прогулка от первого лица. Один этаж или всё здание; этажи выше
// выбранного скрываются.

const M = 0.001;
const EYE = 1600; // высота глаз, мм
const RADIUS = 250; // «толщина» идущего, мм
const SPEED = 1400; // мм/с

interface Props {
  buildingId: string;
  floorId: string;
  floors: FloorInfo[];
  plan: Plan; // текущий этаж — с несохранёнными правками
  lifts: Lift[];
  onWalker: (w: { p: Pt; angle: number } | null) => void;
  walkRequest: { p: Pt; n: number } | null;
  store: EditorStore;
  cat: Catalog | null;
  readOnly: boolean;
}

interface FloorData {
  floor: FloorInfo;
  plan: Plan;
  slabs: Pt[][];
}

export default function View3D({ floorId, floors, plan, lifts, onWalker, walkRequest, store, cat, readOnly }: Props) {
  const others = useQueries({
    queries: floors.map((f) => ({ queryKey: ["plan", f.id], queryFn: () => get<PlanView>(`/api/floors/${f.id}/plan`), staleTime: 30_000 })),
  });
  const otherItems = useQueries({
    queries: floors.map((f) => ({ queryKey: ["items", f.id], queryFn: () => get<{ items: Item[] }>(`/api/floors/${f.id}/items`), staleTime: 30_000, enabled: f.id !== floorId })),
  });
  const items = useEditor(store, (s) => s.items);
  const hidden = useEditor(store, (s) => s.hiddenLayers);
  const selection = useEditor(store, (s) => s.selection);
  const editMode = useEditor(store, (s) => s.mode);
  const selected = useMemo(() => new Set(selection.filter((x) => x.kind === "item").map((x) => x.id)), [selection]);
  const [scope, setScope] = useState<"floor" | "below">("below");
  const [mode, setMode] = useState<"orbit" | "walk">(walkRequest ? "walk" : "orbit");
  const [startAt, setStartAt] = useState<Pt | null>(walkRequest?.p ?? null);
  // «Пройтись отсюда» в свойствах помещения
  useEffect(() => {
    if (!walkRequest) return;
    setStartAt(walkRequest.p);
    setMode("walk");
  }, [walkRequest]);
  const current = floors.find((f) => f.id === floorId)!;

  const data: FloorData[] = floors.map((f, i) => {
    const view = others[i]?.data;
    if (f.id === floorId) return { floor: f, plan, slabs: view?.slabs ?? [] };
    return { floor: f, plan: view?.plan ?? { nodes: {}, walls: [], openings: [], columns: [], stairs: [], rooms: [], underlay: null }, slabs: view?.slabs ?? [] };
  });
  const shown = data.filter((d) => (scope === "floor" ? d.floor.id === floorId : d.floor.position <= current.position));

  useEffect(() => {
    if (mode === "orbit") onWalker(null);
  }, [mode, onWalker]);

  return (
    <div className="relative h-full w-full bg-[#dfe5ec] dark:bg-[#1b2129]">
      <Canvas shadows={false} camera={{ fov: 55, near: 0.05, far: 2000, position: [30, 30, 30] }} dpr={[1, 2]}>
        <ambientLight intensity={0.7} />
        <directionalLight position={[40, 80, 30]} intensity={1.4} />
        <hemisphereLight args={["#ffffff", "#8a8f99", 0.4]} />
        {shown.map((d, i) => (
          <FloorMesh key={d.floor.id} data={d} next={floors.find((f) => f.position === d.floor.position + 1) ?? null}>
            {cat &&
              (d.floor.id === floorId ? (
                <>
                  <Items3D items={items} cat={cat} hidden={hidden} selected={selected} interactive={!readOnly && editMode === "place" && mode === "orbit"} store={store} plan={plan} />
                  {editMode === "place" && <CalcLines3D store={store} />}
                </>
              ) : (
                <Items3D items={otherItems[floors.indexOf(d.floor)]?.data?.items ?? []} cat={cat} hidden={hidden} selected={selected} interactive={false} key={i} />
              ))}
          </FloorMesh>
        ))}
        {lifts.map((l) => (
          <LiftMesh key={l.id} lift={l} floors={floors} upTo={scope === "floor" ? current : current} onlyFloor={scope === "floor" ? current : null} />
        ))}
        {mode === "orbit" ? <Orbit data={shown} /> : <Walk key={startAt ? startAt.join() : "start"} floors={data} start={current} at={startAt} lifts={lifts} onWalker={onWalker} />}
      </Canvas>
      <div className="absolute top-3 left-3 flex flex-wrap gap-2">
        <div role="radiogroup" aria-label="Как смотреть" className="flex rounded-lg border border-line-strong bg-surface p-0.5 shadow-sm">
          <button type="button" role="radio" aria-checked={mode === "orbit"} onClick={() => setMode("orbit")} className={cn("flex h-8 cursor-pointer items-center gap-1.5 rounded-md border-0 px-3 text-[13px] max-md:h-10", mode === "orbit" ? "bg-accent text-white" : "bg-transparent text-ink")}>
            <OrbitIcon className="size-4" /> Обзор
          </button>
          <button type="button" role="radio" aria-checked={mode === "walk"} onClick={() => setMode("walk")} className={cn("flex h-8 cursor-pointer items-center gap-1.5 rounded-md border-0 px-3 text-[13px] max-md:h-10", mode === "walk" ? "bg-accent text-white" : "bg-transparent text-ink")}>
            <Footprints className="size-4" /> Прогулка
          </button>
        </div>
        {mode === "orbit" && (
          <div role="radiogroup" aria-label="Что показывать" className="flex rounded-lg border border-line-strong bg-surface p-0.5 shadow-sm">
            {([["floor", "Этаж"], ["below", "Здание до этажа"]] as const).map(([v, t]) => (
              <button key={v} type="button" role="radio" aria-checked={scope === v} onClick={() => setScope(v)} className={cn("h-8 cursor-pointer rounded-md border-0 px-3 text-[13px] max-md:h-10", scope === v ? "bg-accent text-white" : "bg-transparent text-ink")}>
                {t}
              </button>
            ))}
          </div>
        )}
      </div>
      {mode === "walk" && <WalkHelp />}
    </div>
  );
}

const materials = {
  bearing: new THREE.MeshStandardMaterial({ color: "#c9ced6", roughness: 0.9 }),
  partition: new THREE.MeshStandardMaterial({ color: "#eceef1", roughness: 0.9 }),
  glass: new THREE.MeshStandardMaterial({ color: "#8fc3ef", transparent: true, opacity: 0.35, roughness: 0.1 }),
  slab: new THREE.MeshStandardMaterial({ color: "#b8bec7", roughness: 1 }),
  columns: new THREE.MeshStandardMaterial({ color: "#9aa2ad", roughness: 0.8 }),
  stairs: new THREE.MeshStandardMaterial({ color: "#d6c7ae", roughness: 0.9 }),
  lift: new THREE.MeshStandardMaterial({ color: "#5b8ff0", transparent: true, opacity: 0.25 }),
};

function FloorMesh({ data, next, children }: { data: FloorData; next: FloorInfo | null; children?: React.ReactNode }) {
  const geometry = useMemo(
    () => buildFloor(data.plan, data.floor.height, data.slabs, next ? next.elevation - data.floor.elevation : null),
    [data.plan, data.floor.height, data.slabs, next, data.floor.elevation],
  );
  useEffect(() => () => Object.values(geometry).forEach((g) => g?.dispose()), [geometry]);
  return (
    <group position={[0, data.floor.elevation * M, 0]}>
      {(Object.keys(materials) as (keyof typeof materials)[]).map((k) => {
        const g = k !== "lift" ? geometry[k] : null;
        return g ? <mesh key={k} geometry={g} material={materials[k]} /> : null;
      })}
      {children}
    </group>
  );
}

function LiftMesh({ lift, floors, onlyFloor }: { lift: Lift; floors: FloorInfo[]; upTo: FloorInfo; onlyFloor: FloorInfo | null }) {
  const spanned = floors.filter((f) => lift.floor_ids.includes(f.id) && (!onlyFloor || f.id === onlyFloor.id));
  const geometry = useMemo(() => {
    if (!spanned.length) return null;
    const bottom = Math.min(...spanned.map((f) => f.elevation)) - SLAB * 1000;
    const top = Math.max(...spanned.map((f) => f.elevation + f.height));
    return liftGeometry(lift, bottom, top);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lift, spanned.map((f) => f.id).join()]);
  return geometry ? <mesh geometry={geometry} material={materials.lift} /> : null;
}

function Orbit({ data }: { data: FloorData[] }) {
  const { camera, size } = useThree();
  const controls = useRef<React.ComponentRef<typeof OrbitControls>>(null);
  const fitted = useRef(false);
  useEffect(() => {
    // панель ещё не получила размер (вид «оба» раскладывается после первого кадра)
    if (fitted.current || size.width < 20 || size.height < 20) return;
    const pts = data.flatMap((d) => Object.values(d.plan.nodes));
    if (!pts.length) return;
    fitted.current = true;
    const xs = pts.map((p) => p[0] * M);
    const ys = pts.map((p) => -p[1] * M);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cz = (Math.min(...ys) + Math.max(...ys)) / 2;
    const w = Math.max(...xs) - Math.min(...xs);
    const d = Math.max(...ys) - Math.min(...ys);
    const top = Math.max(...data.map((f) => (f.floor.elevation + f.floor.height) * M));
    // вся коробка здания в кадре
    const radius = Math.max(Math.hypot(w, d, top) / 2, 5);
    // по меньшему из углов обзора: в узкой панели (вид «оба») — по ширине
    const vfov = (55 * Math.PI) / 180;
    const aspect = size.width / Math.max(size.height, 1) || 1;
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
    const distance = radius / Math.sin(Math.min(vfov, hfov) / 2);
    const dir = new THREE.Vector3(0.55, 0.65, 0.75).normalize();
    camera.position.set(cx + dir.x * distance, top / 2 + dir.y * distance, cz + dir.z * distance);
    controls.current?.target.set(cx, top / 2, cz);
    controls.current?.update();
  }, [data, camera, size]);
  return <OrbitControls ref={controls} makeDefault enableDamping />;
}

// ---------------------------------------------------------------- прогулка

function Walk({ floors, start, at, lifts, onWalker }: { floors: FloorData[]; start: FloorInfo; at: Pt | null; lifts: Lift[]; onWalker: Props["onWalker"] }) {
  const { camera, gl } = useThree();
  const state = useRef({ floor: start.position, p: [0, 0] as Pt, height: start.elevation + EYE, yaw: 0, pitch: 0 });
  const keys = useRef(new Set<string>());
  const sorted = useMemo(() => [...floors].sort((a, b) => a.floor.position - b.floor.position), [floors]);
  const walls = useMemo(() => new Map(sorted.map((f) => [f.floor.position, blockers(f.plan)])), [sorted]);
  const lastReport = useRef(0);
  const [liftChoice, setLiftChoice] = useState<Lift | null>(null);

  // начать — с подписи выбранного помещения или с середины этажа
  useEffect(() => {
    const plan = sorted.find((f) => f.floor.id === start.id)?.plan;
    const label = plan?.rooms[0];
    const pts = Object.values(plan?.nodes ?? {});
    const p: Pt = at ?? (label ? [label.x, label.y] : pts.length ? [pts.reduce((s, q) => s + q[0], 0) / pts.length, pts.reduce((s, q) => s + q[1], 0) / pts.length] : [0, 0]);
    state.current = { floor: start.position, p, height: start.elevation + EYE, yaw: 0, pitch: 0 };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start.id]);

  useEffect(() => {
    const el = gl.domElement;
    const down = (e: KeyboardEvent) => keys.current.add(e.code);
    const up = (e: KeyboardEvent) => keys.current.delete(e.code);
    let dragging = false;
    let last: [number, number] = [0, 0];
    const pd = (e: PointerEvent) => {
      if (e.pointerType === "mouse" && document.pointerLockElement !== el) void el.requestPointerLock?.();
      dragging = true;
      last = [e.clientX, e.clientY];
    };
    const pm = (e: PointerEvent) => {
      const locked = document.pointerLockElement === el;
      if (!locked && !dragging) return;
      const dx = locked ? e.movementX : e.clientX - last[0];
      const dy = locked ? e.movementY : e.clientY - last[1];
      last = [e.clientX, e.clientY];
      state.current.yaw -= dx * 0.003;
      state.current.pitch = Math.max(-1.3, Math.min(1.3, state.current.pitch - dy * 0.003));
    };
    const pu = () => {
      dragging = false;
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    el.addEventListener("pointerdown", pd);
    window.addEventListener("pointermove", pm);
    window.addEventListener("pointerup", pu);
    const joy = (e: Event) => {
      const [x, y] = (e as CustomEvent<[number, number]>).detail;
      joystick.current = [x, y];
    };
    window.addEventListener("walk:joystick", joy);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      el.removeEventListener("pointerdown", pd);
      window.removeEventListener("pointermove", pm);
      window.removeEventListener("pointerup", pu);
      window.removeEventListener("walk:joystick", joy);
      if (document.pointerLockElement === el) document.exitPointerLock();
    };
  }, [gl]);
  const joystick = useRef<[number, number]>([0, 0]);

  const blocked = (p: Pt, list: Blocker[]) => list.some((b) => projectOnSegment(p, b.a, b.b).d < b.half + RADIUS);

  useFrame((_, dt) => {
    const s = state.current;
    const k = keys.current;
    let forward = (k.has("KeyW") || k.has("ArrowUp") ? 1 : 0) - (k.has("KeyS") || k.has("ArrowDown") ? 1 : 0) - joystick.current[1];
    let strafe = (k.has("KeyD") || k.has("ArrowRight") ? 1 : 0) - (k.has("KeyA") || k.has("ArrowLeft") ? 1 : 0) + joystick.current[0];
    const len = Math.hypot(forward, strafe);
    if (len > 1) {
      forward /= len;
      strafe /= len;
    }
    const step = SPEED * Math.min(dt, 0.1) * (k.has("ShiftLeft") ? 2 : 1);
    const dir: Pt = [-Math.sin(s.yaw), Math.cos(s.yaw)]; // в координатах плана: yaw = 0 — на +Y
    const right: Pt = [dir[1], -dir[0]];
    const move: Pt = [(dir[0] * forward + right[0] * strafe) * step, (dir[1] * forward + right[1] * strafe) * step];
    const here = sorted.find((f) => f.floor.position === s.floor);
    const list = walls.get(s.floor) ?? [];
    if (move[0] || move[1]) {
      const nx: Pt = [s.p[0] + move[0], s.p[1]];
      if (!blocked(nx, list)) s.p = nx;
      const ny: Pt = [s.p[0], s.p[1] + move[1]];
      if (!blocked(ny, list)) s.p = ny;
    }
    // лестницы: свои ведут вверх, лестницы этажа ниже — вниз
    let floorY = here ? here.floor.elevation : 0;
    const below = sorted.find((f) => f.floor.position === s.floor - 1);
    const above = sorted.find((f) => f.floor.position === s.floor + 1);
    const onStair = (f: FloorData | undefined, to: FloorData | undefined) => {
      if (!f || !to) return null;
      for (const st of f.plan.stairs) {
        const local = rot([s.p[0] - st.x, s.p[1] - st.y], -st.angle);
        if (local[0] >= 0 && local[0] <= st.length && Math.abs(local[1]) <= st.width / 2) return local[0] / st.length;
      }
      return null;
    };
    const up = onStair(here, above);
    const down = onStair(below, here);
    if (up !== null && here && above) {
      floorY = here.floor.elevation + (above.floor.elevation - here.floor.elevation) * up;
      if (up > 0.95) s.floor = above.floor.position;
    } else if (down !== null && below && here) {
      floorY = below.floor.elevation + (here.floor.elevation - below.floor.elevation) * down;
      if (down < 0.05) s.floor = below.floor.position;
    }
    s.height += (floorY + EYE - s.height) * Math.min(1, dt * 10);
    camera.position.set(s.p[0] * M, s.height * M, -s.p[1] * M);
    camera.rotation.set(s.pitch, s.yaw, 0, "YXZ");

    // лифт: внутри шахты на этаже с остановкой — выбор этажа
    const inLift = lifts.find((l) => here && l.stop_ids.includes(here.floor.id) && pointInPolygon(s.p, rect(l.x, l.y, l.w, l.d, l.angle))) ?? null;
    if ((inLift?.id ?? null) !== (liftChoice?.id ?? null)) setLiftChoice(inLift);

    const now = performance.now();
    if (now - lastReport.current > 100) {
      lastReport.current = now;
      onWalker(here && here.floor.id === start.id ? { p: s.p, angle: (s.yaw * 180) / Math.PI + 90 } : null);
    }
  });

  useEffect(() => {
    const go = (e: Event) => {
      const floorId = (e as CustomEvent<string>).detail;
      const target = sorted.find((f) => f.floor.id === floorId);
      if (target) {
        state.current.floor = target.floor.position;
        state.current.height = target.floor.elevation + EYE;
      }
    };
    window.addEventListener("walk:lift", go);
    return () => window.removeEventListener("walk:lift", go);
  }, [sorted]);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent("walk:lift-choice", { detail: liftChoice ? { lift: liftChoice, floors: sorted.filter((f) => liftChoice.stop_ids.includes(f.floor.id)).map((f) => f.floor) } : null }));
  }, [liftChoice, sorted]);
  return null;
}

function WalkHelp() {
  const [choice, setChoice] = useState<{ lift: Lift; floors: FloorInfo[] } | null>(null);
  useEffect(() => {
    const on = (e: Event) => setChoice((e as CustomEvent).detail);
    window.addEventListener("walk:lift-choice", on);
    return () => window.removeEventListener("walk:lift-choice", on);
  }, []);
  return (
    <>
      <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-lg bg-black/55 px-3 py-1.5 text-[12px] text-white max-md:hidden">
        W A S D или стрелки — идти, мышь — смотреть (щелчок захватывает мышь, Esc — отпустить), Shift — быстрее
      </div>
      {choice && (
        <div className="absolute top-14 left-3 flex flex-col gap-1.5 rounded-xl border border-line bg-surface p-3 shadow-lg">
          <div className="text-[13px] font-medium">Лифт{choice.lift.name ? ` ${choice.lift.name}` : ""}: на какой этаж?</div>
          <div className="flex flex-wrap gap-1.5">
            {choice.floors.map((f) => (
              <Button key={f.id} size="sm" onClick={() => window.dispatchEvent(new CustomEvent("walk:lift", { detail: f.id }))}>
                {f.name}
              </Button>
            ))}
          </div>
        </div>
      )}
      <Joystick />
    </>
  );
}

// Джойстик на экране телефона и планшета
function Joystick() {
  const [knob, setKnob] = useState<[number, number] | null>(null);
  const base = useRef<HTMLDivElement>(null);
  const R = 48;
  const set = (x: number, y: number) => {
    const d = Math.hypot(x, y);
    const k = d > R ? R / d : 1;
    setKnob([x * k, y * k]);
    window.dispatchEvent(new CustomEvent("walk:joystick", { detail: [(x * k) / R, (y * k) / R] }));
  };
  const at = (e: React.PointerEvent) => {
    const r = base.current!.getBoundingClientRect();
    set(e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2);
  };
  return (
    <div
      ref={base}
      className="absolute bottom-6 left-6 hidden size-28 touch-none rounded-full border-2 border-white/60 bg-black/20 [@media(pointer:coarse)]:block"
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        at(e);
      }}
      onPointerMove={(e) => knob && at(e)}
      onPointerUp={() => {
        setKnob(null);
        window.dispatchEvent(new CustomEvent("walk:joystick", { detail: [0, 0] }));
      }}
      aria-label="Джойстик: идти"
      role="application"
    >
      <div className="absolute top-1/2 left-1/2 size-12 rounded-full bg-white/80" style={{ transform: `translate(calc(-50% + ${knob?.[0] ?? 0}px), calc(-50% + ${knob?.[1] ?? 0}px))` }} />
    </div>
  );
}

