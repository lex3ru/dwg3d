# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: a11y.spec.ts >> WCAG 2 AA на всех разделах — тёмная тема
- Location: tests\a11y.spec.ts:23:3

# Error details

```
TypeError: Cannot read properties of undefined (reading 'id')
```

# Page snapshot

```yaml
- generic [ref=e3]:
  - navigation "Разделы" [ref=e4]:
    - generic [ref=e6]:
      - generic [ref=e7]: Планировка и учёт
      - generic [ref=e8]: имущества здания
    - generic [ref=e9]:
      - link "Главная" [ref=e11] [cursor=pointer]:
        - /url: /
      - generic [ref=e16]:
        - generic [ref=e17]: Планировка
        - link "План и расстановка" [ref=e18] [cursor=pointer]:
          - /url: /plan
        - link "Проекты" [ref=e27] [cursor=pointer]:
          - /url: /projects
      - generic [ref=e31]:
        - generic [ref=e32]: Учёт имущества
        - link "Имущество" [ref=e33] [cursor=pointer]:
          - /url: /property
        - link "Склад" [ref=e39] [cursor=pointer]:
          - /url: /warehouse
        - link "Документы" [ref=e44] [cursor=pointer]:
          - /url: /documents
        - link "Инвентаризация" [ref=e49] [cursor=pointer]:
          - /url: /inventory
      - link "Отчёты" [ref=e56] [cursor=pointer]:
        - /url: /reports
      - generic [ref=e60]:
        - generic [ref=e61]: Справочники
        - link "Каталог" [ref=e62] [cursor=pointer]:
          - /url: /catalog
        - link "Назначения помещений" [ref=e66] [cursor=pointer]:
          - /url: /purposes
      - generic [ref=e71]:
        - generic [ref=e72]: Управление
        - link "Здания" [ref=e73] [cursor=pointer]:
          - /url: /buildings
        - link "Пользователи" [ref=e79] [cursor=pointer]:
          - /url: /users
        - link "Ссылки на просмотр" [ref=e86] [cursor=pointer]:
          - /url: /links
        - link "Журнал" [ref=e91] [cursor=pointer]:
          - /url: /journal
        - link "Настройки" [ref=e97] [cursor=pointer]:
          - /url: /settings
    - button "Свернуть меню" [ref=e102] [cursor=pointer]: Свернуть
  - generic [ref=e106]:
    - banner [ref=e107]:
      - navigation "Где я" [ref=e108]:
        - generic [ref=e109]: Главная
      - generic [ref=e111]:
        - generic [ref=e112]: Поиск
        - searchbox "Поиск" [ref=e113]
      - link "QR-сканер" [ref=e114] [cursor=pointer]:
        - /url: /scan
      - button "Справка" [ref=e121]
      - 'button "Пользователь: Администратор, администратор" [ref=e125] [cursor=pointer]':
        - generic [ref=e126]: А
        - generic [ref=e127]:
          - generic [ref=e128]: Администратор
          - generic [ref=e129]: администратор
    - main [ref=e131]:
      - generic [ref=e132]:
        - heading "Главная" [level=1] [ref=e135]
        - generic [ref=e137]:
          - generic [ref=e138]: Зданий пока нет
          - generic [ref=e139]:
            - text: Начните с
            - link "«Зданий»" [ref=e140] [cursor=pointer]:
              - /url: /buildings
            - text: ": заведите здание, этажи и план — или загрузите чертёж."
```

# Test source

```ts
  1  | import AxeBuilder from "@axe-core/playwright";
  2  | import { expect, test, type Page } from "@playwright/test";
  3  | import { loginAdmin } from "./helpers";
  4  | 
  5  | // Удобство (8.6 п. 2): контраст текста не ниже 4,5 : 1 и прочие правила WCAG 2 AA (axe) —
  6  | // на каждом разделе, в светлой и тёмной теме; на телефоне кнопки и поля не меньше 44 px.
  7  | 
  8  | const PAGES = ["/", "/projects", "/property", "/warehouse", "/documents", "/inventory", "/reports", "/catalog", "/purposes", "/buildings", "/users", "/links", "/journal", "/settings", "/help", "/scan"];
  9  | 
  10 | async function plan(page: Page) {
  11 |   const all = (await (await page.request.get("/api/buildings")).json()).items as { id: string; name: string }[];
  12 |   const b = all.find((x) => x.name === "Поликлиника") ?? all[0]!;
> 13 |   const info = await (await page.request.get(`/api/buildings/${b.id}`)).json();
     |                                                                  ^ TypeError: Cannot read properties of undefined (reading 'id')
  14 |   return `/plan/${b.id}/${info.floors[0].id}?mode=place`;
  15 | }
  16 | 
  17 | async function settle(page: Page) {
  18 |   await expect(page.getByText("Загрузка…")).toHaveCount(0, { timeout: 10_000 });
  19 |   await page.waitForTimeout(300);
  20 | }
  21 | 
  22 | for (const scheme of ["light", "dark"] as const) {
  23 |   test(`WCAG 2 AA на всех разделах — ${scheme === "light" ? "светлая" : "тёмная"} тема`, async ({ page }) => {
  24 |     test.setTimeout(180_000);
  25 |     await page.emulateMedia({ colorScheme: scheme });
  26 |     await loginAdmin(page);
  27 |     const found: string[] = [];
  28 |     for (const url of [...PAGES, await plan(page)]) {
  29 |       await page.goto(url);
  30 |       await settle(page);
  31 |       const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).exclude("canvas").analyze();
  32 |       for (const v of r.violations.filter((x) => x.impact === "serious" || x.impact === "critical"))
  33 |         found.push(`${url} · ${v.id} (${v.impact}): ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join("; ")}${v.nodes.length > 3 ? ` и ещё ${v.nodes.length - 3}` : ""}`);
  34 |     }
  35 |     console.log(found.join("\n"));
  36 |     expect(found, found.join("\n")).toEqual([]);
  37 |   });
  38 | }
  39 | 
  40 | test("на телефоне кнопки и поля не меньше 44 px @телефон", async ({ page }) => {
  41 |   test.setTimeout(120_000);
  42 |   await loginAdmin(page);
  43 |   const small: string[] = [];
  44 |   for (const url of ["/", "/property", "/warehouse", "/documents", "/inventory", "/scan", "/help", await plan(page)]) {
  45 |     await page.goto(url);
  46 |     await settle(page);
  47 |     const bad = await page.evaluate(() => {
  48 |       const out: string[] = [];
  49 |       const sel = "button, [role=button], [role=tab], select, input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]), a[class*='inline-flex']";
  50 |       for (const el of Array.from(document.querySelectorAll<HTMLElement>(sel))) {
  51 |         // поле внутри подписи-рамки нажимается всей рамкой
  52 |         const r = (el.tagName === "INPUT" && el.closest("label") ? el.closest("label")! : el).getBoundingClientRect();
  53 |         const style = getComputedStyle(el);
  54 |         if (!r.width || !r.height || style.visibility === "hidden" || r.bottom < 0 || r.top > innerHeight) continue;
  55 |         if (Math.round(r.height) < 44 || (Math.round(r.width) < 44 && !el.textContent?.trim()))
  56 |           out.push(`${el.tagName.toLowerCase()} «${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 30)}» ${Math.round(r.width)}×${Math.round(r.height)}`);
  57 |       }
  58 |       return out;
  59 |     });
  60 |     small.push(...bad.map((b) => `${url} · ${b}`));
  61 |   }
  62 |   console.log(small.join("\n"));
  63 |   expect(small, small.join("\n")).toEqual([]);
  64 | });
  65 | 
```