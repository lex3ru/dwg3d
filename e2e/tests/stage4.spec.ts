import { expect, test, type Page } from "@playwright/test";
import { login, loginAdmin, unique } from "./helpers";

// Приёмка этапа 4 (10.1): режим «Расстановка» — С6 «Расстановка кабинета» и расстановка
// светильников из С8 (без освещённости).

const H = { "X-Requested-With": "app" };

interface Item {
  id: string;
  type_id: string;
  room_id: string | null;
  x: number;
  y: number;
  angle: number;
  z: number;
}

// Этаж: кабинеты 214 и 215 над коридором 12 × 2 м
async function floorWithRooms(page: Page) {
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: unique("С6-") } })).json();
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
  const rooms = Object.fromEntries((await saved.json()).rooms.map((r: { number: string; id: string }) => [r.number, r.id]));
  return { building: b.id as string, floor: floor.id as string, rooms };
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

async function items(page: Page, floor: string): Promise<Item[]> {
  return (await (await page.request.get(`/api/floors/${floor}/items`)).json()).items;
}

async function typeId(page: Page, name: string): Promise<string> {
  const tree = await (await page.request.get("/api/catalog")).json();
  return tree.types.find((t: { name: string }) => t.name === name).id;
}

async function pick(page: Page, name: string) {
  await page.getByRole("tab", { name: "Каталог" }).click();
  await page.getByLabel("Поиск в каталоге").fill(name);
  // у настенных и потолочных в строке ещё «на стену», «на потолок»
  return page.getByRole("list", { name: "Типы для расстановки" }).getByRole("button", { name }).first();
}

// щелчок по типу, щелчок по плану
async function placeAt(page: Page, name: string, x: number, y: number) {
  await (await pick(page, name)).click();
  const p = await screen(page, x, y);
  await page.mouse.click(p.x, p.y);
}

test("С6: расстановка кабинета — из каталога на план, шкаф к стене, поворот, 3D", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  await page.goto(`/plan/${f.building}/${f.floor}`);
  await page.getByRole("tab", { name: "Расстановка" }).click();
  const plan = page.getByRole("img", { name: "План этажа" });

  // стол — перетаскиванием из каталога
  const p = await screen(page, 3000, 4200);
  const box = (await plan.boundingBox())!;
  await (await pick(page, "Стол письменный 1200×600")).dragTo(plan, { targetPosition: { x: p.x - box.x, y: p.y - box.y } });
  await expect(page.getByText("Расстановка сохраняется сразу")).toBeVisible();
  await expect.poll(async () => (await items(page, f.floor)).length).toBe(1);

  // кресло врача, стул пациента, кушетка — выбор и щелчок по плану
  await placeAt(page, "Кресло врача", 3000, 4900);
  await placeAt(page, "Стул медицинский винтовой", 3000, 3500);
  await placeAt(page, "Кушетка смотровая", 1000, 3800);
  // шкаф — посреди кабинета, потом к стене: прилипает спиной
  await placeAt(page, "Шкаф для документов", 4500, 4000);
  await expect.poll(async () => (await items(page, f.floor)).length).toBe(5);
  const cabinetType = await typeId(page, "Шкаф для документов");
  const cabinet = (await items(page, f.floor)).find((i) => i.type_id === cabinetType)!;
  expect(cabinet.angle).toBe(0);
  const from = await screen(page, 4500, 4000);
  const to = await screen(page, 4500, 5700);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  for (let k = 1; k <= 10; k++) await page.mouse.move(from.x, from.y + ((to.y - from.y) * k) / 10);
  await page.mouse.up();
  // спиной к стене кабинета: грань стены 6000 − 150, шкаф глубиной 400 — центр на 5650
  await expect.poll(async () => {
    const c = (await items(page, f.floor)).find((i) => i.id === cabinet.id)!;
    return [Math.round(c.y), c.angle];
  }).toEqual([5650, 180]);

  // кушетку поворачивает
  const couchType = await typeId(page, "Кушетка смотровая");
  const couch = (await items(page, f.floor)).find((i) => i.type_id === couchType)!;
  const c = await screen(page, couch.x, couch.y);
  await page.mouse.click(c.x, c.y);
  await expect(page.getByRole("heading", { name: "Кушетка смотровая" })).toBeVisible();
  await page.getByRole("button", { name: "+90°" }).click();
  await expect.poll(async () => (await items(page, f.floor)).find((i) => i.id === couch.id)!.angle).toBe(90);
  // отмена и повтор — тоже сразу на сервере
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await items(page, f.floor)).find((i) => i.id === couch.id)!.angle).toBe(0);
  await page.keyboard.press("Control+y");
  await expect.poll(async () => (await items(page, f.floor)).find((i) => i.id === couch.id)!.angle).toBe(90);

  // результат: расстановка кабинета на плане — всё в 214
  const placed = await items(page, f.floor);
  expect(placed.map((i) => i.room_id)).toEqual(Array(5).fill(f.rooms["214"]));
  // и в 3D
  await page.getByRole("radio", { name: "оба" }).click();
  await expect(page.locator("canvas")).toBeVisible();
  // журнал знает, кто и что ставил
  const history = (await (await page.request.get("/api/journal", { params: { ref: `room:${f.rooms["214"]}` } })).json()).items;
  expect(history.some((h: { summary: string }) => h.summary.includes("поставлены: Шкаф для документов"))).toBeTruthy();
});

test("С8: светильник на потолок коридора и ряд с шагом 3 м до конца коридора", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  await page.goto(`/plan/${f.building}/${f.floor}`);
  await page.getByRole("tab", { name: "Расстановка" }).click();
  // освещение по умолчанию скрыто — включить
  await page.getByRole("tab", { name: "Слои" }).click();
  await page.getByRole("button", { name: "Показать слой Освещение" }).click();
  await placeAt(page, "Светильник светодиодный 600×600", 1500, 1000);
  await expect(page.getByRole("heading", { name: "Светильник светодиодный 600×600" })).toBeVisible();
  const step = page.getByRole("textbox", { name: /^Шаг вдоль/ });
  await step.fill("3000");
  await step.press("Enter");
  await page.getByRole("button", { name: "До конца помещения" }).click();
  await page.getByRole("button", { name: "Поставить копии (3)" }).click();
  await expect.poll(async () => (await items(page, f.floor)).length).toBe(4);
  const lamps = (await items(page, f.floor)).sort((a, b) => a.x - b.x);
  expect(lamps.map((l) => l.x)).toEqual([1500, 4500, 7500, 10500]);
  // на потолке: низ светильника — высота этажа минус его высота
  expect(lamps.every((l) => l.z === 3300 - 40 && l.room_id === f.rooms["1К"])).toBeTruthy();
});

test("Предупреждения расстановки: стена, дверь, вне помещений; «просмотр» только смотрит", async ({ page, browser }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const table = await typeId(page, "Стол письменный 1200×600");
  const r = await page.request.post(`/api/floors/${f.floor}/items/changes`, {
    headers: H,
    data: {
      create: [
        { type_id: table, x: 6000, y: 4000 }, // на перегородке
        { type_id: table, x: 4500, y: 2700 }, // в проёме двери
        { type_id: table, x: 15000, y: 4000 }, // за стенами
      ],
    },
  });
  expect(r.ok()).toBeTruthy();
  await page.goto(`/plan/${f.building}/${f.floor}`);
  await page.getByRole("tab", { name: "Расстановка" }).click();
  const list = page.getByRole("region", { name: "Предупреждения расстановки" });
  await expect(list.getByText("предметов: 3")).toBeVisible();
  await expect(list.getByText(/пересекает стену/)).toBeVisible();
  await expect(list.getByText(/перекрывает проём двери/)).toBeVisible();
  await expect(list.getByText(/^стоит вне помещений/)).toBeVisible();

  // «просмотр»: видит предметы и слои, каталога и правки нет
  const login1 = unique("v");
  await page.request.post("/api/users", { headers: H, data: { login: login1, full_name: "Петрова Е. А.", role: "viewer", building_ids: [f.building], password: "Temporary-1" } });
  const context = await browser.newContext();
  const viewer = await context.newPage();
  await login(viewer, login1, "Temporary-1");
  await viewer.getByLabel("Текущий пароль").fill("Temporary-1");
  await viewer.getByLabel("Новый пароль", { exact: true }).fill("Viewer-pass-12");
  await viewer.getByLabel("Новый пароль ещё раз").fill("Viewer-pass-12");
  await viewer.getByRole("button", { name: "Сменить и продолжить" }).click();
  await viewer.goto(`/plan/${f.building}/${f.floor}`);
  await expect(viewer.getByRole("img", { name: "План этажа" }).locator("[data-item]")).toHaveCount(3);
  await expect(viewer.getByRole("region", { name: "Слои" })).toBeVisible();
  await expect(viewer.getByRole("region", { name: "Каталог" })).toHaveCount(0);
  await expect(viewer.getByRole("tab", { name: "Расстановка" })).toHaveCount(0);
  await context.close();
});

test("Вложение: коммутатор — в стойку 19″, со стойкой и уходит", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  await page.goto(`/plan/${f.building}/${f.floor}`);
  await page.getByRole("tab", { name: "Расстановка" }).click();
  await placeAt(page, "Шкаф телекоммуникационный 19″", 9000, 4000);
  await expect(page.getByRole("heading", { name: "Внутри (0)" })).toBeVisible();
  // мимо стойки — не ставится: сам он на план не встаёт
  await placeAt(page, "Коммутатор", 7000, 3000);
  await expect(page.getByRole("status")).toContainText("сам на план не ставится");
  await placeAt(page, "Коммутатор", 9000, 4000);
  await expect(page.getByRole("heading", { name: "Внутри (1)" })).toBeVisible();
  await expect.poll(async () => (await items(page, f.floor)).length).toBe(2);
  const placed = await items(page, f.floor);
  const rack = placed.find((i) => i.x !== null)!;
  expect(placed.find((i) => i.x === null)).toMatchObject({ room_id: f.rooms["215"] });
  await page.keyboard.press("Delete");
  await expect.poll(async () => (await items(page, f.floor)).length).toBe(0);
  expect(rack.room_id).toBe(f.rooms["215"]);
});
