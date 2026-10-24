import { describe, expect, test } from "vitest";
import type { Layer, TypeBrief } from "@/catalog/types";
import { wallGeometry, type Item } from "./items";
import { emptyPlan, type Plan, type Wall } from "./plan";
import { planPlacement, toChanges, type Catalog } from "./placement";
import { EditorStore } from "./store";

// Постановка предметов (5.3.2 п. 1, 4) и пачка изменений для сервера

const wall = (id: string, a: string, b: string): Wall => ({ id, a, b, thickness: 200, kind: "bearing", bulge: 0 });
const plan: Plan = {
  ...emptyPlan(),
  nodes: { a: [0, 0], b: [4000, 0], c: [4000, 3000], d: [0, 3000] },
  walls: [wall("w1", "a", "b"), wall("w2", "b", "c"), wall("w3", "c", "d"), wall("w4", "d", "a")],
};
const { faces } = wallGeometry(plan);

const type = (id: string, over: Partial<TypeBrief>) => ({ id, name: id, layer_id: "l", mount: "floor", width: 600, depth: 400, height: 400, mount_height: null, container: false, archived: false, ...over }) as TypeBrief;
const types = [
  type("cabinet", { width: 800, depth: 600, height: 2000, container: true }),
  type("switch", { mount: "none", width: 440, depth: 300, height: 44 }),
  type("camera", { mount: "wall", width: 150, depth: 150, height: 150, mount_height: 2500 }),
  type("lamp", { mount: "ceiling", width: 600, depth: 600, height: 40 }),
];
const cat: Catalog = { types: new Map(types.map((t) => [t.id, t])), layers: new Map<string, Layer>() };
const T = (id: string) => cat.types.get(id)!;

const item = (id: string, typeId: string, x: number, y: number): Item => ({ id, floor_id: "f1", room_id: "r1", type_id: typeId, model_id: null, parent_id: null, x, y, angle: 0, z: 0, label: "", unit_id: null, version: 1 });
const store = (items: Item[] = []) => new EditorStore("f1", plan, 1, [], items, "place");

describe("куда встаёт предмет", () => {
  test("на стену — спиной к стене за полтора метра, на высоте из типа", () => {
    const { item: cam } = planPlacement(store(), cat, T("camera"), [1500, 1300], faces, 3300)!;
    expect(cam).toMatchObject({ x: 1500, y: 175, angle: 0, z: 2500 });
  });

  test("на потолок — где поставили, под потолком; к стене не прилипает", () => {
    const { item: lamp } = planPlacement(store(), cat, T("lamp"), [1500, 300], faces, 3300)!;
    expect(lamp).toMatchObject({ x: 1500, y: 300, angle: 0, z: 3260 });
  });

  test("«не ставится» сам — только в вместилище: внутрь шкафа, без координат", () => {
    expect(planPlacement(store(), cat, T("switch"), [2000, 1500], faces, 3300)).toBeNull();
    const placed = planPlacement(store([item("cab", "cabinet", 2000, 1500)]), cat, T("switch"), [2100, 1550], faces, 3300)!;
    expect(placed.container?.id).toBe("cab");
    expect(placed.item).toMatchObject({ parent_id: "cab", room_id: "r1", x: null, y: null });
  });

  test("шкаф в скрытом слое — не вместилище", () => {
    const s = store([item("cab", "cabinet", 2000, 1500)]);
    s.set({ hiddenLayers: ["l"] });
    expect(planPlacement(s, cat, T("switch"), [2100, 1550], faces, 3300)).toBeNull();
  });
});

describe("изменения для сервера", () => {
  const cab = item("cab", "cabinet", 2000, 1500);

  test("новый — create со всеми полями, убранный — delete с версией с сервера", () => {
    const changes = toChanges({ before: { n: null, cab }, after: { n: { ...cab, id: "n" }, cab: null } }, new Map([["cab", 4]]));
    expect(changes.create).toEqual([expect.objectContaining({ id: "n", type_id: "cabinet", x: 2000, y: 1500 })]);
    expect(changes.delete).toEqual([{ id: "cab", version: 4 }]);
  });

  test("изменённый — только изменившиеся поля; вынутый из шкафа — с координатами", () => {
    const inside = { ...item("sw", "switch", 0, 0), parent_id: "cab", x: null, y: null };
    const out = { ...inside, parent_id: null, x: 2000, y: 1500 };
    expect(toChanges({ before: { cab, sw: inside }, after: { cab: { ...cab, angle: 90 }, sw: out } }, new Map()).update).toEqual([
      { id: "cab", version: 1, angle: 90 },
      { id: "sw", version: 1, parent_id: null, x: 2000, y: 1500 },
    ]);
  });
});
