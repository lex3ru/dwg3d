import { expect, test, type Page } from "@playwright/test";
import { loginAdmin, unique } from "./helpers";

// Приёмка этапа 8 (10.1): проекты — создание, правка в редакторе без изменения расстановки,
// сравнение, спецификация и смета, выгрузка, применение с выдачей со склада (5.3.6, 5.5) — С9.

const H = { "X-Requested-With": "app" };

// Этаж: кабинеты 301 и 302 рядом, коридор вдоль них
async function floorWithRooms(page: Page) {
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: unique("Проекты-") } })).json();
  const floor = await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "3 этаж" } })).json();
  const wall = (id: string, a: string, z: string, thickness = 300, kind = "bearing") => ({ id, a, b: z, thickness, kind });
  const saved = await page.request.put(`/api/floors/${floor.id}/plan`, {
    headers: H,
    data: {
      plan_version: 1,
      plan: {
        nodes: { a: [0, 0], b: [12000, 0], c: [12000, 6000], d: [0, 6000], e: [0, 2000], f: [12000, 2000], g: [6000, 2000], h: [6000, 6000] },
        walls: [
          wall("w1", "a", "b"), wall("w2", "b", "f"), wall("w3", "f", "c"), wall("w4", "c", "h"), wall("w5", "h", "d"), wall("w6", "d", "e"), wall("w7", "e", "a"),
          wall("p1", "e", "g", 120, "partition"), wall("p2", "g", "f", 120, "partition"), wall("p3", "g", "h", 120, "partition"),
        ],
        openings: [
          { id: "o1", wall: "p1", kind: "door", at: 4500, width: 900, height: 2100 },
          { id: "o2", wall: "p2", kind: "door", at: 1500, width: 900, height: 2100 },
        ],
        rooms: [
          { id: "new-1", x: 3000, y: 4000, number: "301", name: "Кабинет" },
          { id: "new-2", x: 9000, y: 4000, number: "302", name: "Кабинет" },
          { id: "new-3", x: 6000, y: 1000, number: "3К", name: "Коридор" },
        ],
      },
    },
  });
  expect(saved.ok()).toBeTruthy();
  const rooms = Object.fromEntries((await saved.json()).rooms.map((r: { number: string; id: string }) => [r.number, r.id])) as Record<string, string>;
  return { building: b.id as string, name: b.name as string, floor: floor.id as string, rooms };
}

async function typeId(page: Page, name: string): Promise<string> {
  const tree = await (await page.request.get("/api/catalog")).json();
  return tree.types.find((t: { name: string }) => t.name === name).id;
}

async function screen(page: Page, x: number, y: number) {
  return page.evaluate(
    ([x, y]) => {
      const svg = document.querySelector('svg[aria-label="План этажа"]')!;
      const g = svg.querySelector("g")!;
      const m = /translate\(([-\d.e]+) ([-\d.e]+)\) scale\(([-\d.e]+)/.exec(g.getAttribute("transform")!)!;
      const r = svg.getBoundingClientRect();
      return { x: r.left + Number(m[1]) + x! * Number(m[3]), y: r.top + Number(m[2]) - y! * Number(m[3]) };
    },
    [x, y],
  );
}

interface Item {
  id: string;
  type_id: string;
  unit_id: string | null;
  params: Record<string, unknown>;
  x: number;
}

async function layout(page: Page, floor: string): Promise<Item[]> {
  return (await (await page.request.get(`/api/floors/${floor}/items`)).json()).items;
}

test("С9: проект оснащения — правка на плане, сравнение, смета, PDF, применение с выдачей со склада", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const [desk, cabinet, couch, table] = await Promise.all(
    ["Стол письменный 1200×600", "Шкаф для документов", "Кушетка смотровая", "Стол процедурный"].map((n) => typeId(page, n)),
  );
  const r = await page.request.post(`/api/floors/${f.floor}/items/changes`, {
    headers: H,
    data: { create: [{ type_id: desk, x: 3000, y: 4500 }, { type_id: cabinet, x: 800, y: 5300 }] },
  });
  const [deskItem] = (await r.json()).items as Item[];
  // на складе — одна кушетка
  const wh = await (await page.request.post("/api/inventory/warehouses", { headers: H, data: { name: unique("Склад ") } })).json();
  const doc = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind: "receipt", header: { to_place: wh.key }, lines: [{ type_id: couch, qty: 1, price: 18000 }] } })).json();
  expect((await page.request.post(`/api/inventory/documents/${doc.id}/post`, { headers: H, data: { version: doc.version } })).ok()).toBeTruthy();

  // новый проект из текущей расстановки
  await page.goto(`/projects?building=${f.building}`);
  await page.getByRole("button", { name: "Новый проект" }).click();
  await page.getByRole("dialog", { name: "Новый проект" }).getByLabel("Название").fill("Процедурный 301");
  await page.getByRole("dialog", { name: "Новый проект" }).getByRole("button", { name: "Создать" }).click();
  await expect(page.getByRole("heading", { name: "Проект «Процедурный 301»" })).toBeVisible();
  const projectId = page.url().split("/").pop()!.split("?")[0]!;

  // правка в редакторе: убрать стол, поставить кушетку и процедурный стол
  await page.getByRole("link", { name: "Открыть на плане" }).click();
  await expect(page.getByRole("status", { name: "Режим проекта" })).toContainText("Проект «Процедурный 301»");
  await expect(page.getByRole("tab", { name: "Строительство" })).toBeHidden();
  await expect(page.getByRole("img", { name: "План этажа" })).toBeVisible();
  await page.waitForTimeout(300);
  const place = async (name: string, x: number, y: number) => {
    await page.getByRole("tab", { name: "Каталог" }).click();
    await page.getByLabel("Поиск в каталоге").fill(name);
    await page.getByRole("list", { name: "Типы для расстановки" }).getByRole("button", { name }).first().click();
    const p = await screen(page, x, y);
    await page.mouse.click(p.x, p.y);
  };
  await place("Кушетка смотровая", 1500, 3500);
  await place("Стол процедурный", 4500, 3500);
  const d = await screen(page, 3000, 4500);
  await page.mouse.click(d.x, d.y);
  await expect(page.getByRole("heading", { name: "Стол письменный 1200×600" })).toBeVisible();
  await page.keyboard.press("Delete");
  await expect(page.locator("[data-removed]")).toHaveCount(1);
  // расстановка не тронута
  await expect.poll(async () => (await page.request.get(`/api/projects/${projectId}`).then((x) => x.json())).changes).toBe(3);
  expect((await layout(page, f.floor)).map((i) => i.id)).toContain(deskItem!.id);
  expect(await layout(page, f.floor)).toHaveLength(2);

  // сравнение с расстановкой и спецификация
  await page.goto(`/projects/${projectId}`);
  const diff = page.getByRole("table", { name: "Отличия" });
  await expect(diff).toContainText("Кушетка смотровая");
  await expect(diff).toContainText("убран");
  await page.getByRole("tab", { name: "Спецификация и смета" }).click();
  const spec = page.getByRole("table", { name: "Спецификация" });
  await expect(spec.getByRole("row", { name: /Кушетка смотровая/ })).toContainText("1");
  await expect(spec).toContainText("Итого к закупке");

  // второй вариант — копия без кушетки; сравнение двух проектов
  await page.getByRole("button", { name: "Копия — второй вариант" }).click();
  await page.getByRole("dialog", { name: "Новый проект" }).getByRole("button", { name: "Создать" }).click();
  await expect(page.getByRole("heading", { name: /вариант 2/ })).toBeVisible();
  const variant = page.url().split("/").pop()!.split("?")[0]!;
  const state = await (await page.request.get(`/api/projects/${variant}/floors/${f.floor}`)).json();
  const added = state.items.find((i: { type_id: string; state: string }) => i.type_id === couch && i.state === "added");
  await page.request.post(`/api/projects/${variant}/floors/${f.floor}/changes`, { headers: H, data: { delete: [{ id: added.id }] } });
  await page.goto(`/projects/${projectId}?compare=${variant}`);
  await expect(page.getByRole("table", { name: "Отличия" }).getByRole("row")).toHaveCount(2);
  await expect(page.getByRole("table", { name: "Отличия" })).toContainText("добавлен");

  // PDF для руководства
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "PDF для руководства" }).click();
  expect((await download).suggestedFilename()).toContain("Процедурный 301");

  // применить: кушетку — со склада, процедурный стол — к закупке
  await page.getByRole("button", { name: "Применить" }).click();
  const apply = page.getByRole("dialog", { name: "Применить проект «Процедурный 301»?" });
  await expect(apply.getByLabel("Учёт: Кушетка смотровая")).toHaveValue(/.+/);
  await expect(apply.getByLabel("Учёт: Стол процедурный")).toHaveValue("buy");
  await apply.getByRole("button", { name: "Применить" }).click();
  const done = page.getByRole("dialog", { name: "Проект применён" });
  await expect(done).toContainText("Оформлено «Перемещение");
  await done.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByText("применён", { exact: true })).toBeVisible();
  const after = await layout(page, f.floor);
  expect(after.some((i) => i.id === deskItem!.id)).toBe(false);
  const placed = after.find((i) => i.type_id === couch)!;
  expect(placed.unit_id).toBeTruthy();
  expect(after.find((i) => i.type_id === table)!.params).toEqual({ "project.buy": true });
  const unit = await (await page.request.get(`/api/inventory/units/${placed.unit_id}`)).json();
  expect(unit.place.key).toBe(`r:${f.rooms["301"]}`);
});
