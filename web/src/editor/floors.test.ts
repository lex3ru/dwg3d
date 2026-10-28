import { describe, expect, test } from "vitest";
import { floorUrl, groundFloor, projectFloor } from "./floors";

// Переходы между этажами (5.3.6 п. 2): режим проекта не теряется (R-042), «Открыть на плане» —
// туда, где проект правят (R-043)

const floors = [
  { id: "b1", elevation: -3300 },
  { id: "f1", elevation: 0 },
  { id: "f2", elevation: 3300 },
  { id: "f3", elevation: 6600 },
];

describe("адрес другого этажа", () => {
  test("проект и вид переходят на другой этаж", () => {
    expect(floorUrl("b", "f2", { project: "p", view: "both" })).toBe("/plan/b/f2?project=p&view=both");
    expect(floorUrl("b", "f2", { project: "p", view: "2d" })).toBe("/plan/b/f2?project=p");
  });

  test("без проекта и в 2D — просто этаж", () => {
    expect(floorUrl("b", "f2", { project: null, view: "2d" })).toBe("/plan/b/f2");
    expect(floorUrl("b", "f2", { view: "3d" })).toBe("/plan/b/f2?view=3d");
  });
});

describe("этаж для «Открыть на плане»", () => {
  test("проект без изменений — последний открытый этаж здания", () => {
    expect(projectFloor(floors, [], "f3")?.id).toBe("f3");
  });

  test("без изменений и без запомненного — первый надземный, а не подвал", () => {
    expect(projectFloor(floors, [], null)?.id).toBe("f1");
    expect(groundFloor(floors)?.id).toBe("f1");
  });

  test("запомненного этажа больше нет — первый надземный", () => {
    expect(projectFloor(floors, [], "gone")?.id).toBe("f1");
  });

  test("изменения есть — нижний этаж с ними, если последний открытый без изменений", () => {
    expect(projectFloor(floors, ["f3", "f2"], "f1")?.id).toBe("f2");
  });

  test("последний открытый среди этажей с изменениями — он", () => {
    expect(projectFloor(floors, ["f2", "f3"], "f3")?.id).toBe("f3");
  });

  test("у здания нет надземных этажей — первый", () => {
    expect(groundFloor([{ id: "b2", elevation: -6600 }, { id: "b1", elevation: -3300 }])?.id).toBe("b2");
  });
});
