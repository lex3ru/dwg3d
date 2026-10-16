import { expect, test } from "@playwright/test";
import { loginAdmin, unique } from "./helpers";

// Приёмка этапа 2 (10.1): С1 «Здание из чертежа» — загрузка, разбиение на этажи, перевод.
// На стенде проверяется и на «Бастионе» (docs/ACCEPTANCE.md); здесь — на чертеже из теста,
// чтобы сценарий шёл и там, где чертежей заказчика нет.

// DXF R12: два этажа рядом, стены двойными линиями, перегородка с дверью, номера помещений
function dxf(): string {
  const out: string[] = ["0", "SECTION", "2", "ENTITIES"];
  const line = (layer: string, x0: number, y0: number, x1: number, y1: number) =>
    out.push("0", "LINE", "8", layer, "10", String(x0), "20", String(y0), "30", "0", "11", String(x1), "21", String(y1), "31", "0");
  const ring = (layer: string, pts: [number, number][]) => pts.forEach((p, i) => line(layer, ...p, ...pts[(i + 1) % pts.length]!));
  const text = (x: number, y: number, h: number, value: string) =>
    out.push("0", "TEXT", "8", "0", "10", String(x), "20", String(y), "30", "0", "40", String(h), "1", value);
  const floor = (ox: number, title: string, a: string, b: string) => {
    ring("Стены", [[ox, 0], [ox + 9000, 0], [ox + 9000, 6000], [ox, 6000]]);
    ring("Стены", [[ox + 300, 300], [ox + 8700, 300], [ox + 8700, 5700], [ox + 300, 5700]]);
    ring("Перегородки", [[ox + 5000, 300], [ox + 5120, 300], [ox + 5120, 2000], [ox + 5000, 2000]]);
    ring("Перегородки", [[ox + 5000, 2900], [ox + 5120, 2900], [ox + 5120, 5700], [ox + 5000, 5700]]);
    text(ox + 2500, 3000, 300, a);
    text(ox + 7000, 3000, 300, b);
    text(ox + 2000, 6800, 500, title);
  };
  floor(0, "План 1-го этажа", "101", "102");
  floor(20000, "План 2-го этажа", "201", "202");
  out.push("0", "ENDSEC", "0", "EOF");
  return out.join("\n") + "\n";
}

test("С1: чертёж с двумя этажами — части, этажи, перевод в планы с помещениями", async ({ page }) => {
  test.setTimeout(120_000);
  await loginAdmin(page);
  const b = await (await page.request.post("/api/buildings", { headers: { "X-Requested-With": "app" }, data: { name: unique("С1-") } })).json();
  await page.goto(`/buildings?b=${b.id}`);
  await page.getByLabel("Файл чертежа").setInputFiles({ name: "планы.dxf", mimeType: "application/dxf", buffer: Buffer.from(dxf()) });
  await expect(page.getByText("выберите этажи")).toBeVisible({ timeout: 60_000 });
  // части названы по подписям чертежа, этажи предложены
  await expect(page.getByText("План 1-го этажа")).toBeVisible();
  await expect(page.getByLabel("Название нового этажа для части План 2-го этажа")).toHaveValue("2 этаж");
  await page.getByRole("button", { name: "Перевести в планы" }).click();
  await expect(page.getByText("2 этаж — открыть план")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("без замечаний проверки").first()).toBeVisible();

  const building = await (await page.request.get(`/api/buildings/${b.id}`)).json();
  expect(building.floors.map((f: { name: string }) => f.name)).toEqual(["1 этаж", "2 этаж"]);
  const plan = await (await page.request.get(`/api/floors/${building.floors[0].id}/plan`)).json();
  expect(plan.rooms.map((r: { number: string }) => r.number).sort()).toEqual(["101", "102"]);
  expect(plan.issues).toEqual([]);

  await page.getByText("1 этаж — открыть план").click();
  await expect(page.getByRole("img", { name: "План этажа" }).getByText("101")).toBeVisible();
});
