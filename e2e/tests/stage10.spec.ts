import { expect, test } from "@playwright/test";
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
