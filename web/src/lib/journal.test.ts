import { describe, expect, test } from "vitest";
import { feedRef, journalUrl, placeJournalUrl } from "./journal";

// Ленты журнала 5.7.3 (R-041): здание и этаж — из фильтров, одна сущность — из перехода

describe("feedRef", () => {
  test("сущность из перехода важнее здания и этажа", () => {
    expect(feedRef({ ref: "document:d1", building: "b1", floor: "f1" })).toBe("document:d1");
  });
  test("этаж уже здания", () => {
    expect(feedRef({ ref: "", building: "b1", floor: "f1" })).toBe("floor:f1");
    expect(feedRef({ ref: "", building: "b1", floor: "" })).toBe("building:b1");
  });
  test("без фильтров — весь журнал", () => {
    expect(feedRef({ ref: "", building: "", floor: "" })).toBe("");
  });
});

test("адреса лент", () => {
  expect(journalUrl("document:d1", "Приход № 3")).toBe("/journal?ref=document%3Ad1&about=%D0%9F%D1%80%D0%B8%D1%85%D0%BE%D0%B4+%E2%84%96+3");
  expect(placeJournalUrl("b1")).toBe("/journal?building=b1");
  expect(placeJournalUrl("b1", "f1")).toBe("/journal?building=b1&floor=f1");
});
