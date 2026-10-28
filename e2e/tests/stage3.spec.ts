import { expect, test, type Page } from "./fixtures";
import { loginAdmin, unique } from "./helpers";

// Приёмка этапа 3 (10.1): каталог — С4 «Новый тип», С5 «Новый слой», загрузка и выгрузка
// каталога, назначения помещений.

const H = { "X-Requested-With": "app" };

async function tree(page: Page) {
  return (await page.request.get("/api/catalog")).json();
}

async function newType(page: Page, name: string, layer: string) {
  await page.getByRole("button", { name: "Тип", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Новый тип" });
  await dialog.getByLabel("Название").fill(name);
  await dialog.getByLabel("Слой").selectOption({ label: layer });
  await dialog.getByRole("button", { name: "Создать" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
}

test("С4: новый тип с характеристиками и моделью", async ({ page }) => {
  await loginAdmin(page);
  const name = unique("Аппарат УЗИ ");
  await page.goto("/catalog");
  await newType(page, name, "Оборудование");

  // Основное: габариты, на пол, поштучно, срок службы 7 лет
  const field = (label: string) => page.getByRole("textbox", { name: label, exact: true });
  for (const [label, value] of [["Ширина мм", "550"], ["Глубина мм", "900"], ["Высота мм", "1400"], ["Срок службы мес.", "84"]] as const) {
    await field(label).fill(value);
    await field(label).press("Enter");
  }
  await expect(page.getByRole("radio", { name: "на пол" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("radio", { name: /поштучно/ })).toHaveAttribute("aria-checked", "true");

  // Характеристики: удостоверение — общее для типа, дата ТО — своя у каждого аппарата
  await page.getByRole("tab", { name: /Характеристики/ }).click();
  const addChar = async (title: string, kind: string, level: RegExp) => {
    await page.getByRole("button", { name: "Своя характеристика" }).click();
    const d = page.getByRole("dialog", { name: "Новая характеристика" });
    await d.getByLabel("Название").fill(title);
    await d.getByLabel("Вид значения").selectOption({ label: kind });
    await d.getByRole("radio", { name: level }).check();
    await d.getByRole("button", { name: "Сохранить" }).click();
    await expect(d).toBeHidden();
  };
  await addChar("Регистрационное удостоверение", "текст", /^у типа/);
  await addChar("Дата последнего ТО", "дата", /^у каждой вещи/);
  await page.getByRole("textbox", { name: "Регистрационное удостоверение" }).fill("РЗН 2020/12345");
  await page.getByRole("textbox", { name: "Регистрационное удостоверение" }).press("Enter");
  await expect(page.getByText("задаётся у каждой вещи")).toBeVisible();

  // Модель с производителем и ценой
  await page.getByRole("tab", { name: /Модели/ }).click();
  await page.getByRole("button", { name: "Новая модель" }).click();
  const d = page.getByRole("dialog", { name: "Новая модель" });
  await d.getByLabel("Производитель").fill("Mindray");
  await d.getByLabel("Модель").fill("DC-70");
  await d.getByLabel("Цена, ₽").fill("4500000");
  await d.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByRole("cell", { name: "DC-70", exact: true })).toBeVisible();

  // результат: тип в слое, на пол, с характеристиками и моделью — его можно ставить и учитывать
  const t = (await tree(page)).types.find((x: { name: string }) => x.name === name);
  const full = await (await page.request.get(`/api/catalog/types/${t.id}`)).json();
  expect([full.width, full.depth, full.height, full.mount, full.accounting, full.life_months]).toEqual([550, 900, 1400, "floor", "piece", 84]);
  const chars = Object.fromEntries(full.characteristics.map((c: { name: string; level: string; id: string }) => [c.name, c]));
  expect(chars["Регистрационное удостоверение"].level).toBe("type");
  expect(chars["Дата последнего ТО"].level).toBe("item");
  expect(full.values[chars["Регистрационное удостоверение"].id]).toBe("РЗН 2020/12345");
  expect(full.models.map((m: { manufacturer: string; name: string; price: number }) => [m.manufacturer, m.name, m.price])).toEqual([["Mindray", "DC-70", 4500000]]);
});

test("С5: новый слой с типами, без доработки системы", async ({ page }) => {
  await loginAdmin(page);
  const layer = unique("СКУД ");
  await page.goto("/catalog?section=layers");
  await page.getByLabel("Название нового слоя").fill(layer);
  await page.getByRole("button", { name: "Добавить" }).click();
  const color = page.getByLabel(`Цвет слоя ${layer}`);
  await expect(color).toBeVisible();
  await color.fill("#7b1fa2");
  await expect.poll(async () => (await tree(page)).layers.find((l: { name: string }) => l.name === layer)?.color).toBe("#7b1fa2");
  // пустой слой можно удалить — кнопка есть
  await expect(page.getByRole("button", { name: `Удалить слой ${layer}` })).toBeVisible();

  await page.getByRole("tab", { name: "Типы" }).click();
  await newType(page, unique("Считыватель "), layer);
  await newType(page, unique("Электрозамок "), layer);
  await expect(page.getByRole("navigation", { name: "Типы по слоям" }).getByRole("heading", { name: new RegExp(layer) })).toContainText("2");

  // слой с типами удалить нельзя — только скрыть
  await page.getByRole("tab", { name: "Слои" }).click();
  await expect(page.getByRole("button", { name: `Удалить слой ${layer}` })).toBeHidden();
  const l = (await tree(page)).layers.find((x: { name: string }) => x.name === layer);
  const refused = await page.request.delete(`/api/catalog/layers/${l.id}`, { headers: H });
  expect(refused.status()).toBe(409);
  await page.getByLabel(`Слой ${layer} виден сразу`).click();
  await expect.poll(async () => (await tree(page)).layers.find((x: { name: string }) => x.name === layer)?.visible).toBe(false);
});

test("Каталог: выгрузка в Excel и загрузка обратно — сначала проверка, без изменений", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/catalog");
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Выгрузить в Excel" }).click();
  const file = await (await download).path();
  await page.getByRole("button", { name: "Загрузить из Excel" }).click();
  await page.getByLabel("Файл каталога").setInputFiles(file);
  await expect(page.getByText("каталог уже такой же")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("dialog").getByRole("button", { name: "Загрузить", exact: true })).toHaveCount(0);
});

test("Назначения помещений: добавить, задать норму, выбрать у помещения в редакторе", async ({ page }) => {
  await loginAdmin(page);
  const name = unique("Кабинет ");
  await page.goto("/purposes");
  await page.getByLabel("Новое назначение").fill(name);
  await page.getByRole("button", { name: "Добавить" }).click();
  const norm = page.getByLabel(`Норма освещённости, ${name}`);
  await norm.fill("500");
  await norm.press("Enter");
  const surface = page.getByLabel(`Рабочая поверхность, ${name}`);
  await surface.fill("0,8");
  await surface.press("Enter");
  await expect
    .poll(async () => {
      const items = (await (await page.request.get("/api/catalog/purposes")).json()).items;
      const p = items.find((x: { name: string }) => x.name === name);
      return p && [p.norm, p.surface];
    })
    .toEqual([500, 800]);

  // у помещения в редакторе
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: unique("С4-") } })).json();
  const floor = (await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "1 этаж" } })).json()).id;
  const wall = (id: string, a: string, z: string) => ({ id, a, b: z, thickness: 300, kind: "bearing" });
  const saved = await page.request.put(`/api/floors/${floor}/plan`, {
    headers: H,
    data: {
      plan_version: 1,
      plan: {
        nodes: { a: [0, 0], b: [5000, 0], c: [5000, 4000], d: [0, 4000] },
        walls: [wall("w1", "a", "b"), wall("w2", "b", "c"), wall("w3", "c", "d"), wall("w4", "d", "a")],
        rooms: [{ id: "new-1", x: 2500, y: 2000, number: "901", name: "Кабинет" }],
      },
    },
  });
  expect(saved.ok()).toBeTruthy();
  await page.goto(`/plan/${b.id}/${floor}`);
  await page.getByRole("img", { name: "План этажа" }).getByText("901", { exact: true }).click({ force: true });
  await page.getByLabel("Назначение").selectOption({ label: name });
  await expect(page.getByText("норма 500 лк на высоте 0,8 м")).toBeVisible();
  await page.getByRole("button", { name: "Сохранить план" }).click();
  await expect.poll(async () => (await (await page.request.get(`/api/floors/${floor}/plan`)).json()).plan.rooms[0].purpose_id).not.toBeNull();
});

test("Каталог на телефоне: список типов, карточка, назад к списку @телефон", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/catalog");
  await page.getByLabel("Поиск типа").fill("Кушетка смотровая");
  await page.getByRole("button", { name: "Кушетка смотровая" }).click();
  await expect(page.getByRole("heading", { name: "Кушетка смотровая" })).toBeVisible();
  await expect(page.getByLabel("Поиск типа")).toBeHidden();
  await page.getByRole("tab", { name: /Характеристики/ }).click();
  await expect(page.getByText(/Набор «Мебель»/)).toBeVisible();
  await page.getByRole("button", { name: "К списку" }).click();
  await expect(page.getByLabel("Поиск типа")).toBeVisible();
});
