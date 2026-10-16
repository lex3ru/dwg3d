import { useGLTF } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { Suspense, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { placeModel, transformOf } from "@/catalog/model3d";
import type { TypeBrief } from "@/catalog/types";
import { normAngle, sizeOf, stickToWall, wallGeometry, type Item } from "./items";
import type { Catalog } from "./placement";
import type { Plan } from "./plan";
import type { EditorStore } from "./store";

// Предметы в 3D (5.1.7, 5.3.3): 3D-модель типа или фигура по габаритам в цвете слоя.
// Предметы одного типа рисуются одним набором экземпляров — 2 000 предметов этажа идут
// плавно (8.2). Выбор, перемещение по полу (настенные — вдоль стены), поворот: Shift и
// движение мыши (шаг 15°, Alt — свободно).

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

export function Items3D({ items, cat, hidden, selected, interactive, store, plan }: {
  items: Item[];
  cat: Catalog;
  hidden: string[];
  selected: Set<string>;
  interactive: boolean;
  store?: EditorStore;
  plan?: Plan;
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
  useDrag(root, interactive ? store : undefined, cat, plan);
  return (
    <group ref={root}>
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

// Перетаскивание в 3D: по плоскости пола этажа; настенные — вдоль стены; Shift — поворот.
// Луч пускается только при нажатии (а не на каждое движение мыши по 2 000 предметам), и
// раньше, чем вращение сцены: нажатие на предмет сцену не вращает.
function useDrag(root: React.RefObject<THREE.Group | null>, store: EditorStore | undefined, cat: Catalog, plan: Plan | undefined) {
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
    const down = (e: PointerEvent) => {
      if (e.button !== 0 || !root.current) return;
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
    el.addEventListener("pointerdown", down, { capture: true });
    return () => el.removeEventListener("pointerdown", down, { capture: true });
  }, [store, gl, camera, controls, cat, faces, root]);
}
