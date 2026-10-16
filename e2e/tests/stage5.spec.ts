import { expect, test, type Page } from "@playwright/test";
import { loginAdmin, unique } from "./helpers";
import { xlsx } from "./xlsx";

// Приёмка этапа 5 (10.1): учёт имущества — С10 (по списку), С11, С14–С17, С19.

const H = { "X-Requested-With": "app" };
const HEAD = ["Инвентарный номер", "Наименование", "Модель", "Слой", "Вид учёта", "Количество", "Ед. изм.", "Серийный номер", "Этаж", "Помещение", "Название помещения", "Ответственный", "Подразделение", "Состояние", "Цена за ед., ₽", "Дата ввода", "Срок службы, мес.", "Стоимость, ₽", "Примечание"];

// Здание с одним этажом: помещения в ряд по 4 м
async function building(page: Page, rooms: [string, string][]) {
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: unique("Учёт-") } })).json();
  const f = await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "1 этаж" } })).json();
  const nodes: Record<string, [number, number]> = {};
  const walls = [];
  for (let i = 0; i <= rooms.length; i++) {
    nodes[`b${i}`] = [i * 4000, 0];
    nodes[`t${i}`] = [i * 4000, 5000];
    walls.push({ id: `v${i}`, a: `b${i}`, b: `t${i}`, thickness: 200, kind: "bearing" });
    if (i < rooms.length) {
      walls.push({ id: `s${i}`, a: `b${i}`, b: `b${i + 1}`, thickness: 200, kind: "bearing" });
      walls.push({ id: `n${i}`, a: `t${i}`, b: `t${i + 1}`, thickness: 200, kind: "bearing" });
    }
  }
  const saved = await page.request.put(`/api/floors/${f.id}/plan`, {
    headers: H,
    data: { plan_version: 1, plan: { nodes, walls, rooms: rooms.map(([number, name], i) => ({ id: `new-${i}`, x: i * 4000 + 2000, y: 2500, number, name })) } },
  });
  expect(saved.ok()).toBeTruthy();
  const ids = Object.fromEntries((await saved.json()).rooms.map((r: { number: string; id: string }) => [r.number, `r:${r.id}`]));
  return { id: b.id as string, name: b.name as string, floor: f.id as string, rooms: ids as Record<string, string> };
}

async function typeId(page: Page, name: string) {
  const tree = await (await page.request.get("/api/catalog")).json();
  return tree.types.find((t: { name: string }) => t.name === name).id as string;
}

async function newDoc(page: Page, kind: string, header: object, lines: object[]) {
  const doc = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind, header, lines } })).json();
  const r = await page.request.post(`/api/inventory/documents/${doc.id}/post`, { headers: H, data: { version: doc.version } });
  expect(r.ok()).toBeTruthy();
  return r.json();
}

async function confirmPost(page: Page) {
  await page.getByRole("button", { name: "Провести" }).first().click();
  await page.getByRole("dialog", { name: "Провести документ?" }).getByRole("button", { name: "Провести" }).click();
  await expect(page.getByText("проведён", { exact: true })).toBeVisible();
}

test("С10: список имущества из Excel — сопоставление, создание типа, «Ввод остатков»", async ({ page }) => {
  await loginAdmin(page);
  const b = await building(page, [["101", "Регистратура"], ["102", "Холл"], ["103", "Процедурный кабинет"], ["1К", "Коридор"]]);
  // случайное слово — не похоже ни на один тип, даже заведённый прошлыми прогонами
  const odd = Array.from({ length: 12 }, () => "бвгджзклмнпрстфхцчшщ"[Math.floor(Math.random() * 20)]).join("");
  const number = `E${Date.now().toString().slice(-8)}`;
  const file = xlsx("Имущество", [
    HEAD,
    [number, "Стойка регистратуры", "", "Мебель", "поштучно", 1, "шт.", "", 1, "101", "Регистратура", "Соколова И. П.", "Регистратура", "в работе", 86000, "01.03.2019", 120, null, ""],
    ["", "Банкетка трёхместная", "", "Мебель", "поштучно", 2, "шт.", "", 1, "102", "Холл", "", "", "в работе", 12400, "01.11.2018", 96, null, ""],
    ["", "Тонометр", "Omron M2", "Оборудование", "поштучно", 1, "шт.", "", 1, "103", "Процедурный", "", "", "неисправна", 3400, "01.09.2021", 36, null, ""],
    ["", "Перчатки смотровые нитриловые", "размер M", "", "количеством", 40, "упак.", "", 1, "103", "Процедурный", "", "", "на хранении", 520, "02.09.2025", null, null, ""],
    ["", odd, "", "Оборудование", "поштучно", 1, "шт.", "", 1, "К1", "Коридор 1 этажа", "", "", "в работе", 1000, "01.01.2024", null, null, ""],
  ]);
  await page.goto("/property");
  await page.getByRole("button", { name: "Загрузить из Excel" }).click();
  const dialog = page.getByRole("dialog", { name: "Загрузить имущество из Excel" });
  await dialog.getByLabel("Здание").selectOption({ label: b.name });
  await dialog.getByLabel("Файл со списком имущества").setInputFiles({ name: "имущество.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: file });
  // «Банкетка» похожа на «Секцию стульев», коридор К1 — на «1К Коридор»; диковинного прибора в каталоге нет
  await expect(dialog.getByText(/Есть что исправить/)).toBeVisible();
  await expect(dialog.getByLabel("Тип для «Банкетка трёхместная»")).toHaveValue(await typeId(page, "Секция стульев трёхместная"));
  await expect(dialog.getByText(`«${odd}» не сопоставлено`)).toBeVisible();
  await dialog.getByLabel(`Тип для «${odd}»`).selectOption("new");
  await dialog.getByRole("button", { name: "Проверить снова" }).click();
  await expect(dialog.getByText(/Ошибок нет. Будет заведено единиц: 5, позиций остатков: 1/)).toBeVisible();
  await dialog.getByRole("button", { name: "Загрузить", exact: true }).click();
  await expect(dialog.getByText(/Загружено: единиц — 5/)).toBeVisible();
  await dialog.getByRole("button", { name: "Открыть документ" }).click();
  await expect(page.getByRole("heading", { name: /Ввод остатков ВО-/ })).toBeVisible();
  // результат: единицы числятся в своих помещениях, номер с наклейки сохранён
  const units = await (await page.request.get("/api/inventory/units", { params: { building_id: b.id } })).json();
  expect(units.total).toBe(5);
  const stand = units.items.find((u: { number: string }) => u.number === number);
  expect(stand.place.key).toBe(b.rooms["101"]);
  expect(units.items.find((u: { type_name: string }) => u.type_name === odd).place.key).toBe(b.rooms["1К"]);
  const stock = await (await page.request.get("/api/inventory/balances", { params: { place: b.rooms["103"] } })).json();
  expect(stock.items.map((s: { qty: number }) => s.qty)).toEqual([40]);
});

test("С11 и С16: приход на склад с номерами подряд, расход перчаток", async ({ page }) => {
  await loginAdmin(page);
  const name = unique("Склад ");
  await page.goto("/warehouse");
  await page.getByRole("button", { name: "Новый склад" }).click();
  await page.getByRole("dialog", { name: "Новый склад" }).getByLabel("Название").fill(name);
  await page.getByRole("dialog", { name: "Новый склад" }).getByRole("button", { name: "Создать" }).click();
  await expect(page.getByRole("heading", { name: `Склад «${name}»` })).toBeVisible();
  await page.getByRole("button", { name: "Принять" }).click();
  await expect(page.getByRole("heading", { name: /Приход ПР-/ })).toBeVisible();
  for (const [i, [type, qty, price]] of ([["Монитор 24″", "5", "14500"], ["Перчатки смотровые нитриловые", "20", "520"]] as const).entries()) {
    await page.getByRole("button", { name: "Строка: тип и количество" }).click();
    await page.getByLabel(`Тип, строка ${i + 1}`).fill(type.slice(0, 10));
    await page.getByRole("option", { name: new RegExp(`^${type}`) }).click();
    await page.getByLabel(`Количество, строка ${i + 1}`).fill(qty);
    await page.getByLabel(`Цена, строка ${i + 1}`).fill(price);
  }
  await expect(page.getByRole("cell", { name: "82 900,00 ₽" })).toBeVisible();
  await confirmPost(page);
  await expect(page.getByRole("button", { name: "Метки (5)" })).toBeVisible();
  const docId = page.url().split("/").pop()!;
  const doc = await (await page.request.get(`/api/inventory/documents/${docId}`)).json();
  const numbers = doc.lines[0].created_units.map((u: { number: string }) => Number(u.number));
  expect(numbers).toEqual(numbers.map((_: number, i: number) => numbers[0] + i));
  // метки печатаются
  const labels = await page.request.post("/api/inventory/labels.pdf", { headers: H, data: { unit_ids: doc.lines[0].created_units.map((u: { id: string }) => u.id), origin: "http://localhost" } });
  expect((await labels.body()).subarray(0, 5).toString()).toBe("%PDF-");

  // С16: расход перчаток со склада
  await page.goto(`/warehouse?place=${doc.to_place}`);
  await page.getByRole("button", { name: "Расход / списание" }).click();
  await page.getByRole("button", { name: "Количество (остаток)" }).click();
  await page.getByLabel("Тип, строка 1").fill("Перчатки");
  await page.getByRole("option", { name: /^Перчатки смотровые нитриловые/ }).click();
  await page.getByLabel("Количество, строка 1").fill("3");
  await page.getByLabel("Причина списания").fill("Израсходовано в процедурном");
  await confirmPost(page);
  const stock = await (await page.request.get("/api/inventory/balances", { params: { place: doc.to_place } })).json();
  expect(stock.items.map((s: { qty: number }) => s.qty)).toEqual([17]);
});

test("С14, С15, С17: найти, ремонт, списание — с историей", async ({ page }) => {
  await loginAdmin(page);
  const b = await building(page, [["214", "Кабинет терапевта"]]);
  const opened = await newDoc(page, "opening", { to_place: b.rooms["214"] }, [
    { type_id: await typeId(page, "Дефибриллятор"), qty: 1, price: 185000, commissioned_on: "2021-08-30" },
    { type_id: await typeId(page, "Кресло врача"), qty: 1, price: 11200 },
  ]);
  const defib = opened.lines[0].created_units[0];
  const chair = opened.lines[1].created_units[0];

  // С17: найти по инвентарному номеру — карточка: где, состояние, «На плане»
  await page.goto("/property");
  await page.getByRole("searchbox").fill(defib.number);
  await page.getByRole("link", { name: new RegExp(`Дефибриллятор № ${defib.number}`) }).click();
  const card = page.getByRole("complementary", { name: "Карточка" });
  await expect(card.getByText("214 Кабинет терапевта")).toBeVisible();
  await expect(card.getByRole("link", { name: "На плане" })).toHaveAttribute("href", new RegExp(`/plan/${b.id}/${b.floor}\\?room=`));

  // С14: сломался — в карточке; ремонт — документами
  await card.getByLabel("Состояние").selectOption("broken");
  await expect(card.getByText("неисправна").first()).toBeVisible();
  await card.getByRole("button", { name: "В ремонт" }).click();
  await page.getByLabel("Исполнитель ремонта").fill("ООО «Медсервис»");
  await confirmPost(page);
  let unit = await (await page.request.get(`/api/inventory/units/${defib.id}`)).json();
  expect(unit.state).toBe("repair");
  await page.goto(`/property?card=unit:${defib.id}`);
  await page.getByRole("complementary", { name: "Карточка" }).getByRole("button", { name: "Из ремонта" }).click();
  await confirmPost(page);
  unit = await (await page.request.get(`/api/inventory/units/${defib.id}`)).json();
  expect(unit.state).toBe("in_use");
  expect(unit.movements.length).toBe(3);
  expect(unit.changes[0].after).toEqual({ state: "broken" });

  // С15: кресло списано с причиной — уходит из реестра и стоимости, карточка остаётся
  await page.goto(`/property?card=unit:${chair.id}`);
  await page.getByRole("complementary", { name: "Карточка" }).getByRole("button", { name: "Списать" }).click();
  await page.getByLabel("Причина списания").fill("Износ");
  await confirmPost(page);
  unit = await (await page.request.get(`/api/inventory/units/${chair.id}`)).json();
  expect([unit.state, unit.writeoff_reason, unit.value]).toEqual(["written_off", "Износ", 0]);
  const list = await (await page.request.get("/api/inventory/units", { params: { building_id: b.id } })).json();
  expect(list.items.map((u: { id: string }) => u.id)).toEqual([defib.id]);
});

test("С19: стоимость на дату с разбивкой по этажам и слоям, выгрузка в Excel", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/property?tab=cost");
  await expect(page.getByRole("columnheader", { name: "Этаж" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Слой" })).toBeVisible();
  await expect(page.getByText(/Итого на/)).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Excel" }).click();
  expect((await download).suggestedFilename()).toMatch(/^стоимость-на-.*\.xlsx$/);
});
