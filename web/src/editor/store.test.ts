// @vitest-environment jsdom
import { beforeEach, describe, expect, test } from "vitest";
import { setStorageUser } from "@/lib/userStorage";
import type { Item } from "./items";
import { emptyPlan } from "./plan";
import { EditorStore, readDraft, type ItemOp } from "./store";

// Отмена и повтор (5.1.4 п. 7); несохранённые правки переживают закрытие вкладки (6.5.2)

beforeEach(() => localStorage.clear());

const nodes = (s: EditorStore) => Object.keys(s.state.plan.nodes);

describe("план", () => {
  test("отмена и повтор по шагам; новая правка обрывает повтор", () => {
    const s = new EditorStore("f1", emptyPlan(), 7, []);
    s.apply((p) => void (p.nodes.a = [0, 0]));
    s.apply((p) => void (p.nodes.b = [1000, 0]));
    s.undo();
    expect(nodes(s)).toEqual(["a"]);
    s.undo();
    s.undo(); // отменять больше нечего
    expect(nodes(s)).toEqual([]);
    s.redo();
    expect(nodes(s)).toEqual(["a"]);
    s.apply((p) => void (p.nodes.c = [0, 1000]));
    s.redo();
    expect(nodes(s)).toEqual(["a", "c"]);
  });

  test("правка не трогает прежний план — он остаётся шагом отмены", () => {
    const s = new EditorStore("f1", emptyPlan(), 7, []);
    s.apply((p) => void (p.nodes.a = [0, 0]));
    const before = s.state.plan;
    s.apply((p) => void (p.nodes.a = [500, 500]));
    expect(before.nodes.a).toEqual([0, 0]);
  });

  test("черновик — в браузере до сохранения, после сохранения — убран", () => {
    const s = new EditorStore("f1", emptyPlan(), 7, []);
    s.apply((p) => void (p.nodes.a = [0, 0]));
    expect(readDraft("f1")).toMatchObject({ base: 7, edits: 1, plan: { nodes: { a: [0, 0] } } });
    s.saved(s.state.plan, 8);
    expect(readDraft("f1")).toBeNull();
    expect(s.state).toMatchObject({ baseVersion: 8, edits: 0, past: [], future: [] });
  });
});

describe("расстановка", () => {
  const desk: Item = { id: "d", floor_id: "f1", room_id: null, type_id: "desk", model_id: null, parent_id: null, x: 1000, y: 1000, angle: 0, z: 0, label: "", unit_id: null, version: 1 };

  function store() {
    const s = new EditorStore("f1", emptyPlan(), 1, [], [], "place");
    const sent: ItemOp[] = [];
    s.sendItems = (op) => sent.push(op);
    return { s, sent };
  }

  test("каждое действие уходит на сервер; отмена отправляет обратное", () => {
    const { s, sent } = store();
    s.changeItems([desk]);
    s.changeItems([{ ...desk, x: 2000 }]);
    s.undoItems();
    expect(s.state.items[0]!.x).toBe(1000);
    s.redoItems();
    expect(s.state.items[0]!.x).toBe(2000);
    s.undoItems();
    s.undoItems();
    expect(s.state.items).toEqual([]);
    expect(sent.map((op) => [op.before.d?.x ?? null, op.after.d?.x ?? null])).toEqual([
      [null, 1000], // поставили
      [1000, 2000], // сдвинули
      [2000, 1000], // отмена сдвига
      [1000, 2000], // повтор
      [2000, 1000],
      [1000, null], // отмена постановки — убрать
    ]);
  });

  test("отмена после сохранения отправляет версию с сервера, а не ту, что была в шаге", () => {
    const { s, sent } = store();
    s.changeItems([desk]);
    s.changeItems([{ ...desk, x: 2000 }]);
    s.itemsSaved([{ ...desk, x: 2000, version: 3 }], []);
    s.undoItems();
    expect(s.state.items[0]).toMatchObject({ x: 1000, version: 3 });
    expect(sent).toHaveLength(3);
  });

  test("действие без изменений — не шаг отмены и не запрос", () => {
    const { s, sent } = store();
    s.changeItems([desk]);
    s.changeItems([{ ...desk }]);
    expect(s.state.itemPast).toHaveLength(1);
    expect(sent).toHaveLength(1);
  });
});

// R-018 п. 4: несохранённый план — того, кто его правил; на общем компьютере другой вошедший
// его не видит, а тот, кто правил, найдёт при следующем входе
test("черновик плана — свой у каждого пользователя", () => {
  setStorageUser("u1");
  new EditorStore("f1", emptyPlan(), 7, []).apply((p) => void (p.nodes.a = [0, 0]));
  expect(readDraft("f1")?.edits).toBe(1);
  setStorageUser("u2");
  expect(readDraft("f1")).toBeNull();
  setStorageUser("u1");
  expect(Object.keys(readDraft("f1")!.plan.nodes)).toEqual(["a"]);
});
