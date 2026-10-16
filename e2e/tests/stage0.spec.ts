import { expect, test } from "@playwright/test";
import { login, loginAdmin, unique } from "./helpers";

// Приёмка этапа 0 (10.1): администратор входит и заводит учётную запись «просмотр»;
// права проверяются на сервере (8.4 п. 3); каждое изменение — в журнале (5.7.3).

test("администратор заводит «просмотр», тот входит, меняет пароль и видит только своё", async ({ page, browser }) => {
  await loginAdmin(page);
  await expect(page.getByRole("navigation", { name: "Разделы" }).getByRole("link")).toHaveCount(15);

  const name = unique("view");
  await page.getByRole("link", { name: "Пользователи" }).click();
  await page.getByRole("button", { name: "Завести учётную запись" }).click();
  const dialog = page.getByRole("dialog", { name: "Новая учётная запись" });
  await dialog.getByLabel("ФИО").fill("Петрова Елена Алексеевна");
  await dialog.getByLabel("Имя для входа").fill(name);
  await dialog.getByRole("radio", { name: /Просмотр/ }).check();
  await dialog.getByRole("button", { name: "Завести" }).click();

  const issued = page.getByRole("dialog", { name: "Учётная запись заведена" });
  const temporary = (await issued.locator("code").textContent())!.trim();
  expect(temporary.length).toBeGreaterThanOrEqual(10);
  await issued.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByRole("row", { name: new RegExp(name) })).toContainText("просмотр");

  // другой человек на другом устройстве
  const viewer = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage();
  await login(viewer, name, temporary);
  await expect(viewer.getByRole("heading", { name: "Смените временный пароль" })).toBeVisible();
  await viewer.getByLabel("Текущий пароль").fill(temporary);
  await viewer.getByLabel("Новый пароль", { exact: true }).fill("Viewer-pass-12");
  await viewer.getByLabel("Новый пароль ещё раз").fill("Viewer-pass-12");
  await viewer.getByRole("button", { name: "Сменить и продолжить" }).click();

  const menu = viewer.getByRole("navigation", { name: "Разделы" });
  await expect(menu.getByRole("link")).toHaveText(["План", "Имущество"]);
  await expect(viewer.getByRole("heading", { name: "План" })).toBeVisible();
  // адрес раздела администратора не открывает его
  await viewer.goto("/users");
  await expect(viewer).toHaveURL(/\/plan$/);
  // и сервер не отдаёт данных напрямую
  const answer = await viewer.request.get("/api/users");
  expect(answer.status()).toBe(403);

  // изменения другого пользователя приходят без перезагрузки (6.1 п. 8): строка
  // «последний вход» у администратора заполнилась сама
  await expect(page.getByRole("row", { name: new RegExp(name) })).not.toContainText("—", { timeout: 10_000 });

  // журнал: кто и что сделал
  await page.getByRole("link", { name: "Журнал" }).click();
  await expect(page.getByText(`Заведена учётная запись «${name}»`)).toBeVisible();
  await expect(page.getByText(`Вход «${name}»`)).toBeVisible();
});

test("неверный пароль — понятная ошибка, попытка в журнале", async ({ page, browser }) => {
  const other = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage();
  const name = unique("nobody");
  await login(other, name, "wrong-password-1");
  await expect(other.getByRole("alert")).toHaveText("Неверное имя или пароль.");

  await loginAdmin(page);
  await page.goto("/journal?action=auth.");
  await expect(page.getByText(`Неудачная попытка входа: имени «${name}» нет`)).toBeVisible();
});

test("администратор блокирует учётную запись — сеанс заканчивается сразу", async ({ page, browser }) => {
  await loginAdmin(page);
  const name = unique("block");
  const created = await page.request.post("/api/users", {
    headers: { "X-Requested-With": "app" },
    data: { login: name, full_name: "Блокируемый Б. Б.", role: "viewer", password: "Temporary-pass-1" },
  });
  expect(created.status()).toBe(201);
  const user = (await created.json()).user;

  const viewer = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage();
  await login(viewer, name, "Temporary-pass-1");
  await expect(viewer.getByRole("heading", { name: "Смените временный пароль" })).toBeVisible();

  await page.goto(`/users?card=user:${user.id}`);
  await page.getByRole("button", { name: "Заблокировать" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Заблокировать" }).click();
  await expect(page.getByRole("complementary", { name: "Карточка" })).toContainText("заблокирована");

  await viewer.reload();
  await expect(viewer.getByRole("heading", { name: "Вход" })).toBeVisible();
  await login(viewer, name, "Temporary-pass-1");
  await expect(viewer.getByRole("alert")).toContainText("заблокирована");
});

test("каркас на телефоне: вкладки внизу, карточка — отдельной страницей @телефон", async ({ page }) => {
  await loginAdmin(page);
  const tabs = page.getByRole("navigation", { name: "Разделы" }).filter({ hasText: "Поиск" });
  await expect(tabs.getByRole("link")).toHaveText(["Главная", "Поиск", "QR", "План"]);
  await page.goto("/users");
  await page.getByRole("row").nth(1).click();
  const card = page.getByRole("complementary", { name: "Карточка" });
  await expect(card).toBeVisible();
  const box = await card.boundingBox();
  expect(box!.width).toBeGreaterThan(350);
});
