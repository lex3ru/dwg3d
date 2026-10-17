import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { loginAdmin } from "./helpers";

// Удобство (8.6 п. 2): контраст текста не ниже 4,5 : 1 и прочие правила WCAG 2 AA (axe) —
// на каждом разделе, в светлой и тёмной теме; на телефоне кнопки и поля не меньше 44 px.

const PAGES = ["/", "/projects", "/property", "/warehouse", "/documents", "/inventory", "/reports", "/catalog", "/purposes", "/buildings", "/users", "/links", "/journal", "/settings", "/help", "/scan"];

async function plan(page: Page) {
  const all = (await (await page.request.get("/api/buildings")).json()).items as { id: string; name: string }[];
  const b = all.find((x) => x.name === "Поликлиника") ?? all[0]!;
  const info = await (await page.request.get(`/api/buildings/${b.id}`)).json();
  return `/plan/${b.id}/${info.floors[0].id}?mode=place`;
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
