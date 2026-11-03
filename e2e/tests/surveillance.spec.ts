import { expect, test } from "./fixtures";
import { loginAdmin, unique } from "./helpers";

// ADR-0027: сохраняем реальное подключение через API, недоступность потока показываем
// воспроизводимой ошибкой. Физическая камера для этого сценария не требуется.
test("камера на плане: настройка адреса, просмотр и повторное открытие", async ({ page }, testInfo) => {
  await loginAdmin(page);
  const headers = { "X-Requested-With": "app" };
  const building = await (await page.request.post("/api/buildings", { headers, data: { name: unique("Видео-") } })).json();
  const floor = await (await page.request.post(`/api/buildings/${building.id}/floors`, { headers, data: { name: "Первый этаж" } })).json();
  const catalog = await (await page.request.get("/api/catalog")).json();
  const type = catalog.types.find((t: { name: string }) => t.name === "Камера цилиндрическая");
  expect(type).toBeTruthy();
  const placed = await page.request.post(`/api/floors/${floor.id}/items/changes`, {
    headers, data: { create: [{ type_id: type.id, x: 1000, y: 1000, label: "Камера у входа" }] },
  });
  expect(placed.ok()).toBeTruthy();
  const item = (await placed.json()).items[0];
  await page.route(`**/api/surveillance/cameras/${item.id}/preview`, (route) => route.fulfill({
    status: 504, contentType: "application/json", body: JSON.stringify({ error: { message: "Камера не отвечает. Проверьте подключение." } }),
  }));
  await page.goto(`/plan/${building.id}/${floor.id}?mode=place`);
  const marker = page.locator(`[data-item="${item.id}"]`).first();
  await expect(marker).toBeVisible();
  const box = (await marker.boundingBox())!;
  // Выбор предмета обрабатывается SVG-планом по координатам (сами глифы pointer-events=none).
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  const dialog = page.getByRole("dialog", { name: "Камера у входа" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Настроить подключение" }).click();
  await dialog.getByLabel("Адрес потока RTSP").fill("rtsp://192.0.2.10:554/stream1");
  await dialog.getByLabel("Логин камеры").fill("camera-test");
  await dialog.getByLabel("Пароль камеры").fill("test-secret");
  await dialog.getByRole("button", { name: "Сохранить и открыть видео" }).click();
  await expect(dialog.getByRole("status")).toHaveText("Камера не отвечает. Проверьте подключение.");
  await dialog.getByRole("button", { name: "Закрыть" }).click();
  await page.getByRole("button", { name: "Видео с камеры" }).click();
  await dialog.getByRole("button", { name: "Настройки" }).click();
  await expect(dialog.getByLabel("Адрес потока RTSP")).toHaveValue("rtsp://192.0.2.10:554/stream1");
  await expect(dialog.getByLabel("Пароль камеры")).toHaveValue("");
  await expect(dialog.getByLabel("Пароль камеры")).toHaveAttribute("placeholder", /Сохранён/);
  await page.screenshot({ path: testInfo.outputPath("camera-settings.png") });
});
