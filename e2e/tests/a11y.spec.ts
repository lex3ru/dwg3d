import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "./fixtures";
import { loginAdmin, unique } from "./helpers";

// Удобство (8.6 п. 2): контраст текста не ниже 4,5 : 1 и прочие правила WCAG 2 AA (axe) —
// на каждом разделе, в светлой и тёмной теме; на телефоне кнопки и поля не меньше 44 px.

const PAGES = ["/", "/projects", "/property", "/warehouse", "/documents", "/inventory", "/reports", "/catalog", "/purposes", "/buildings", "/users", "/links", "/journal", "/settings", "/help", "/scan"];

const H = { "X-Requested-With": "app" };

// План для проверки — своё здание, на чистой базе других нет: два кабинета с дверью и стол
async function plan(page: Page) {
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: unique("Доступность-") } })).json();
  const floor = await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "1 этаж" } })).json();
  const wall = (id: string, a: string, z: string, thickness = 300, kind = "bearing") => ({ id, a, b: z, thickness, kind });
  const saved = await page.request.put(`/api/floors/${floor.id}/plan`, {
    headers: H,
    data: {
      plan_version: 1,
      plan: {
        nodes: { a: [0, 0], b: [4000, 0], c: [8000, 0], d: [8000, 5000], e: [4000, 5000], f: [0, 5000] },
        walls: [
          wall("w1", "a", "b"), wall("w2", "b", "c"), wall("w3", "c", "d"), wall("w4", "d", "e"), wall("w5", "e", "f"), wall("w6", "f", "a"),
          wall("p1", "b", "e", 120, "partition"),
        ],
        openings: [{ id: "o1", wall: "p1", kind: "door", at: 2500, width: 900, height: 2100 }],
        rooms: [
          { id: "new-1", x: 2000, y: 2500, number: "101", name: "Кабинет" },
          { id: "new-2", x: 6000, y: 2500, number: "102", name: "Кабинет" },
        ],
      },
    },
  });
  expect(saved.ok()).toBeTruthy();
  const tree = await (await page.request.get("/api/catalog")).json();
  const desk = tree.types.find((t: { name: string }) => t.name === "Стол письменный 1200×600").id;
  const placed = await page.request.post(`/api/floors/${floor.id}/items/changes`, { headers: H, data: { create: [{ type_id: desk, x: 2000, y: 3500 }] } });
  expect(placed.ok()).toBeTruthy();
  return `/plan/${b.id}/${floor.id}?mode=place`;
}

async function settle(page: Page) {
  await expect(page.getByText("Загрузка…")).toHaveCount(0, { timeout: 10_000 });
  await page.waitForTimeout(300);
}

for (const scheme of ["light", "dark"] as const) {
  test(`WCAG 2 AA на всех разделах — ${scheme === "light" ? "светлая" : "тёмная"} тема`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.emulateMedia({ colorScheme: scheme });
    await loginAdmin(page);
    const found: string[] = [];
    for (const url of [...PAGES, await plan(page)]) {
      await page.goto(url);
      await settle(page);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).exclude("canvas").analyze();
      for (const v of r.violations.filter((x) => x.impact === "serious" || x.impact === "critical"))
        found.push(`${url} · ${v.id} (${v.impact}): ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join("; ")}${v.nodes.length > 3 ? ` и ещё ${v.nodes.length - 3}` : ""}`);
    }
    console.log(found.join("\n"));
    expect(found, found.join("\n")).toEqual([]);
  });
}

test("на телефоне кнопки и поля не меньше 44 px @телефон", async ({ page }) => {
  test.setTimeout(120_000);
  await loginAdmin(page);
  const small: string[] = [];
  for (const url of ["/", "/property", "/warehouse", "/documents", "/inventory", "/scan", "/help", await plan(page)]) {
    await page.goto(url);
    await settle(page);
    const bad = await page.evaluate(() => {
      const out: string[] = [];
      const sel = "button, [role=button], [role=tab], select, input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]), a[class*='inline-flex']";
      for (const el of Array.from(document.querySelectorAll<HTMLElement>(sel))) {
        // поле внутри подписи-рамки нажимается всей рамкой
        const r = (el.tagName === "INPUT" && el.closest("label") ? el.closest("label")! : el).getBoundingClientRect();
        const style = getComputedStyle(el);
        if (!r.width || !r.height || style.visibility === "hidden" || r.bottom < 0 || r.top > innerHeight) continue;
        if (Math.round(r.height) < 44 || (Math.round(r.width) < 44 && !el.textContent?.trim()))
          out.push(`${el.tagName.toLowerCase()} «${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 30)}» ${Math.round(r.width)}×${Math.round(r.height)}`);
      }
      return out;
    });
    small.push(...bad.map((b) => `${url} · ${b}`));
  }
  console.log(small.join("\n"));
  expect(small, small.join("\n")).toEqual([]);
});
