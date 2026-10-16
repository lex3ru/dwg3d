import { expect, test } from "@playwright/test";
import { loginAdmin } from "./helpers";

// 8.2: план этажа открывается за 2 с, 3D-вид — за 3 с. Нужно здание E2E_PERF_BUILDING
// (например, «Поликлиника»: python -m app sample polyclinic); без него тест пропускается.
const building = process.env.E2E_PERF_BUILDING;

test("8.2: план этажа за 2 с, 3D за 3 с", async ({ page }) => {
  test.skip(!building, "нет E2E_PERF_BUILDING");
  await loginAdmin(page);
  const info = await (await page.request.get(`/api/buildings/${building}`)).json();
  for (const floor of info.floors) {
    const t0 = Date.now();
    await page.goto(`/plan/${building}/${floor.id}`);
    await expect(page.getByRole("img", { name: "План этажа" }).locator("text").first()).toBeVisible();
    const plan = Date.now() - t0;
    const t1 = Date.now();
    await page.goto(`/plan/${building}/${floor.id}?view=3d`);
    await page.waitForFunction(() => {
      const c = document.querySelector("canvas");
      return !!c && c.width > 0;
    });
    await page.waitForTimeout(50);
    const view3d = Date.now() - t1;
    console.log(`${floor.name}: план ${plan} мс, 3D ${view3d} мс`);
    expect(plan).toBeLessThan(2000);
    expect(view3d).toBeLessThan(3000);
  }
});

// 8.2 для этапа 4: этаж с 2 000 предметов открывается за 2 с; перемещение предмета и
// вращение 3D — не меньше 30 кадров в секунду (3D — с E2E_GPU=1, на видеокарте машины)
test("8.2: 2 000 предметов на этаже — открытие и плавность", async ({ page }) => {
  test.setTimeout(120_000);
  await loginAdmin(page);
  const H = { "X-Requested-With": "app" };
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: `8.2-${Date.now().toString(36)}` } })).json();
  const floor = await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "1 этаж" } })).json();
  const wall = (id: string, a: string, z: string) => ({ id, a, b: z, thickness: 400, kind: "bearing" });
  await page.request.put(`/api/floors/${floor.id}/plan`, {
    headers: H,
    data: {
      plan_version: 1,
      plan: {
        nodes: { a: [0, 0], b: [62000, 0], c: [62000, 42000], d: [0, 42000] },
        walls: [wall("w1", "a", "b"), wall("w2", "b", "c"), wall("w3", "c", "d"), wall("w4", "d", "a")],
        rooms: [{ id: "new-1", x: 31000, y: 21000, number: "1", name: "Зал" }],
      },
    },
  });
  const tree = await (await page.request.get("/api/catalog")).json();
  const kinds = tree.types.filter((t: { layer_id: string | null; mount: string }) => t.layer_id && t.mount === "floor").slice(0, 20);
  const create = [];
  for (let i = 0; i < 2000; i++) create.push({ type_id: kinds[i % kinds.length].id, x: 1000 + (i % 50) * 1200, y: 1000 + Math.floor(i / 50) * 1000, angle: (i * 15) % 360 });
  const r = await page.request.post(`/api/floors/${floor.id}/items/changes`, { headers: H, data: { create } });
  expect(r.ok()).toBeTruthy();

  const t0 = Date.now();
  await page.goto(`/plan/${b.id}/${floor.id}?mode=place`);
  await expect(page.getByRole("img", { name: "План этажа" }).locator("[data-item]")).toHaveCount(2000);
  const open = Date.now() - t0;

  // кадры в секунду, пока что-то происходит
  const fps = async (action: () => Promise<void>) => {
    await page.evaluate(() => {
      const w = window as unknown as { __frames: number; __run: boolean };
      w.__frames = 0;
      w.__run = true;
      const tick = () => {
        w.__frames++;
        if (w.__run) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    const s = Date.now();
    await action();
    const frames = await page.evaluate(() => {
      const w = window as unknown as { __frames: number; __run: boolean };
      w.__run = false;
      return w.__frames;
    });
    return (frames * 1000) / (Date.now() - s);
  };

  await page.getByRole("tab", { name: "Расстановка" }).click();
  const svg = page.getByRole("img", { name: "План этажа" });
  const target = svg.locator("[data-item]").nth(1020);
  const box = (await target.boundingBox())!;
  const [x, y] = [box.x + box.width / 2, box.y + box.height / 2];
  const drag2d = await fps(async () => {
    await page.mouse.move(x, y);
    await page.mouse.down();
    for (let k = 1; k <= 60; k++) await page.mouse.move(x + k * 3, y + Math.sin(k / 5) * 20);
    await page.mouse.up();
  });

  // 3D мерится видеокартой (E2E_GPU=1); программная отрисовка headless-браузера — не мерило
  let orbit3d = NaN;
  if (process.env.E2E_GPU) {
    await page.getByRole("radio", { name: "3D" }).click();
    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible();
    await page.waitForTimeout(1500);
    const c = (await canvas.boundingBox())!;
    orbit3d = await fps(async () => {
      await page.mouse.move(c.x + c.width / 2, c.y + c.height / 2);
      await page.mouse.down();
      for (let k = 1; k <= 60; k++) await page.mouse.move(c.x + c.width / 2 + k * 4, c.y + c.height / 2 + k);
      await page.mouse.up();
    });
  }
  console.log(`2 000 предметов: открытие ${open} мс, перетаскивание ${drag2d.toFixed(0)} кадр/с, 3D ${orbit3d.toFixed(0)} кадр/с`);
  expect(open).toBeLessThan(2000);
  expect(drag2d).toBeGreaterThanOrEqual(30);
  if (process.env.E2E_GPU) expect(orbit3d).toBeGreaterThanOrEqual(30);
});
