import { expect, test } from "./fixtures";
import { loginAdmin, unique } from "./helpers";

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

// 8.2 для этапа 7: пересчёт зоны обзора при движении камеры — 0,2 с, освещённость этажа — 10 с.
// Этаж 60 × 30 м: 40 кабинетов 6 × 7,5 м с назначением, по 4 светильника, 30 камер.
test("8.2: расчёты — зона обзора 0,2 с, освещённость этажа 10 с", async ({ page }) => {
  const H = { "X-Requested-With": "app" };
  await loginAdmin(page);
  const tree = await (await page.request.get("/api/catalog")).json();
  const type = (name: string) => tree.types.find((t: { name: string }) => t.name === name).id as string;
  const office = tree.purposes.find((p: { name: string }) => p.name === "Кабинет врача").id;
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: unique("8.2-расчёты-") } })).json();
  const f = await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "1 этаж" } })).json();
  const nodes: Record<string, [number, number]> = {};
  const walls: object[] = [];
  const rooms: object[] = [];
  for (let i = 0; i <= 10; i++) for (let j = 0; j <= 4; j++) nodes[`n${i}_${j}`] = [i * 6000, j * 7500];
  for (let i = 0; i <= 10; i++) for (let j = 0; j < 4; j++) walls.push({ id: `v${i}_${j}`, a: `n${i}_${j}`, b: `n${i}_${j + 1}`, thickness: 200 });
  for (let j = 0; j <= 4; j++) for (let i = 0; i < 10; i++) walls.push({ id: `h${i}_${j}`, a: `n${i}_${j}`, b: `n${i + 1}_${j}`, thickness: 200 });
  for (let i = 0; i < 10; i++) for (let j = 0; j < 4; j++) rooms.push({ id: `new-${i}-${j}`, x: i * 6000 + 3000, y: j * 7500 + 3750, number: `${j + 1}${String(i + 1).padStart(2, "0")}`, name: "Кабинет", purpose_id: office });
  const saved = await page.request.put(`/api/floors/${f.id}/plan`, { headers: H, data: { plan_version: 1, plan: { nodes, walls, rooms } } });
  expect(saved.ok()).toBeTruthy();
  const lamp = type("Светильник светодиодный 600×600");
  const cam = type("Камера купольная");
  const create: object[] = [];
  for (let i = 0; i < 10; i++)
    for (let j = 0; j < 4; j++) {
      for (const [dx, dy] of [[1500, 1900], [4500, 1900], [1500, 5600], [4500, 5600]]) create.push({ type_id: lamp, x: i * 6000 + dx!, y: j * 7500 + dy! });
      if ((i * 4 + j) % 4 < 3) create.push({ type_id: cam, x: i * 6000 + 500, y: j * 7500 + 7000, angle: 225 });
    }
  const r = await page.request.post(`/api/floors/${f.id}/items/changes`, { headers: H, data: { create } });
  expect(r.ok()).toBeTruthy();
  const items = (await r.json()).items;
  const cams = items.filter((i: { type_id: string }) => i.type_id === cam);
  expect(cams).toHaveLength(30);

  const run = async (key: string, sent?: object[]) => {
    const t = Date.now();
    const res = await page.request.post(`/api/calc/${key}/floors/${f.id}`, { headers: H, data: { items: sent ?? null, options: {} } });
    expect(res.ok()).toBeTruthy();
    return { ms: Date.now() - t, body: await res.json() };
  };
  const light = await run("light");
  expect(light.body.table.rows).toHaveLength(40);
  // камеру тащат: пересчёт по расстановке с экрана, несколько раз подряд
  const calls: { ms: number; body: { took_ms: number } }[] = [];
  for (let k = 0; k < 5; k++) {
    const res = await run("camera", cams.map((c: { x: number }, n: number) => (n === 0 ? { ...c, x: c.x + k * 300 } : c)));
    expect(res.body.table.rows).toHaveLength(30);
    calls.push(res);
  }
  const times = calls.map((c) => c.ms);
  const zone = Math.max(...times.slice(1));
  console.log(`расчёты: освещённость этажа (40 помещений, 160 светильников) ${light.ms} мс, зона обзора (30 камер) ${zone} мс`);
  // замер — у клиента; рядом время расчёта на сервере (took_ms): разница — сеть, очередь и
  // сериализация ответа (DWG3D-10)
  const pairs = calls.map((c) => `${c.ms}/${c.body.took_ms}`).join(", ");
  console.log(`  клиент/сервер, мс: освещённость ${light.ms}/${light.body.took_ms}; зона обзора ${pairs}`);
  expect(light.ms).toBeLessThan(10_000);
  expect(zone).toBeLessThan(200);
});
