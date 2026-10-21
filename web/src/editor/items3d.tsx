import { useGLTF } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { placeModel, transformOf } from "@/catalog/model3d";
import type { TypeBrief } from "@/catalog/types";
import { normAngle, sizeOf, stickToWall, wallGeometry, type Item } from "./items";
import { draggedType, placeAt, planPlacement, type Catalog } from "./placement";
import type { Plan } from "./plan";
import type { EditorStore } from "./store";

// Предметы в 3D (5.1.7, 5.3.3): 3D-модель типа или фигура по габаритам в цвете слоя.
// Предметы одного типа рисуются одним набором экземпляров — 2 000 предметов этажа идут
// плавно (8.2). Выбор, перемещение по полу (настенные — вдоль стены), поворот: Shift и
// движение мыши (шаг 15°, Alt — свободно). Постановка — как на плане: тип из каталога
// перетаскивается в сцену или выбирается и ставится щелчком; где он встанет, показывает
// полупрозрачный «призрак» с прилипанием к стене.

const M = 0.001;

function matrixOf(item: Item, out = new THREE.Matrix4()) {
  const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), (item.angle * Math.PI) / 180);
  return out.compose(new THREE.Vector3((item.x ?? 0) * M, item.z * M, -(item.y ?? 0) * M), q, new THREE.Vector3(1, 1, 1));
}

interface Group {
  type: TypeBrief | undefined;
  color: string;
  items: Item[];
}

export function Items3D({ items, cat, hidden, selected, interactive, store, plan, floorHeight = 3300 }: {
  items: Item[];
  cat: Catalog;
  hidden: string[];
  selected: Set<string>;
  interactive: boolean;
  store?: EditorStore;
  plan?: Plan;
  floorHeight?: number;
}) {
  const groups = useMemo(() => {
    const out = new Map<string, Group>();
    for (const it of items) {
      if (it.parent_id) continue;
      const t = cat.types.get(it.type_id);
      if (t?.layer_id && hidden.includes(t.layer_id)) continue;
      const g = out.get(it.type_id) ?? { type: t, color: (t?.layer_id && cat.layers.get(t.layer_id)?.color) || "#607D8B", items: [] };
      g.items.push(it);
      out.set(it.type_id, g);
    }
    return [...out.values()];
  }, [items, cat, hidden]);
  const root = useRef<THREE.Group>(null);
  const [ghost, setGhost] = useState<Item | null>(null);
  useDrag(root, interactive ? store : undefined, cat, plan, floorHeight, setGhost);
  return (
    <group ref={root}>
      {ghost && <Ghost item={ghost} type={cat.types.get(ghost.type_id)} color={cat.layers.get(cat.types.get(ghost.type_id)?.layer_id ?? "")?.color ?? "#2f6fde"} />}
      {groups.map((g) =>
        g.type?.model_url ? (
          <Suspense key={g.type.id} fallback={<Boxes group={g} />}>
            <Models group={g} url={g.type.model_url} />
          </Suspense>
        ) : (
          <Boxes key={g.type?.id ?? g.items[0]!.type_id} group={g} />
        ),
      )}
      {items.filter((i) => selected.has(i.id) && !i.parent_id).map((i) => (
        <Highlight key={i.id} item={i} type={cat.types.get(i.type_id)} />
      ))}
    </group>
  );
}

function Boxes({ group }: { group: Group }) {
  const { w, d, h } = sizeOf(group.type);
  const geometry = useMemo(() => new THREE.BoxGeometry(w * M, h * M, d * M).translate(0, (h / 2) * M, 0), [w, d, h]);
  const material = useMemo(() => new THREE.MeshLambertMaterial({ color: group.color }), [group.color]);
  return <Instanced geometry={geometry} material={material} items={group.items} />;
}

function Models({ group, url }: { group: Group; url: string }) {
  const gltf = useGLTF(url);
  const t = group.type!;
  const tr = transformOf(t.model_transform);
  const { w, d, h } = sizeOf(t);
  // модель поворачивается, масштабируется или вписывается в габариты типа, ставится на пол
  const parts = useMemo(() => {
    const root = placeModel(gltf.scene, tr, [w, h, d]);
    const out: { geometry: THREE.BufferGeometry; material: THREE.Material }[] = [];
    root.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      out.push({ geometry: mesh.geometry.clone().applyMatrix4(mesh.matrixWorld), material: Array.isArray(mesh.material) ? mesh.material[0]! : mesh.material });
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gltf, tr.rx, tr.ry, tr.rz, tr.scale, tr.fit, w, h, d]);
  return (
    <>
      {parts.map((p, i) => (
        <Instanced key={i} geometry={p.geometry} material={p.material} items={group.items} />
      ))}
    </>
  );
}

function Instanced({ geometry, material, items }: { geometry: THREE.BufferGeometry; material: THREE.Material; items: Item[] }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const m = new THREE.Matrix4();
    items.forEach((it, i) => mesh.setMatrixAt(i, matrixOf(it, m)));
    mesh.count = items.length;
    mesh.userData.items = items; // какой предмет под лучом — по номеру экземпляра
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [items]);
  // запас по числу экземпляров: при добавлении предметов набор не пересоздаётся каждый раз
  const capacity = Math.max(16, 2 ** Math.ceil(Math.log2(Math.max(items.length, 1))));
  return (
    <instancedMesh
      ref={ref}
      args={[geometry, material, capacity]}
      key={capacity}
    />
  );
}

function Highlight({ item, type }: { item: Item; type: TypeBrief | undefined }) {
  const { w, d, h } = sizeOf(type);
  const geometry = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(w * M + 0.04, h * M + 0.04, d * M + 0.04)).translate(0, (h / 2) * M, 0), [w, d, h]);
  const matrix = useMemo(() => matrixOf(item), [item]);
  return <lineSegments geometry={geometry} matrix={matrix} matrixAutoUpdate={false} material={highlight} />;
}

const highlight = new THREE.LineBasicMaterial({ color: "#2f6fde", depthTest: false });

// где встанет предмет: полупрозрачные габариты в цвете слоя с рёбрами
function Ghost({ item, type, color }: { item: Item; type: TypeBrief | undefined; color: string }) {
  const { w, d, h } = sizeOf(type);
  const box = useMemo(() => new THREE.BoxGeometry(w * M, h * M, d * M).translate(0, (h / 2) * M, 0), [w, d, h]);
  const edges = useMemo(() => new THREE.EdgesGeometry(box), [box]);
  const fill = useMemo(() => new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.35, depthWrite: false }), [color]);
  const matrix = useMemo(() => matrixOf(item), [item]);
  return (
    <group matrix={matrix} matrixAutoUpdate={false} name="ghost">
      <mesh geometry={box} material={fill} raycast={() => null} />
      <lineSegments geometry={edges} material={highlight} raycast={() => null} />
    </group>
  );
}

// Перетаскивание в 3D: по плоскости пола этажа; настенные — вдоль стены; Shift — поворот.
// Луч пускается только при нажатии (а не на каждое движение мыши по 2 000 предметам), и
// раньше, чем вращение сцены: нажатие на предмет сцену не вращает.
function useDrag(root: React.RefObject<THREE.Group | null>, store: EditorStore | undefined, cat: Catalog, plan: Plan | undefined, floorHeight: number, setGhost: (g: Item | null) => void) {
  const { camera, gl, controls } = useThree();
  const faces = useMemo(() => (plan ? wallGeometry(plan).faces : []), [plan]);
  useEffect(() => {
    if (!store) return;
    const el = gl.domElement;
    const ray = new THREE.Raycaster();
    const ndc = (cx: number, cy: number) => {
      const rect = el.getBoundingClientRect();
      return new THREE.Vector2(((cx - rect.left) / rect.width) * 2 - 1, -((cy - rect.top) / rect.height) * 2 + 1);
    };
    // точка плана (мм) под курсором: стены, пол, колонны этажа — без предметов (луч по 2 000
    // предметов на каждое движение мыши дорог), мимо них — плоскость пола. Попали в стену —
    // предмет встаёт перед ней: в бок — с этой стороны, в верх — со стороны камеры
    const pick = (cx: number, cy: number, type: TypeBrief): [number, number] | null => {
      const r = root.current;
      if (!r) return null;
      ray.setFromCamera(ndc(cx, cy), camera);
      const floorY = new THREE.Vector3().setFromMatrixPosition(r.matrixWorld).y;
      const scene = (r.parent?.children ?? []).filter((c) => c !== r);
      const hit = ray.intersectObjects(scene, true)[0];
      let at: THREE.Vector3 | null = hit?.point.clone() ?? null;
      let push: [number, number] | null = null;
      if (hit?.face && at && at.y > floorY + 0.05) {
        const n = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
        if (Math.abs(n.y) < 0.3) push = [n.x, -n.z];
        else if (n.y > 0.7) {
          const toCamera: [number, number] = [camera.position.x - at.x, -(camera.position.z - at.z)];
          const len = Math.hypot(...toCamera) || 1;
          push = [(toCamera[0] / len) * 1.6, (toCamera[1] / len) * 1.6]; // через толщину стены
        }
      }
      if (!at) at = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -floorY), new THREE.Vector3());
      if (!at) return null;
      const local = r.worldToLocal(at);
      const p: [number, number] = [local.x / M, -local.z / M];
      if (!push) return p;
      const step = sizeOf(type).d / 2 + 20;
      return [p[0] + push[0] * step, p[1] + push[1] * step];
    };
    const unitOf = (unitId: string | null) => (unitId ? { id: unitId, model_id: store.state.unitModels[unitId] ?? null } : undefined);
    const preview = (typeId: string | null, cx: number, cy: number, free: boolean) => {
      const t = typeId ? cat.types.get(typeId) : undefined;
      const p = t ? pick(cx, cy, t) : null;
      const planned = t && p ? planPlacement(store, cat, t, p, faces, floorHeight, free) : null;
      setGhost(planned && !planned.container ? planned.item : null);
    };
    // выбран тип в каталоге — щелчок по сцене ставит его (с Shift — несколько раз)
    const place = (e: PointerEvent) => {
      const s = store.state;
      const t = s.placing ? cat.types.get(s.placing) : undefined;
      const p = t ? pick(e.clientX, e.clientY, t) : null;
      if (!t || !p) return false;
      e.stopPropagation();
      const unit = unitOf(s.placingUnit);
      placeAt(store, cat, t, p, faces, floorHeight, e.altKey, unit);
      if (!e.shiftKey || unit) {
        store.set({ placing: null, placingUnit: null });
        setGhost(null);
      }
      return true;
    };
    let frame = 0;
    const hover = (e: PointerEvent) => {
      const placing = store.state.placing;
      el.style.cursor = placing ? "copy" : "";
      if (!placing) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = 0;
        preview(store.state.placing, e.clientX, e.clientY, e.altKey);
      });
    };
    const leave = () => setGhost(null);
    // тип или единица из «Неразмещённых» — перетаскиванием из панели слева
    const over = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes("application/x-item-type")) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      const typeId = draggedType(e.dataTransfer);
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = 0;
        preview(typeId, e.clientX, e.clientY, e.altKey);
      });
    };
    const drop = (e: DragEvent) => {
      const typeId = e.dataTransfer?.getData("application/x-item-type");
      cancelAnimationFrame(frame);
      frame = 0;
      setGhost(null);
      if (!typeId) return;
      e.preventDefault();
      const t = cat.types.get(typeId);
      const p = t ? pick(e.clientX, e.clientY, t) : null;
      if (t && p) placeAt(store, cat, t, p, faces, floorHeight, e.altKey, unitOf(e.dataTransfer!.getData("application/x-unit") || null));
    };
    const down = (e: PointerEvent) => {
      if (e.button !== 0 || !root.current) return;
      if (store.state.placing && place(e)) return;
      ray.setFromCamera(ndc(e.clientX, e.clientY), camera);
      const hit = ray.intersectObjects(root.current.children, true).find((h) => h.instanceId !== undefined && (h.object.userData.items as Item[] | undefined)?.[h.instanceId]);
      if (!hit) return;
      const id = (hit.object.userData.items as Item[])[hit.instanceId!]!.id;
      const s = store.state;
      const item = s.items.find((i) => i.id === id);
      if (!item) return;
      e.stopPropagation();
      store.set({ selection: [{ kind: "item", id }] });
      const t = cat.types.get(item.type_id);
      const { w, d } = sizeOf(t);
      const base = s.items;
      // плоскость низа предмета в координатах сцены
      const floorY = new THREE.Vector3().setFromMatrixPosition(root.current.matrixWorld).y;
      const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -(floorY + item.z * M));
      const onPlane = (cx: number, cy: number) => {
        ray.setFromCamera(ndc(cx, cy), camera);
        const p = new THREE.Vector3();
        return ray.ray.intersectPlane(plane, p) ? ([p.x / M, -p.z / M] as [number, number]) : null;
      };
      const start = onPlane(e.clientX, e.clientY);
      const startX = e.clientX;
      let moved = false;
      const orbit = controls as unknown as { enabled: boolean } | null;
      if (orbit) orbit.enabled = false;
      const move = (ev: PointerEvent) => {
        let next: Item;
        if (ev.shiftKey) {
          let angle = item.angle - (ev.clientX - startX) * 0.5;
          if (!ev.altKey) angle = Math.round(angle / 15) * 15;
          next = { ...item, angle: normAngle(angle) };
        } else {
          const p = onPlane(ev.clientX, ev.clientY);
          if (!p || !start) return;
          next = { ...item, x: (item.x ?? 0) + p[0] - start[0], y: (item.y ?? 0) + p[1] - start[1] };
          if (!ev.altKey && t && t.mount !== "ceiling") {
            const stick = stickToWall(faces, [next.x!, next.y!], w, d, t.mount === "wall" ? 1500 : 150);
            if (stick) next = { ...next, x: stick.x, y: stick.y, angle: stick.angle };
          }
        }
        moved = true;
        store.previewItems(base.map((i) => (i.id === id ? next : i)));
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        if (orbit) orbit.enabled = true;
        if (moved) {
          const next = store.state.items;
          store.previewItems(base);
          store.changeItems(next);
        }
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    };
    // выбор типа сняли (Esc, другой режим) — «призрак» и курсор уходят сразу
    const stop = store.subscribe(() => {
      if (store.state.placing) return;
      el.style.cursor = "";
      setGhost(null);
    });
    el.addEventListener("pointerdown", down, { capture: true });
    el.addEventListener("pointermove", hover);
    el.addEventListener("pointerleave", leave);
    el.addEventListener("dragover", over);
    el.addEventListener("dragleave", leave);
    el.addEventListener("drop", drop);
    return () => {
      stop();
      cancelAnimationFrame(frame);
      el.style.cursor = "";
      el.removeEventListener("pointerdown", down, { capture: true });
      el.removeEventListener("pointermove", hover);
      el.removeEventListener("pointerleave", leave);
      el.removeEventListener("dragover", over);
      el.removeEventListener("dragleave", leave);
      el.removeEventListener("drop", drop);
    };
  }, [store, gl, camera, controls, cat, faces, root, floorHeight, setGhost]);
}
