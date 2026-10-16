import { expect, test, type Page } from "@playwright/test";
import { deflateSync } from "node:zlib";
import { login, loginAdmin, unique } from "./helpers";

// Приёмка этапа 1 (10.1): С2 «План с нуля» и С3 «Перепланировка»; 3D-вид; печать;
// «просмотр» видит план только для чтения.

const H = { "X-Requested-With": "app" };

async function building(page: Page, name: string, floors = ["1 этаж"]) {
  const b = await page.request.post("/api/buildings", { headers: H, data: { name } });
  expect(b.status()).toBe(201);
  const id = (await b.json()).id as string;
  const ids: string[] = [];
  for (const floor of floors) {
    const f = await page.request.post(`/api/buildings/${id}/floors`, { headers: H, data: { name: floor } });
    ids.push((await f.json()).id);
  }
  return { id, floors: ids };
}

// Картинка-подложка: белый PNG с чёрной рамкой (скан плана)
function png(width: number, height: number): Buffer {
  const raw = Buffer.alloc((width * 3 + 1) * height, 255);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 3 + 1)] = 0;
    for (let x = 0; x < width; x++) {
      if (x < 4 || y < 4 || x >= width - 4 || y >= height - 4) raw.fill(0, y * (width * 3 + 1) + 1 + x * 3, y * (width * 3 + 1) + 4 + x * 3);
    }
  }
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const b of buf) c = crcTable[(c ^ b) & 0xff]! ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const c = Buffer.alloc(4);
    c.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, c]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}

async function planBox(page: Page) {
  const box = await page.getByRole("img", { name: "План этажа" }).boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

test("С2: этаж с нуля — подложка, масштаб, стены, двери, окна, помещение", async ({ page }) => {
  await loginAdmin(page);
  const b = await building(page, unique("С2-"));
  await page.goto(`/plan/${b.id}/${b.floors[0]}`);
  await expect(page.getByRole("button", { name: "Сохранить план" })).toBeDisabled();

  // подложка и масштаб по двум точкам
  await page.locator('input[type="file"]').setInputFiles({ name: "скан.png", mimeType: "image/png", buffer: png(400, 300) });
  await expect(page.getByText("Подложка положена")).toBeVisible();
  const box = await planBox(page);
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.getByRole("button", { name: "Масштаб по двум точкам" }).click();
  await page.mouse.click(cx - 150, cy);
  await page.mouse.click(cx + 150, cy);
  await page.getByLabel("Расстояние, мм").fill("6000");
  await page.getByRole("button", { name: "Применить" }).click();

  // стены цепочкой: прямоугольник, замыкается на начале
  await page.getByRole("button", { name: /^Стена/ }).click();
  const pts: [number, number][] = [[cx - 150, cy - 100], [cx + 150, cy - 100], [cx + 150, cy + 100], [cx - 150, cy + 100], [cx - 150, cy - 100]];
  for (const [x, y] of pts) await page.mouse.click(x, y);
  await page.keyboard.press("Escape");
  await expect(page.getByText(/Стен 4,/)).toBeVisible();

  // дверь и окно
  await page.getByRole("button", { name: /^Дверь/ }).click();
  await page.mouse.click(cx, cy + 100);
  await page.getByRole("button", { name: /^Окно/ }).click();
  await page.mouse.click(cx, cy - 100);
  await page.keyboard.press("Escape");
  await expect(page.getByText(/проёмов 2/)).toBeVisible();

  // помещение из замкнутых стен — подписать
  await expect(page.getByText(/Помещений без подписи: 1/)).toBeVisible();
  await page.getByRole("button", { name: /^Подпись помещения/ }).click();
  await page.mouse.click(cx, cy);
  await page.getByLabel("Номер", { exact: true }).fill("101");
  await page.getByLabel("Номер", { exact: true }).press("Enter");
  await page.getByLabel("Название", { exact: true }).fill("Регистратура");
  await page.getByLabel("Название", { exact: true }).press("Enter");

  await page.getByRole("button", { name: "Сохранить план" }).click();
  await expect(page.getByText("План сохранён.")).toBeVisible();
  const plan = await (await page.request.get(`/api/floors/${b.floors[0]}/plan`)).json();
  expect(plan.rooms).toHaveLength(1);
  expect(plan.rooms[0].number).toBe("101");
  expect(plan.rooms[0].area).toBeGreaterThan(1);
  expect(plan.plan.underlay.file_id).toBeTruthy();

  // 3D строится сам
  await page.getByRole("radio", { name: "оба" }).click();
  await expect(page.locator("canvas")).toBeVisible();

  // печать и выгрузка
  const pdf = await page.request.get(`/api/floors/${b.floors[0]}/export.pdf?paper=A4`);
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  const dxf = await page.request.get(`/api/floors/${b.floors[0]}/export.dxf`);
  expect(await dxf.text()).toContain("Регистратура");
});

test("С3: снесли перегородку — система спрашивает, какое помещение остаётся", async ({ page }) => {
  await loginAdmin(page);
  const b = await building(page, unique("С3-"), ["2 этаж"]);
  const nodes = { a: [0, 0], e: [3000, 0], b: [6000, 0], c: [6000, 4000], f: [3000, 4000], d: [0, 4000] };
  const wall = (id: string, a: string, bb: string, t = 300, kind = "bearing") => ({ id, a, b: bb, thickness: t, kind });
  const saved = await page.request.put(`/api/floors/${b.floors[0]}/plan`, {
    headers: H,
    data: {
      plan_version: 1,
      plan: {
        nodes,
        walls: [wall("w1", "a", "e"), wall("w2", "e", "b"), wall("w3", "b", "c"), wall("w4", "c", "f"), wall("w5", "f", "d"), wall("w6", "d", "a"), wall("p", "e", "f", 120, "partition")],
        rooms: [
          { id: "new-1", x: 1500, y: 2000, number: "214", name: "Кабинет" },
          { id: "new-2", x: 4500, y: 2000, number: "215", name: "Кабинет" },
        ],
      },
    },
  });
  expect(saved.status()).toBe(200);

  await page.goto(`/plan/${b.id}/${b.floors[0]}`);
  const box = await planBox(page);
  // перегородка — посередине этажа, который вписан в окно
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2 + 30);
  await expect(page.getByRole("heading", { name: "Стена · перегородка" })).toBeVisible();
  await page.keyboard.press("Delete");
  await page.getByRole("button", { name: "Сохранить план" }).click();
  const dialog = page.getByRole("dialog", { name: "Сохранить план?" });
  await expect(dialog).toContainText("Помещения 214 Кабинет и 215 Кабинет станут одним");
  await dialog.getByRole("radio", { name: /215 Кабинет/ }).check();
  await dialog.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByText("План сохранён.")).toBeVisible();

  const plan = await (await page.request.get(`/api/floors/${b.floors[0]}/plan`)).json();
  expect(plan.rooms.map((r: { number: string }) => r.number)).toEqual(["215"]);
  await page.goto("/journal?action=floor.");
  await expect(page.getByText(/объединены: 214 Кабинет \+ 215 Кабинет → 215 Кабинет/).first()).toBeVisible();
});

test("«просмотр» видит план выданного здания только для чтения", async ({ page, browser }) => {
  await loginAdmin(page);
  const b = await building(page, unique("Просмотр-"));
  await page.request.put(`/api/floors/${b.floors[0]}/plan`, {
    headers: H,
    data: { plan_version: 1, plan: { nodes: { a: [0, 0], b: [4000, 0], c: [4000, 3000], d: [0, 3000] }, walls: [["w1", "a", "b"], ["w2", "b", "c"], ["w3", "c", "d"], ["w4", "d", "a"]].map(([id, a, bb]) => ({ id, a, b: bb, thickness: 200 })), rooms: [{ id: "new", x: 2000, y: 1500, number: "7", name: "Палата" }] } },
  });
  const name = unique("view");
  await page.request.post("/api/users", { headers: H, data: { login: name, full_name: "Смотрящий С. С.", role: "viewer", building_ids: [b.id], password: "Temporary-pass-1" } });

  const viewer = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage();
  await login(viewer, name, "Temporary-pass-1");
  await viewer.getByLabel("Текущий пароль").fill("Temporary-pass-1");
  await viewer.getByLabel("Новый пароль", { exact: true }).fill("Viewer-pass-12");
  await viewer.getByLabel("Новый пароль ещё раз").fill("Viewer-pass-12");
  await viewer.getByRole("button", { name: "Сменить и продолжить" }).click();
  // пароль сменён — система сама открыла план
  await expect(viewer.getByRole("navigation", { name: "Разделы" }).first()).toBeVisible();
  await viewer.goto(`/plan/${b.id}`);
  await expect(viewer.getByRole("img", { name: "План этажа" })).toBeVisible();
  await expect(viewer.getByText("Палата")).toBeVisible();
  await expect(viewer.getByRole("button", { name: "Сохранить план" })).toHaveCount(0);
  await expect(viewer.getByRole("complementary", { name: "Инструменты" })).toHaveCount(0);
  const put = await viewer.request.put(`/api/floors/${b.floors[0]}/plan`, { headers: H, data: { plan_version: 2, plan: {} } });
  expect(put.status()).toBe(403);
});
