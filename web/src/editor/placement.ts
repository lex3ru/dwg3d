// Действия расстановки (5.3.2) поверх хранилища редактора: поставить, убрать, скопировать,
// вложить — и перевод действия в пачку изменений для сервера.

import type { Layer, TypeBrief } from "@/catalog/types";
import { defaultZ, footprint, newItemId, sizeOf, stickToWall, type Face, type Item } from "./items";
import { pointInPolygon, type Pt } from "./plan";
import type { EditorStore, ItemOp, Sel } from "./store";

export interface Catalog {
  types: Map<string, TypeBrief>;
  layers: Map<string, Layer>;
}

// на план — типы со слоем; «не ставится» (сервер, коммутатор) — только во вместилище
export const placeable = (t: TypeBrief) => !t.archived && !!t.layer_id;
export const standalone = (t: TypeBrief | undefined) => !!t && t.mount !== "none";

// Виден ли предмет и можно ли его выбрать (слои: скрыт, заблокирован)
export function itemState(store: EditorStore, cat: Catalog, item: Item): { shown: boolean; locked: boolean } {
  const layer = cat.types.get(item.type_id)?.layer_id ?? "";
  return { shown: !store.state.hiddenLayers.includes(layer), locked: store.state.lockedLayers.includes(layer) };
}

// Поставить тип в точку: на пол — как есть, к стене — спиной к ближайшей, на потолок —
// под потолком; в вместилище, если точка внутри него (5.3.2 п. 1, 4)
export function placeAt(store: EditorStore, cat: Catalog, type: TypeBrief, p: Pt, faces: Face[], floorHeight: number, free = false, unit?: { id: string; model_id: string | null }): Item | null {
  const { w, d } = sizeOf(type);
  const s = store.state;
  const container = type.container
    ? null
    : s.items.find((i) => {
        if (i.parent_id || !cat.types.get(i.type_id)?.container) return false;
        const st = itemState(store, cat, i);
        return st.shown && !st.locked && pointInPolygon(p, footprint(i, cat.types.get(i.type_id)));
      });
  if (!container && !standalone(type)) {
    window.dispatchEvent(new CustomEvent("editor:flash", { detail: `«${type.name}» сам на план не ставится — положите его в шкаф или стойку: перетащите прямо на них.` }));
    return null;
  }
  const item: Item = {
    id: newItemId(),
    floor_id: s.floorId,
    room_id: container?.room_id ?? null,
    type_id: type.id,
    model_id: unit?.model_id ?? null,
    parent_id: container?.id ?? null,
    x: container ? null : p[0],
    y: container ? null : p[1],
    angle: 0,
    z: defaultZ(type, floorHeight),
    label: "",
    unit_id: unit?.id ?? null,
    params: {},
    version: 1,
  };
  if (!container && !free) {
    const stick = stickToWall(faces, p, w, d, type.mount === "wall" ? 1500 : 200);
    if (stick && type.mount !== "ceiling") Object.assign(item, { x: stick.x, y: stick.y, angle: stick.angle });
  }
  store.changeItems([...s.items, item], [{ kind: "item", id: container?.id ?? item.id }]);
  // поставили в скрытый слой — слой показывается, иначе предмет пропал бы из виду
  if (type.layer_id && s.hiddenLayers.includes(type.layer_id)) store.setLayers(s.hiddenLayers.filter((l) => l !== type.layer_id), s.lockedLayers);
  return item;
}

// Убрать выбранные; если среди них связанные с учётом — сначала спросить: только с плана,
// вернуть на склад или списать (5.5)
export function requestRemove(store: EditorStore, ids: Set<string>, cat?: Catalog) {
  if (store.state.items.some((i) => ids.has(i.id) && i.unit_id)) store.set({ askRemove: [...ids] });
  else removeItems(store, ids, cat);
}

// Убрать выбранные; содержимое убранного вместилища остаётся на его месте
export function removeItems(store: EditorStore, ids: Set<string>, cat?: Catalog) {
  const items = store.state.items;
  // то, что само стоять не может, уходит вместе с вместилищем
  if (cat) for (const i of items) if (i.parent_id && ids.has(i.parent_id) && !standalone(cat.types.get(i.type_id))) ids = new Set([...ids, i.id]);
  const byId = new Map(items.map((i) => [i.id, i]));
  const next = items
    .filter((i) => !ids.has(i.id))
    .map((i) => {
      const parent = i.parent_id ? byId.get(i.parent_id) : null;
      return parent && ids.has(parent.id) ? { ...i, parent_id: null, x: parent.x, y: parent.y } : i;
    });
  store.changeItems(next, []);
}

// Копии выбранных (с содержимым вместилищ) со сдвигом или в заданные точки
export function copyItems(store: EditorStore, source: Item[], offset: Pt): Sel[] {
  const s = store.state;
  const ids = new Set(source.map((i) => i.id));
  const withContents = [...source, ...s.items.filter((i) => i.parent_id && ids.has(i.parent_id) && !ids.has(i.id))];
  const fresh = new Map(withContents.map((i) => [i.id, newItemId()]));
  const copies = withContents.map((i) => ({
    ...i,
    id: fresh.get(i.id)!,
    parent_id: i.parent_id ? (fresh.get(i.parent_id) ?? i.parent_id) : null,
    x: i.x === null ? null : i.x + offset[0],
    y: i.y === null ? null : i.y + offset[1],
    unit_id: null, // копия — новая вещь, на учёт её ставят отдельно
    version: 1,
  }));
  const sel = source.map((i) => ({ kind: "item" as const, id: fresh.get(i.id)! }));
  store.changeItems([...s.items, ...copies], sel);
  return sel;
}

export function copiesAt(store: EditorStore, item: Item, points: Pt[]) {
  const copies = points.map((p) => ({ ...item, id: newItemId(), parent_id: null, x: p[0], y: p[1], version: 1, label: item.label, unit_id: null }));
  store.changeItems([...store.state.items, ...copies], [{ kind: "item", id: item.id }, ...copies.map((c) => ({ kind: "item" as const, id: c.id }))]);
}

// ---------------------------------------------------------------- на сервер

const FIELDS = ["x", "y", "angle", "z", "parent_id", "label", "model_id", "unit_id", "params"] as const;

export interface Changes {
  create: Record<string, unknown>[];
  update: Record<string, unknown>[];
  delete: { id: string; version: number }[];
}

export function toChanges(op: ItemOp, versions: Map<string, number>): Changes {
  const out: Changes = { create: [], update: [], delete: [] };
  for (const id of Object.keys(op.after)) {
    const before = op.before[id];
    const after = op.after[id];
    if (!before && after) {
      out.create.push({ id, type_id: after.type_id, ...Object.fromEntries(FIELDS.map((k) => [k, after[k]])) });
    } else if (before && !after) {
      out.delete.push({ id, version: versions.get(id) ?? before.version });
    } else if (before && after) {
      const diff: Record<string, unknown> = {};
      for (const k of FIELDS) if (before[k] !== after[k]) diff[k] = after[k];
      if ("parent_id" in diff && after.parent_id === null) Object.assign(diff, { x: after.x, y: after.y });
      if (Object.keys(diff).length) out.update.push({ id, version: versions.get(id) ?? before.version, ...diff });
    }
  }
  return out;
}
