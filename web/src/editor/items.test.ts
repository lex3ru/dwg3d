import { describe, expect, test } from "vitest";
import type { TypeBrief } from "@/catalog/types";
import { align, arrayCopies, distribute, fitAlong, footprint, gapsToWalls, stickToWall, wallGeometry, warningsFor, type Item, type Placed } from "./items";
import { emptyPlan, type Plan, type Pt, type Wall } from "./plan";

// Предметы на плане (5.3.2): прилипание, размеры до стен, предупреждения, ряды

const wall = (id: string, a: string, b: string): Wall => ({ id, a, b, thickness: 200, kind: "bearing", bulge: 0 });

// Кабинет 4 × 3 м по осям стен 200 мм (внутри — 100…3900 × 100…2900), дверь в нижней стене
// на 3 м, открывается внутрь: зона полотна 2550…3450 × 100…1000
const plan: Plan = {
  ...emptyPlan(),
  nodes: { a: [0, 0], b: [4000, 0], c: [4000, 3000], d: [0, 3000] },
  walls: [wall("w1", "a", "b"), wall("w2", "b", "c"), wall("w3", "c", "d"), wall("w4", "d", "a")],
  openings: [{ id: "o1", wall: "w1", kind: "door", at: 3000, width: 900, height: 2100, sill: 0, hinge: "start", side: "left" }],
};
const inside: Pt[] = [[100, 100], [3900, 100], [3900, 2900], [100, 2900]];
const { faces } = wallGeometry(plan);

const type = (id: string, over: Partial<TypeBrief>) => ({ id, name: id, layer_id: "l", mount: "floor", width: 1200, depth: 600, height: 750, mount_height: null, container: false, archived: false, ...over }) as TypeBrief;
const desk = type("desk", {});
const shelf = type("shelf", { mount: "wall", width: 800, depth: 300, height: 400, mount_height: 1500 });

const item = (id: string, x: number, y: number, over: Partial<Item> = {}): Item => ({ id, floor_id: "f", room_id: null, type_id: "desk", model_id: null, parent_id: null, x, y, angle: 0, z: 0, label: "", unit_id: null, version: 1, ...over });
const placed = (i: Item, t: TypeBrief = desk): Placed => ({ item: i, type: t, poly: footprint(i, t) });

describe("прилипание к стене (5.3.2 п. 1)", () => {
  test("стол встаёт спиной к ближайшей стене", () => {
    expect(stickToWall(faces, [1500, 450], 1200, 600, 200)).toEqual({ x: 1500, y: 400, angle: 0, wall: "w1" });
  });

  test("у правой стены — повёрнут на 90°, спиной к ней", () => {
    expect(stickToWall(faces, [3500, 1500], 1200, 600, 200)).toMatchObject({ x: 3600, y: 1500, angle: 90, wall: "w2" });
  });

  test("не заезжает в проём двери: сдвигается вдоль стены до его края", () => {
    const s = stickToWall(faces, [2000, 450], 1200, 600, 200)!;
    expect(s.x + 600).toBeCloseTo(2550);
  });

  test("стена дальше досягаемости — остаётся где поставили", () => {
    expect(stickToWall(faces, [2000, 1500], 1200, 600, 200)).toBeNull();
  });
});

test("размеры от сторон предмета до стен (С6)", () => {
  const gaps = gapsToWalls(faces, item("d", 1500, 1500), 1200, 600);
  expect(gaps.map((g) => Math.round(g.mm)).sort((x, y) => x - y)).toEqual([800, 1100, 1100, 1800]);
});

describe("предупреждения (5.3.2 п. 6)", () => {
  const warn = (...list: Placed[]) => Object.fromEntries(warningsFor(plan, [inside], list));

  test("в свободном месте — без предупреждений", () => {
    expect(warn(placed(item("d", 1500, 1500)))).toEqual({});
  });

  test("на стене — пересекает стену и стоит вне помещений", () => {
    expect(warn(placed(item("d", 1000, 0)))).toEqual({ d: ["wall", "outside"] });
  });

  test("в зоне открывания двери; полка на стене выше проёма — не мешает", () => {
    expect(warn(placed(item("d", 3000, 600)))).toEqual({ d: ["door"] });
    expect(warn(placed(item("s", 3000, 250, { type_id: "shelf", z: 2200 }), shelf))).toEqual({});
  });

  test("на другом предмете — только если пересекаются и по высоте", () => {
    expect(warn(placed(item("d1", 1500, 1500)), placed(item("d2", 1600, 1500)))).toEqual({ d1: ["overlap"], d2: ["overlap"] });
    expect(warn(placed(item("d1", 1500, 1500)), placed(item("s", 1500, 1500, { type_id: "shelf", z: 1500 }), shelf))).toEqual({});
  });
});

describe("ряды и выравнивание (5.3.2 п. 3)", () => {
  test("копии рядами вдоль осей повёрнутого предмета", () => {
    const pts = arrayCopies(item("d", 1000, 1000, { angle: 90 }), 3, 1000, 2, 800).map(([x, y]) => [Math.round(x), Math.round(y)]);
    expect(pts).toEqual([[1000, 2000], [1000, 3000], [200, 1000], [200, 2000], [200, 3000]]);
  });

  test("«до конца коридора» (С8): сколько светильников с шагом 3 м поместится в 12 м", () => {
    const corridor: Pt[] = [[0, 0], [12000, 0], [12000, 2000], [0, 2000]];
    expect(fitAlong(item("lamp", 1500, 1000), corridor, 3000)).toBe(4);
  });

  test("по левому краю общей рамки и с равным шагом", () => {
    const list = [placed(item("a", 1000, 500)), placed(item("b", 1800, 1500)), placed(item("c", 5000, 2500))];
    expect(Object.fromEntries(align(list, "left"))).toEqual({ a: [1000, 500], b: [1000, 1500], c: [1000, 2500] });
    expect(Object.fromEntries(distribute(list, "x"))).toEqual({ a: [1000, 500], b: [3000, 1500], c: [5000, 2500] });
  });
});
