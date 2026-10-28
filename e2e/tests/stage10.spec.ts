import { expect, test } from "./fixtures";
import { login, loginAdmin, unique } from "./helpers";

// Итоговая приёмка (10.3), удобство 8.6: встроенная справка по разделам — F1 или «Справка»
// вверху, поиск по всей справке, страница /help с указателем сценариев С1–С22; «просмотру» —
// только то, что ему доступно.

test("справка: F1 открывает раздел, где человек сейчас; поиск; все сценарии С1–С22", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/warehouse");
  await expect(page.getByRole("heading", { name: "Склад", level: 1 })).toBeVisible();
  await page.keyboard.press("F1");
  const help = page.getByRole("dialog", { name: "Справка" });
  await expect(help).toBeVisible();
  await expect(help.getByRole("tab", { name: "Склад" })).toHaveAttribute("aria-selected", "true");
  await expect(help.getByText("Принять на склад")).toBeVisible();
  // первая тема раскрыта — шаги видны
  await expect(help.getByText(/«Метки \(N\)»/)).toBeVisible();

  await help.getByLabel("Поиск в справке").fill("перемещ");
  const found = help.getByLabel("Найдено в справке");
  await expect(found.getByText("Переместить вещь в другой кабинет")).toBeVisible();
  await help.getByLabel("Поиск в справке").fill("С1");
  await expect(found.getByText("Здание из чертежа")).toBeVisible();
  await expect(found.getByText("Провести инвентаризацию")).toHaveCount(0); // это С18, не С1
  await help.getByRole("link", { name: "Вся справка на одной странице" }).click();
  await expect(help).toHaveCount(0);

  await expect(page).toHaveURL(/\/help$/);
  const index = page.getByRole("region", { name: "Сценарии" });
  for (let i = 1; i <= 22; i++) {
    const item = index.getByRole("listitem").filter({ hasText: new RegExp(`^С${i}\\s`) });
    await expect(item, `С${i} есть в справке`).toHaveCount(1);
    await expect(item).not.toHaveText(/—\s*$/); // и ведёт хоть в один раздел
  }
  // кнопка «Справка» вверху — то же, что F1
  await page.goto("/plan");
  await page.getByRole("button", { name: "Справка" }).click();
  await expect(page.getByRole("dialog", { name: "Справка" }).getByRole("tab", { name: "План и расстановка" })).toBeVisible();
});

test("справка «просмотра» — только о том, что ему доступно", async ({ page, browser }) => {
  await loginAdmin(page);
  const name = unique("help");
  const H = { "X-Requested-With": "app" };
  expect((await page.request.post("/api/users", { headers: H, data: { login: name, full_name: "Справкин С. С.", role: "viewer", password: "Temporary-pass-1" } })).status()).toBe(201);
  const viewer = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage();
  await login(viewer, name, "Temporary-pass-1");
  await viewer.getByLabel("Текущий пароль").fill("Temporary-pass-1");
  await viewer.getByLabel("Новый пароль", { exact: true }).fill("Viewer-pass-12");
  await viewer.getByLabel("Новый пароль ещё раз").fill("Viewer-pass-12");
  await viewer.getByRole("button", { name: "Сменить и продолжить" }).click();
  await expect(viewer.getByRole("navigation", { name: "Разделы" })).toBeVisible();
  await viewer.goto("/help");
  await expect(viewer.getByRole("region", { name: "Справка: План и расстановка" })).toContainText("Что я могу здесь");
  await expect(viewer.getByRole("region", { name: "Справка: Склад" })).toHaveCount(0);
  await expect(viewer.getByText("Нарисовать план этажа с нуля")).toHaveCount(0);
  await expect(viewer.getByRole("region", { name: "Сценарии" })).toHaveCount(0);
});

test("перенос здания: выгрузка пакета и загрузка с проверкой — этажи, предметы, учёт", async ({ page }) => {
  await loginAdmin(page);
  const H = { "X-Requested-With": "app" };
  const name = unique("Перенос-");
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name } })).json();
  const floor = await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "1 этаж" } })).json();
  const wall = (id: string, a: string, z: string) => ({ id, a, b: z, thickness: 300, kind: "bearing" });
  const saved = await (
    await page.request.put(`/api/floors/${floor.id}/plan`, {
      headers: H,
      data: { plan_version: 1, plan: { nodes: { a: [0, 0], b: [6000, 0], c: [6000, 4000], d: [0, 4000] }, walls: [wall("w1", "a", "b"), wall("w2", "b", "c"), wall("w3", "c", "d"), wall("w4", "d", "a")], rooms: [{ id: "new-1", x: 3000, y: 2000, number: "101", name: "Кабинет" }] } },
    })
  ).json();
  const room = saved.rooms[0].id;
  const tree = await (await page.request.get("/api/catalog")).json();
  const desk = tree.types.find((t: { name: string }) => t.name === "Стол письменный 1200×600").id;
  const doc = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind: "receipt", header: { to_place: `r:${room}` }, lines: [{ type_id: desk, qty: 2, price: 9900 }] } })).json();
  expect((await page.request.post(`/api/inventory/documents/${doc.id}/post`, { headers: H, data: { version: doc.version } })).ok()).toBeTruthy();
  const unit = (await (await page.request.get(`/api/inventory/documents/${doc.id}`)).json()).lines[0].created_units[0].id;
  await page.request.post(`/api/floors/${floor.id}/items/changes`, { headers: H, data: { create: [{ type_id: desk, x: 3000, y: 2000, unit_id: unit }] } });

  // выгрузка — из карточки здания
  await page.goto(`/buildings?b=${b.id}`);
  const link = page.getByRole("link", { name: "Выгрузить для переноса" });
  await expect(link).toHaveAttribute("href", `/api/buildings/${b.id}/transfer.zip`);
  const pkg = await page.request.get(`/api/buildings/${b.id}/transfer.zip`);
  expect(pkg.ok()).toBeTruthy();

  // загрузка — в ту же установку: номера заняты, каталог совпал
  await page.getByRole("button", { name: "Загрузить из файла" }).click();
  const dialog = page.getByRole("dialog", { name: "Загрузить здание из файла" });
  await dialog.getByLabel("Файл пакета").setInputFiles({ name: "перенос.zip", mimeType: "application/zip", buffer: await pkg.body() });
  const report = dialog.getByLabel("Проверка пакета");
  await expect(report).toContainText("Инвентарных единиц: 2");
  await expect(report).toContainText("Предметов: 1");
  await expect(report).toContainText("всё нашлось на этой установке");
  await expect(dialog.getByRole("alert")).toContainText("уже заняты");
  await expect(dialog.getByRole("button", { name: "Загрузить" })).toBeDisabled();
  await dialog.getByLabel(/Выдать этим единицам новые номера/).check();
  await dialog.getByLabel("Название здания").fill(`${name} копия`);
  await dialog.getByRole("button", { name: "Загрузить" }).click();
  await expect(page.getByRole("heading", { name: `${name} копия` })).toBeVisible({ timeout: 30_000 });
  const copy = new URL(page.url()).searchParams.get("b")!;
  const info = await (await page.request.get(`/api/buildings/${copy}`)).json();
  expect(info.floors).toHaveLength(1);
  const items = (await (await page.request.get(`/api/floors/${info.floors[0].id}/items`)).json()).items;
  expect(items).toHaveLength(1);
  expect(items[0].unit_id).toBeTruthy();
  const units = (await (await page.request.get("/api/inventory/units", { params: { building_id: copy } })).json()).items;
  expect(units).toHaveLength(2);
});
