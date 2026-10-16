import { expect, test, type Page } from "@playwright/test";
import { loginAdmin, unique } from "./helpers";

// Приёмка этапа 7 (10.1): расчёты как модули (5.3.7) — обзор камер с уровнями различимости
// (5.3.4, С7) и освещённость с нормами (5.3.5, С8).

const H = { "X-Requested-With": "app" };

// Этаж: кабинеты 214 (Кабинет врача) и 215, коридор 1К вдоль них (Коридор)
async function floorWithRooms(page: Page) {
  const tree = await (await page.request.get("/api/catalog")).json();
  const purpose = (name: string) => tree.purposes.find((p: { name: string }) => p.name === name).id as string;
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: unique("Расчёты-") } })).json();
  const floor = await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "1 этаж" } })).json();
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
          { id: "new-1", x: 3000, y: 4000, number: "214", name: "Кабинет", purpose_id: purpose("Кабинет врача") },
          { id: "new-2", x: 9000, y: 4000, number: "215", name: "Кабинет", purpose_id: purpose("Кабинет врача") },
          { id: "new-3", x: 6000, y: 1000, number: "1К", name: "Коридор", purpose_id: purpose("Коридор") },
        ],
      },
    },
  });
  expect(saved.ok()).toBeTruthy();
  return { building: b.id as string, floor: floor.id as string, types: tree.types as { id: string; name: string }[] };
}

async function modelOf(page: Page, typeId: string, part: string) {
  const full = await (await page.request.get(`/api/catalog/types/${typeId}`)).json();
  return full.models.find((m: { name: string }) => m.name.includes(part)).id as string;
}

async function openPlan(page: Page, url: string) {
  await page.goto(url);
  await expect(page.getByRole("img", { name: "План этажа" })).toBeVisible();
}

test("С7: зона обзора камеры по уровням, угол вариофокальной, непросматриваемые места", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const cam = f.types.find((t) => t.name === "Камера цилиндрическая")!.id;
  const model = await modelOf(page, cam, "2.7–13.5");
  // на стене 214 на высоте 2,8 м, смотрит вдоль кабинета
  const r = await page.request.post(`/api/floors/${f.floor}/items/changes`, {
    headers: H,
    data: { create: [{ type_id: cam, model_id: model, x: 300, y: 4000, angle: 270, z: 2800 }] },
  });
  expect(r.ok()).toBeTruthy();
  await openPlan(page, `/plan/${f.building}/${f.floor}?mode=place`);
  await page.getByRole("tab", { name: /^Расчёты/ }).click();
  const calcs = page.getByRole("region", { name: "Расчёты" });
  await calcs.getByRole("checkbox", { name: "Обзор камер" }).check();
  const summary = calcs.getByLabel("Итоги: Обзор камер");
  await expect(summary).toContainText("Камер: 1");
  await expect(summary).toContainText("идентификация ≥ 250 пк/м");
  await expect(page.locator("[data-calc] path")).not.toHaveCount(0);

  // таблица камер: угол модели — 113° (широкий конец вариофокального объектива)
  await summary.getByRole("button", { name: "Камеры этажа (1)" }).click();
  const table = page.getByRole("dialog", { name: /Камеры этажа/ });
  await expect(table).toContainText("IPC-HFW2441T-ZS");
  await expect(table.getByRole("cell", { name: "113°" })).toBeVisible();
  const before = Number(await table.getByRole("row").nth(1).getByRole("cell").nth(6).innerText());
  await page.keyboard.press("Escape");

  // сузить угол до 40° — идентификация дальше
  await summary.getByRole("button", { name: "Камеры этажа (1)" }).click();
  await table.getByRole("row").nth(1).click();
  const angle = page.getByRole("textbox", { name: "Угол обзора, °" });
  await angle.fill("40");
  await angle.press("Enter");
  await expect.poll(async () => {
    await summary.getByRole("button", { name: "Камеры этажа (1)" }).click();
    const v = Number(await table.getByRole("row").nth(1).getByRole("cell").nth(6).innerText());
    await page.keyboard.press("Escape");
    return v;
  }).toBeGreaterThan(before * 2);
  const saved = (await (await page.request.get(`/api/floors/${f.floor}/items`)).json()).items[0];
  expect(saved.params["camera.fov"]).toBe(40);

  // где лицо не различить
  await calcs.getByRole("combobox", { name: "Непросматриваемые места" }).selectOption("identify");
  const unseen = calcs.getByRole("list", { name: "Не просматривается — идентификация" });
  await expect(unseen).toContainText("214 Кабинет");
  await expect(summary).toContainText("Не просматривается (идентификация)");
});

test("С8: освещённость коридора — ряд светильников с шагом 3 м ниже нормы, с шагом 1,5 м — норма", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const lamp = f.types.find((t) => t.name === "Светильник светодиодный 600×600")!.id;
  const model = await modelOf(page, lamp, "ДВО 40");
  const r = await page.request.post(`/api/floors/${f.floor}/items/changes`, {
    headers: H,
    data: { create: [{ type_id: lamp, model_id: model, x: 1500, y: 1000 }] },
  });
  expect(r.ok()).toBeTruthy();
  const first = (await r.json()).items[0].id as string;
  await openPlan(page, `/plan/${f.building}/${f.floor}?mode=place`);
  await page.getByRole("tab", { name: /^Расчёты/ }).click();
  const calcs = page.getByRole("region", { name: "Расчёты" });
  await calcs.getByRole("checkbox", { name: "Освещённость" }).check();
  const low = calcs.getByRole("list", { name: "Ниже нормы" });
  await expect(low).toContainText("1К Коридор");
  await expect(low).toContainText("214 Кабинет: ср. 0 лк при норме 500 — светильников нет");

  // светильник — рядом с шагом 3 м до конца коридора
  await page.getByRole("tab", { name: "Слои" }).click();
  await page.getByRole("button", { name: "Показать слой Освещение" }).click();
  await page.goto(`/plan/${f.building}/${f.floor}?mode=place&item=${first}`);
  await expect(page.getByRole("heading", { name: "Светильник светодиодный 600×600" })).toBeVisible();
  const step = page.getByRole("textbox", { name: /^Шаг вдоль/ });
  await step.fill("3000");
  await step.press("Enter");
  await page.getByRole("button", { name: "До конца помещения" }).click();
  await page.getByRole("button", { name: "Поставить копии (3)" }).click();
  // шаг 3 м — концы коридора всё ещё темнее нормы
  await page.getByRole("tab", { name: /^Расчёты/ }).click();
  await expect(calcs.getByRole("list", { name: "Ниже нормы" })).toContainText(/1К Коридор: ср\. \d+ лк при норме 200/);
  await expect.poll(async () => (await (await page.request.get(`/api/floors/${f.floor}/items`)).json()).items.length).toBe(4);
  // С8: уменьшить шаг — копии заново с шагом 1,5 м, пока подсветка не исчезнет
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await (await page.request.get(`/api/floors/${f.floor}/items`)).json()).items.length).toBe(1);
  await page.goto(`/plan/${f.building}/${f.floor}?mode=place&item=${first}`);
  await step.fill("1500");
  await step.press("Enter");
  await page.getByRole("button", { name: "До конца помещения" }).click();
  await page.getByRole("button", { name: /^Поставить копии/ }).click();
  await page.getByRole("tab", { name: /^Расчёты/ }).click();
  await expect(calcs.getByRole("list", { name: "Ниже нормы" })).not.toContainText("1К Коридор");
  await expect(page.getByText(/норма 200/).first()).toBeVisible();
});
