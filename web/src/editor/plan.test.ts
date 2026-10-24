import { describe, expect, test } from "vitest";
import { arcPoints, band, dist, pointAt, pointInPolygon, polylineLength, projectOnSegment, rect, slice, type Pt } from "./plan";

// Геометрия плана (5.1.4): мм, Y вверх

describe("дуга стены по bulge (как geometry.arc_points на сервере)", () => {
  test("прямая стена — две точки", () => {
    expect(arcPoints([0, 0], [2000, 0], 0)).toEqual([[0, 0], [2000, 0]]);
  });

  test("bulge 1 — полуокружность через концы, выгнута вправо от направления a → b", () => {
    const arc = arcPoints([0, 0], [2000, 0], 1);
    expect(arc[0]![0]).toBeCloseTo(0);
    expect(arc[0]![1]).toBeCloseTo(0);
    expect(arc.at(-1)![0]).toBeCloseTo(2000);
    expect(arc.at(-1)![1]).toBeCloseTo(0);
    for (const p of arc) expect(dist(p, [1000, 0])).toBeCloseTo(1000);
    expect(Math.min(...arc.map((p) => p[1]))).toBeCloseTo(-1000);
    expect(polylineLength(arc)).toBeCloseTo(Math.PI * 1000, -1); // ломаная короче дуги не больше чем на 5 мм
  });
});

describe("полилиния", () => {
  const L: Pt[] = [[0, 0], [3000, 0], [3000, 2000]];

  test("точка и направление на расстоянии от начала", () => {
    expect(pointAt(L, 1000)).toEqual({ p: [1000, 0], dir: [1, 0] });
    expect(pointAt(L, 4000)).toEqual({ p: [3000, 1000], dir: [0, 1] });
    expect(pointAt(L, 9000).p).toEqual([3000, 2000]); // за концом — конец
  });

  test("часть между s0 и s1 проходит через излом", () => {
    expect(slice(L, 2000, 4000)).toEqual([[2000, 0], [3000, 0], [3000, 1000]]);
  });

  test("ближайшая точка отрезка не выходит за его концы", () => {
    expect(projectOnSegment([500, 700], [0, 0], [1000, 0])).toEqual({ p: [500, 0], t: 0.5, d: 700 });
    expect(projectOnSegment([-300, 400], [0, 0], [1000, 0])).toEqual({ p: [0, 0], t: 0, d: 500 });
  });

  test("тело стены — полоса заданной толщины вокруг осевой", () => {
    expect(band([[0, 0], [1000, 0]], 200)).toEqual([[0, 100], [1000, 100], [1000, -100], [0, -100]]);
  });
});

describe("многоугольники", () => {
  test("прямоугольник, повёрнутый на 90°, меняет габариты местами", () => {
    const r = rect(0, 0, 1200, 600, 90);
    expect(Math.max(...r.map((p) => p[0]))).toBeCloseTo(300);
    expect(Math.max(...r.map((p) => p[1]))).toBeCloseTo(600);
  });

  test("точка в невыпуклом помещении (Г-образный коридор)", () => {
    const corridor: Pt[] = [[0, 0], [6000, 0], [6000, 2000], [2000, 2000], [2000, 6000], [0, 6000]];
    expect(pointInPolygon([1000, 5000], corridor)).toBe(true);
    expect(pointInPolygon([5000, 1000], corridor)).toBe(true);
    expect(pointInPolygon([4000, 4000], corridor)).toBe(false); // во внутреннем углу Г
  });
});
