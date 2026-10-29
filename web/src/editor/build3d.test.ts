import { expect, test } from "vitest";
import { DEPTH_OFFSET, orbitNear, WALK_NEAR } from "./build3d";

// R-029: в узле стены перекрываются, и совпадающие грани разных материалов «дерутся» —
// мерцают при повороте. При равной глубине видна грань с меньшим сдвигом.
test("совпадающие грани: колонна поверх несущей стены, несущая поверх перегородки", () => {
  expect(DEPTH_OFFSET.columns).toBeLessThan(DEPTH_OFFSET.bearing);
  expect(DEPTH_OFFSET.bearing).toBeLessThan(DEPTH_OFFSET.partition);
});

// точность буфера глубины — около d² / (near · 2²⁴): с near 0,05 м на 150 м грани ближе 3 см
// неразличимы. Ближняя плоскость в обзоре — по расстоянию до цели, в прогулке — у самых стен
test("ближняя плоскость в обзоре растёт с расстоянием, вблизи — как в прогулке", () => {
  const precision = (d: number) => (d * d) / (orbitNear(d) * 2 ** 24);
  expect(precision(150)).toBeLessThan(0.005);
  expect(precision(600)).toBeLessThan(0.02);
  expect(orbitNear(5)).toBe(WALK_NEAR);
  expect(orbitNear(150)).toBeLessThan(1); // стена в метре от камеры не срезается
});
