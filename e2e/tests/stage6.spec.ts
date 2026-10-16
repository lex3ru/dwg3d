import { expect, test, type Page } from "@playwright/test";
import { loginAdmin, unique } from "./helpers";

// Приёмка этапа 6 (10.1): связь планировки и учёта (5.5) и телефон (6.5.12) — С10 (обходом),
// С12, С13.

const H = { "X-Requested-With": "app" };

// Этаж: кабинеты 214 и 215 рядом, коридор вдоль них
async function floorWithRooms(page: Page) {
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: unique("Связь-") } })).json();
  const floor = await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "2 этаж" } })).json();
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
          { id: "new-1", x: 3000, y: 4000, number: "214", name: "Кабинет" },
          { id: "new-2", x: 9000, y: 4000, number: "215", name: "Кабинет" },
          { id: "new-3", x: 6000, y: 1000, number: "1К", name: "Коридор" },
        ],
      },
    },
  });
  expect(saved.ok()).toBeTruthy();
  const rooms = Object.fromEntries((await saved.json()).rooms.map((r: { number: string; id: string }) => [r.number, r.id])) as Record<string, string>;
  return { building: b.id as string, floor: floor.id as string, rooms };
}

async function typeId(page: Page, name: string): Promise<string> {
  const tree = await (await page.request.get("/api/catalog")).json();
  return tree.types.find((t: { name: string }) => t.name === name).id;
}

async function posted(page: Page, kind: string, header: object, lines: object[]) {
  const doc = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind, header, lines } })).json();
  const r = await page.request.post(`/api/inventory/documents/${doc.id}/post`, { headers: H, data: { version: doc.version } });
  expect(r.ok()).toBeTruthy();
  return (await page.request.get(`/api/inventory/documents/${doc.id}`)).json();
}

// Открыть план и дождаться, пока он впишется в окно
async function openPlan(page: Page, url: string) {
  await page.goto(url);
  await expect(page.getByRole("img", { name: "План этажа" })).toBeVisible();
  await page.waitForTimeout(300);
}

// Точка плана (мм) → точка на экране
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
  room_id: string | null;
  unit_id: string | null;
  x: number;
  y: number;
  angle: number;
}

async function items(page: Page, floor: string): Promise<Item[]> {
  return (await (await page.request.get(`/api/floors/${floor}/items`)).json()).items;
}

async function unit(page: Page, id: string) {
  return (await page.request.get(`/api/inventory/units/${id}`)).json();
}

test("С12 и С13: выданное ждёт в «Неразмещённых», ставится на стол; перенос на плане — перемещение", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const monitor = await typeId(page, "Монитор 24″");
  const wh = await (await page.request.post("/api/inventory/warehouses", { headers: H, data: { name: unique("Склад ") } })).json();
  const receipt = await posted(page, "receipt", { to_place: wh.key }, [{ type_id: monitor, qty: 2, price: 14500 }]);
  const units: string[] = receipt.lines[0].created_units.map((u: { id: string }) => u.id);
  // С12: выдача со склада в кабинет 214
  await posted(page, "transfer", { from_place: wh.key, to_place: `r:${f.rooms["214"]}` }, units.map((id) => ({ unit_id: id })));

  await openPlan(page, `/plan/${f.building}/${f.floor}?mode=place`);
  await page.getByRole("tab", { name: /^Учёт/ }).click();
  const unplaced = page.getByRole("list", { name: "Неразмещённые единицы" });
  await expect(unplaced.getByRole("button")).toHaveCount(2);
  await expect(unplaced.getByRole("button").first()).toContainText("Монитор 24″");
  await expect(unplaced).toContainText("214 Кабинет");

  // первый — перетаскиванием на стол в 214, второй — выбрать и щёлкнуть по плану
  const plan = page.getByRole("img", { name: "План этажа" });
  const box = (await plan.boundingBox())!;
  const p1 = await screen(page, 2500, 4000);
  await unplaced.getByRole("button").first().dragTo(plan, { targetPosition: { x: p1.x - box.x, y: p1.y - box.y } });
  await expect.poll(async () => (await items(page, f.floor)).filter((i) => i.unit_id).length).toBe(1);
  await expect(unplaced.getByRole("button")).toHaveCount(1);
  await unplaced.getByRole("button").first().click();
  const p2 = await screen(page, 3500, 4000);
  await page.mouse.click(p2.x, p2.y);
  await expect(page.getByText("Всё, что числится на этаже, стоит на плане.")).toBeVisible();
  await expect.poll(async () => (await items(page, f.floor)).filter((i) => i.unit_id).length).toBe(2);
  await expect(page.locator("[data-unit-state]")).toHaveCount(2);
  // справа — номер и карточка единицы
  await expect(page.getByLabel("Учёт")).toContainText("Инв. №");

  // С13: монитор перенесли на плане в 215 — в учёте числится там, перемещение оформлено само
  const placed = (await items(page, f.floor)).find((i) => i.unit_id === units[1])!;
  const from = await screen(page, placed.x, placed.y);
  const to = await screen(page, 9000, 4000);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move((from.x + to.x) / 2, from.y, { steps: 5 });
  await page.mouse.move(to.x, to.y, { steps: 5 });
  await page.mouse.up();
  await expect(page.getByRole("status")).toContainText("Оформлено «Перемещение");
  await expect.poll(async () => (await unit(page, units[1]!)).place.key).toBe(`r:${f.rooms["215"]}`);
  const docs = (await (await page.request.get("/api/inventory/documents", { params: { unit_id: units[1]! } })).json()).items;
  expect(docs.find((d: { basis: string }) => d.basis === "Перенос на плане")).toBeTruthy();
  // в истории единицы видно перемещение — кто и когда
  await page.goto(`/plan/${f.building}/${f.floor}?mode=place&card=unit:${units[1]}`);
  await page.getByRole("tab", { name: "Движение" }).click();
  await expect(page.getByRole("complementary", { name: "Карточка" })).toContainText("Перемещение");

  // связанный предмет убирают — спросить: вернуть на склад
  await openPlan(page, `/plan/${f.building}/${f.floor}?mode=place`);
  const first = (await items(page, f.floor)).find((i) => i.unit_id === units[0])!;
  const at = await screen(page, first.x, first.y);
  await page.mouse.click(at.x, at.y);
  await page.keyboard.press("Delete");
  const ask = page.getByRole("dialog", { name: "Убрать учтённое с плана" });
  await ask.getByText("Вернуть на склад").click();
  await ask.getByLabel("Куда вернуть").selectOption({ label: `Склад «${wh.name}»` });
  await ask.getByRole("button", { name: "Вернуть" }).click();
  await expect(ask).toBeHidden();
  await expect.poll(async () => (await items(page, f.floor)).some((i) => i.unit_id === units[0])).toBe(false);
  expect((await unit(page, units[0]!)).place.key).toBe(wh.key);
});

test("Постановка на учёт с плана: несколько предметов — «Ввод остатков», номера, метки", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const [desk, chair] = [await typeId(page, "Стол письменный 1200×600"), await typeId(page, "Кресло врача")];
  const r = await page.request.post(`/api/floors/${f.floor}/items/changes`, {
    headers: H,
    data: { create: [{ type_id: desk, x: 2500, y: 4000 }, { type_id: chair, x: 2500, y: 3200 }] },
  });
  expect(r.ok()).toBeTruthy();
  await openPlan(page, `/plan/${f.building}/${f.floor}?mode=place`);
  const plan = page.getByRole("img", { name: "План этажа" });
  // рамкой — оба
  const a = await screen(page, 1500, 4800);
  const b = await screen(page, 3500, 2600);
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move(b.x, b.y, { steps: 6 });
  await page.mouse.up();
  await expect(plan).toBeVisible();
  await page.getByRole("button", { name: "Поставить на учёт (2)" }).click();
  const dialog = page.getByRole("dialog", { name: "Поставить на учёт: 2" });
  await dialog.getByLabel("Ответственный").fill("Кузнецова Е. Н.");
  await dialog.getByRole("button", { name: "Провести" }).click();
  const done = page.getByRole("dialog", { name: "Поставлено на учёт" });
  await expect(done).toContainText("Ввод остатков");
  await expect(done.getByRole("button", { name: "Напечатать метки (2)" })).toBeVisible();
  await done.getByRole("button", { name: "Готово" }).click();
  const linked = (await items(page, f.floor)).filter((i) => i.unit_id);
  expect(linked).toHaveLength(2);
  const numbers = await Promise.all(linked.map(async (i) => (await unit(page, i.unit_id!)).number as string));
  expect(Math.abs(Number(numbers[0]) - Number(numbers[1]))).toBe(1);
  expect((await unit(page, linked[0]!.unit_id!)).responsible).toBe("Кузнецова Е. Н.");
});

test("С10 обходом с телефона: помещение во весь экран, «Добавить», касание, «На учёт» @телефон", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  await openPlan(page, `/plan/${f.building}/${f.floor}?room=${f.rooms["214"]}&mode=place`);
  const walk = page.getByLabel("Обход");
  await expect(walk.getByLabel("Помещение", { exact: true })).toHaveValue(f.rooms["214"]!);
  // строительство на телефоне недоступно
  await expect(page.getByRole("tab", { name: "Строительство" })).toBeHidden();

  await walk.getByRole("button", { name: "Добавить" }).click();
  const add = page.getByRole("dialog", { name: "Добавить на план" });
  await add.getByLabel("Поиск типа").fill("Кушетка смотровая");
  await add.getByRole("list", { name: "Найдено в каталоге" }).getByRole("button").first().click();
  await expect(walk).toContainText("Коснитесь места на плане");
  const p = await screen(page, 3000, 4000);
  await page.touchscreen.tap(p.x, p.y);
  await expect.poll(async () => (await items(page, f.floor)).length).toBe(1);
  await expect(walk).toContainText("не на учёте");
  // повернуть кнопкой
  await walk.getByRole("button", { name: "Повернуть на 90° по часовой" }).click();
  await expect.poll(async () => (await items(page, f.floor))[0]!.angle).toBe(270);

  await walk.getByRole("button", { name: "На учёт" }).click();
  const dialog = page.getByRole("dialog", { name: "Поставить на учёт: 1" });
  await dialog.getByRole("button", { name: "Провести" }).click();
  const done = page.getByRole("dialog", { name: "Поставлено на учёт" });
  await expect(done.getByRole("button", { name: "Напечатать метки (1)" })).toBeVisible();
  await done.getByRole("button", { name: "Готово" }).click();
  await expect(walk).toContainText("№");
  const placed = (await items(page, f.floor))[0]!;
  expect(placed.unit_id).toBeTruthy();
  expect((await unit(page, placed.unit_id!)).place.key).toBe(`r:${f.rooms["214"]}`);

  // сканер: камера в тесте недоступна — номер с наклейки вводится руками и находится
  await page.goto("/scan");
  await page.getByLabel("Код метки или инвентарный номер").fill((await unit(page, placed.unit_id!)).number);
  await page.getByRole("button", { name: "Открыть" }).click();
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.getByText("Кушетка смотровая").first()).toBeVisible();
});
