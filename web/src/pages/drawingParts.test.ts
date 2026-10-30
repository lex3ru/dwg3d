import { expect, test } from "vitest";
import { type PartInfo, type PartResult, propose, sameName } from "./drawingParts";

const part = (key: string, name: string, extra: Partial<PartInfo> = {}): PartInfo => ({
  key,
  name,
  level: null,
  width: 9000,
  height: 6000,
  preview: "M0 0",
  floor_like: true,
  ...extra,
});

const done = (floor_id: string, floor: string): PartResult => ({ floor_id, floor, walls: 8, openings: 2, rooms: 2, labelled: 2, issues: 0, notes: [] });

// R-064: после перевода карточка предлагала перевод заново — части на этажи, по несколько на один
test("переведённые части и не-этажи — «не переводить»", () => {
  const parts = [part("p1", "План 1-го этажа", { level: 1 }), part("p2", "План 1-го этажа", { kind: "stamp", floor_like: false }), part("p3", "План 2-го этажа", { level: 2 })];
  const floors = [
    { id: "f1", name: "1 этаж" },
    { id: "f2", name: "2 этаж" },
  ];
  const { choice } = propose(parts, { p1: done("f1", "1 этаж"), p3: done("f2", "2 этаж") }, floors);
  expect(choice).toEqual({ p1: "", p2: "", p3: "" });
});

test("этаж — одной части: вторая с той же подписью — «не переводить»", () => {
  const parts = [part("p1", "План 1-го этажа", { level: 1 }), part("p2", "План 1-го этажа", { level: 1 })];
  expect(propose(parts, {}, [{ id: "f1", name: "1 этаж" }]).choice).toEqual({ p1: "f1", p2: "" });
  expect(propose(parts, {}, []).choice).toEqual({ p1: "new", p2: "" });
});

test("названия новых этажей не повторяют этажи здания и друг друга", () => {
  const parts = [part("p1", ""), part("p2", ""), part("p3", "Подпись", { kind: "table", floor_like: false })];
  const { choice, names } = propose(parts, {}, [{ id: "f1", name: "1 Этаж" }]);
  expect(choice).toEqual({ p1: "new", p2: "new", p3: "" });
  expect([names.p1, names.p2]).toEqual(["2 этаж", "3 этаж"]);
});

test("переведённая часть без подписи не занимает номер нового этажа", () => {
  const parts = [part("p1", ""), part("p2", "")];
  const { choice, names } = propose(parts, { p1: done("f1", "1 этаж") }, [{ id: "f1", name: "1 этаж" }]);
  expect(choice).toEqual({ p1: "", p2: "new" });
  expect(names).toEqual({ p1: "1 этаж", p2: "2 этаж" });
});

test("названия сравниваются без регистра и лишних пробелов", () => {
  expect(sameName("  1   ЭТАЖ ")).toBe(sameName("1 этаж"));
});
