import { describe, expect, test } from "vitest";
import { addWall, remove, snapPoint, splitWall } from "./ops";
import { centerline, emptyPlan, pointAt, type Plan, type Wall } from "./plan";

// Правка плана (5.1.4): привязки, разрез стены, удаление

const wall = (id: string, a: string, b: string, bulge = 0): Wall => ({ id, a, b, thickness: 200, kind: "bearing", bulge });

// Кабинет 4 × 3 м по осям стен, дверь в нижней стене в 3 м от угла
function room(): Plan {
  return {
    ...emptyPlan(),
    nodes: { a: [0, 0], b: [4000, 0], c: [4000, 3000], d: [0, 3000] },
    walls: [wall("w1", "a", "b"), wall("w2", "b", "c"), wall("w3", "c", "d"), wall("w4", "d", "a")],
    openings: [{ id: "o1", wall: "w1", kind: "door", at: 3000, width: 900, height: 2100, sill: 0, hinge: "start", side: "left" }],
  };
}

describe("привязки (5.1.4 п. 6)", () => {
  const all = { nodes: true, angles: true, grid: true };
  const scale = 0.05; // пикселей на мм: допуск 10 px — 200 мм

  test("к узлу, к середине стены, к стене", () => {
    expect(snapPoint(room(), [150, -100], scale, all)).toEqual({ p: [0, 0], kind: "node", node: "a" });
    expect(snapPoint(room(), [2050, 120], scale, all)).toEqual({ p: [2000, 0], kind: "middle" });
    expect(snapPoint(room(), [1000, 50], scale, all)).toEqual({ p: [1000, 0], kind: "wall" });
  });

  test("к сетке 100 мм вдали от стен", () => {
    expect(snapPoint(room(), [1234, 1567], scale, all)).toEqual({ p: [1200, 1600], kind: "grid" });
  });

  test("к углу 45° от предыдущей точки, длина — по сетке", () => {
    const s = snapPoint(room(), [2010, 1980], scale, all, [1000, 1000]);
    expect(s.kind).toBe("angle");
    expect(s.p[0]).toBeCloseTo(1000 + 1400 * Math.SQRT1_2);
    expect(s.p[1]).toBeCloseTo(1000 + 1400 * Math.SQRT1_2);
  });

  test("привязки выключены — точка как есть", () => {
    expect(snapPoint(room(), [1234, 1567], scale, { nodes: false, angles: false, grid: false }, [1000, 1000])).toEqual({ p: [1234, 1567], kind: "free" });
  });
});

describe("стены", () => {
  test("перегородка от стены до стены разрезает обе, дверь остаётся на месте", () => {
    const plan = room();
    const where = (p: Plan) => {
      const o = p.openings[0]!;
      return pointAt(centerline(p, p.walls.find((w) => w.id === o.wall)!), o.at).p;
    };
    const door = where(plan);
    const partition = addWall(plan, [2000, 0], [2000, 3000], 200, { thickness: 120, kind: "partition" })!;
    expect(plan.walls).toHaveLength(7); // 4 + 2 половины + перегородка
    expect(plan.nodes[partition.a]).toEqual([2000, 0]);
    expect(plan.nodes[partition.b]).toEqual([2000, 3000]);
    expect(plan.openings[0]!.wall).not.toBe("w1"); // дверь — на второй половине стены
    expect(where(plan)).toEqual(door);
  });

  test("дуга делится на две дуги того же круга", () => {
    const plan: Plan = { ...emptyPlan(), nodes: { a: [0, 0], b: [2000, 0] }, walls: [wall("w", "a", "b", 1)] };
    splitWall(plan, "w", Math.PI * 500); // на середине полуокружности
    const sweep = plan.walls.reduce((sum, w) => sum + 4 * Math.atan(w.bulge), 0);
    expect(sweep).toBeCloseTo(Math.PI);
    expect(plan.walls.map((w) => w.bulge)).toEqual([expect.closeTo(Math.tan(Math.PI / 8), 2), expect.closeTo(Math.tan(Math.PI / 8), 2)]);
  });

  test("слишком короткая стена не ставится", () => {
    expect(addWall(room(), [500, 500], [502, 501], 200, { thickness: 200, kind: "bearing" })).toBeNull();
  });

  test("удалить узел — уходят его стены, их проёмы и узлы без стен", () => {
    const plan = room();
    remove(plan, [{ kind: "node", id: "a" }]);
    expect(plan.walls.map((w) => w.id)).toEqual(["w2", "w3"]);
    expect(plan.openings).toEqual([]);
    expect(Object.keys(plan.nodes).sort()).toEqual(["b", "c", "d"]);
  });
});
