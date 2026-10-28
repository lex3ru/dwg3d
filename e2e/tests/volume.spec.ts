import { expect, test, type Page } from "./fixtures";
import { loginAdmin } from "./helpers";
import { xlsx } from "./xlsx";

// Итоговая приёмка (10.3): быстродействие 8.2 на стенде с объёмами 8.1 — 20 зданий, 10 000
// помещений, 200 000 предметов (на этаже «Объём-01 · 1 этаж» — 2 000), 50 000 единиц, 5 000
// позиций остатков, 20 000 документов. Стенд: `python -m app sample volume` на отдельной базе
// (docs/ACCEPTANCE.md, этап 10). Без E2E_VOLUME=1 сценарии пропускаются.

const H = { "X-Requested-With": "app" };
const on = !!process.env.E2E_VOLUME;
const times: string[] = [];

function note(what: string, ms: number, limit: number) {
  const line = `${what}: ${ms} мс (норма ${limit} мс)`;
  times.push(line);
  console.log(`8.2 · ${line}`);
  expect(ms, what).toBeLessThan(limit);
}

async function timed<T>(fn: () => Promise<T>): Promise<[T, number]> {
  const t = Date.now();
  const out = await fn();
  return [out, Date.now() - t];
}

async function stand(page: Page) {
  const all = (await (await page.request.get("/api/buildings")).json()).items as { id: string; name: string }[];
  const first = all.find((b) => b.name === "Объём-01");
  test.skip(!first, "на стенде нет зданий «Объём-…» — python -m app sample volume");
  const info = await (await page.request.get(`/api/buildings/${first!.id}`)).json();
  return { building: first!.id, floors: info.floors as { id: string; name: string }[], all };
}

test.describe("8.2 на объёмах 8.1", () => {
  test.skip(!on, "нет E2E_VOLUME=1");
  test.afterAll(() => console.log(`\n8.2 на стенде объёмов:\n${times.map((t) => `  ${t}`).join("\n")}`));

  test("объёмы стенда не меньше 8.1", async ({ page }) => {
    await loginAdmin(page);
    const s = await stand(page);
    expect(s.all.filter((b) => b.name.startsWith("Объём-")).length).toBeGreaterThanOrEqual(20);
    const units = await (await page.request.get("/api/inventory/units", { params: { limit: 1 } })).json();
    expect(units.total).toBeGreaterThanOrEqual(50_000);
    const items = await (await page.request.get(`/api/floors/${s.floors[0]!.id}/items`)).json();
    expect(items.items.length).toBeGreaterThanOrEqual(2_000);
  });

  test("план этажа с 2 000 предметов — 2 с, 3D — 3 с", async ({ page }) => {
    await loginAdmin(page);
    const s = await stand(page);
    const floor = s.floors[0]!;
    // на плане — предметы слоёв, видимых сразу («Освещение» по умолчанию скрыт)
    const tree = await (await page.request.get("/api/catalog")).json();
    const shown = new Set(tree.layers.filter((l: { visible: boolean }) => l.visible).map((l: { id: string }) => l.id));
    const layerOf = new Map(tree.types.map((t: { id: string; layer_id: string }) => [t.id, t.layer_id]));
    const items = (await (await page.request.get(`/api/floors/${floor.id}/items`)).json()).items as { type_id: string }[];
    const visible = items.filter((i) => shown.has(layerOf.get(i.type_id))).length;
    expect(items.length).toBeGreaterThanOrEqual(2000);
    const [, plan] = await timed(async () => {
      await page.goto(`/plan/${s.building}/${floor.id}?mode=place`);
      await expect(page.getByRole("img", { name: "План этажа" }).locator("[data-item]")).toHaveCount(visible, { timeout: 10_000 });
    });
    note("план этажа с 2 000 предметов", plan, 2000);
    const [, view3d] = await timed(async () => {
      await page.goto(`/plan/${s.building}/${floor.id}?view=3d`);
      await page.waitForFunction(() => {
        const c = document.querySelector("canvas");
        return !!c && c.width > 0;
      });
    });
    note("3D-вид этажа", view3d, 3000);
  });

  test("поиск, карточка, переход между экранами — 1 с", async ({ page }) => {
    await loginAdmin(page);
    await stand(page);
    const some = (await (await page.request.get("/api/inventory/units", { params: { limit: 1, sort: "number" } })).json()).items[0];
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Главная" })).toBeVisible();
    const [, search] = await timed(async () => {
      await page.getByRole("searchbox").first().fill(some.number);
      await expect(page.getByRole("link", { name: new RegExp(`№ ${some.number}`) }).first()).toBeVisible();
    });
    note("поиск по инвентарному номеру", search, 1000);

    const menu = page.getByRole("navigation", { name: "Разделы" });
    for (const [link, heading] of [["Имущество", "Имущество"], ["Документы", "Документы"], ["Склад", "Склад"], ["Инвентаризация", "Инвентаризация"]] as const) {
      const [, ms] = await timed(async () => {
        await menu.getByRole("link", { name: link }).click();
        await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
        await expect(page.getByText("Загрузка…")).toHaveCount(0);
      });
      note(`переход на «${link}»`, ms, 1000);
    }
    await menu.getByRole("link", { name: "Имущество" }).click();
    const row = page.getByRole("row").nth(1);
    await expect(row).toBeVisible();
    const [, card] = await timed(async () => {
      await row.click();
      await expect(page.getByRole("complementary", { name: "Карточка" }).getByRole("heading", { level: 2 })).toBeVisible();
      await expect(page.getByRole("complementary", { name: "Карточка" }).getByText("Загрузка…")).toHaveCount(0);
    });
    note("открытие карточки из реестра 50 000 единиц", card, 1000);
  });

  test("документ на 100 строк проводится за 2 с, Excel на 1 000 строк проверяется за 10 с", async ({ page }) => {
    await loginAdmin(page);
    const s = await stand(page);
    const tree = await (await page.request.get("/api/catalog")).json();
    const pieces = tree.types.filter((t: { accounting: string; archived: boolean }) => t.accounting === "piece" && !t.archived);
    const warehouse = (await (await page.request.get("/api/inventory/places")).json()).warehouses?.[0];
    const to = warehouse?.key ?? `w:${warehouse?.id}`;
    const lines = Array.from({ length: 100 }, (_, i) => ({ type_id: pieces[i % pieces.length].id, qty: 1, price: 1000 + i }));
    const doc = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind: "receipt", header: { to_place: to }, lines } })).json();
    const [posted, post] = await timed(() => page.request.post(`/api/inventory/documents/${doc.id}/post`, { headers: H, data: { version: doc.version } }));
    expect(posted.ok(), await posted.text()).toBeTruthy();
    note("проведение документа на 100 строк", post, 2000);

    const head = ["Инвентарный номер", "Наименование", "Модель", "Слой", "Вид учёта", "Количество", "Ед. изм.", "Серийный номер", "Этаж", "Помещение", "Название помещения", "Ответственный", "Подразделение", "Состояние", "Цена за ед., ₽", "Дата ввода", "Срок службы, мес.", "Стоимость, ₽", "Примечание"];
    const rows: (string | number | null)[][] = [head];
    for (let i = 0; i < 1000; i++) {
      const t = pieces[i % pieces.length];
      rows.push(["", t.name, "", "", "поштучно", 1, "шт.", `SN-${i}`, "1 этаж", `1${String((i % 21) + 1).padStart(2, "0")}`, "", "", "", "в работе", 1000 + i, "01.03.2024", 60, null, ""]);
    }
    const [checked, check] = await timed(() =>
      page.request.post("/api/inventory/import", {
        headers: H,
        multipart: { building_id: s.building, mapping: "{}", apply: "false", file: { name: "имущество.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: xlsx("Имущество", rows) } },
      }),
    );
    expect(checked.ok(), await checked.text()).toBeTruthy();
    note("проверка Excel на 1 000 строк", check, 10_000);
  });

  test("отчёт и выгрузка по 50 000 единиц — 30 с", async ({ page }) => {
    test.setTimeout(300_000);
    await loginAdmin(page);
    const s = await stand(page);
    for (const report of ["registry.xlsx", "cost.xlsx", "balances.xlsx"]) {
      const [r, ms] = await timed(() => page.request.get(`/api/reports/${report}`, { timeout: 120_000 }));
      expect(r.ok(), await r.text()).toBeTruthy();
      note(`отчёт ${report}`, ms, 30_000);
    }
    const exportOf = async (building?: string) => {
      const started = await (await page.request.post(`/api/reports/exports${building ? `?building_id=${building}` : ""}`, { headers: H })).json();
      for (;;) {
        const j = await (await page.request.get(`/api/system/tasks/${started.job_id}`)).json();
        if (j.status === "done" || j.status === "failed") return j;
        await page.waitForTimeout(250);
      }
    };
    const [one, ms] = await timed(() => exportOf(s.building));
    expect(one.status, one.error).toBe("done");
    note(`полная выгрузка здания (${Math.round(one.result.size / 1e6)} МБ)`, ms, 30_000);
    // все 20 зданий — справочно: в архиве ещё 200 000 предметов, 20 000 документов и журнал
    const [all, total] = await timed(() => exportOf());
    expect(all.status, all.error).toBe("done");
    times.push(`полная выгрузка всех 20 зданий (${Math.round(all.result.size / 1e6)} МБ): ${total} мс (справочно)`);
  });

  test("QR-метка → карточка на телефоне — 2 с @телефон", async ({ page }) => {
    test.skip(!on, "нет E2E_VOLUME=1");
    await loginAdmin(page);
    await stand(page);
    const some = (await (await page.request.get("/api/inventory/units", { params: { limit: 1 } })).json()).items[0];
    const unit = await (await page.request.get(`/api/inventory/units/${some.id}`)).json();
    const [, ms] = await timed(async () => {
      await page.goto(`/q/${unit.label_code}`);
      await expect(page.getByRole("heading", { name: unit.title ?? some.title }).first()).toBeVisible();
    });
    note("QR-метка → карточка на телефоне", ms, 2000);
  });
});
