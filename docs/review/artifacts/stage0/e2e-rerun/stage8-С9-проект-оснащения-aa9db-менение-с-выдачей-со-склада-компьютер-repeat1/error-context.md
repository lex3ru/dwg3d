# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: stage8.spec.ts >> С9: проект оснащения — правка на плане, сравнение, смета, PDF, применение с выдачей со склада
- Location: tests\stage8.spec.ts:71:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: getByRole('dialog', { name: 'Проект применён' })
Expected substring: "Оформлено «Перемещение"
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toContainText" getByRole('dialog', { name: 'Проект применён' }) with timeout 5000ms
  - waiting for getByRole('dialog', { name: 'Проект применён' })

```

```yaml
- dialog "Применить проект «Процедурный 301»?":
  - heading "Применить проект «Процедурный 301»?" [level=2]
  - paragraph: "Изменения перейдут в расстановку: добавится 0, переместится или изменится 0, уберётся 0. Со склада выдаётся 0 (документами «Перемещение»), к закупке — 0."
  - button "Закрыть"
  - button "Отмена"
  - button "Применить"
```

# Test source

```ts
  54  |     },
  55  |     [x, y],
  56  |   );
  57  | }
  58  | 
  59  | interface Item {
  60  |   id: string;
  61  |   type_id: string;
  62  |   unit_id: string | null;
  63  |   params: Record<string, unknown>;
  64  |   x: number;
  65  | }
  66  | 
  67  | async function layout(page: Page, floor: string): Promise<Item[]> {
  68  |   return (await (await page.request.get(`/api/floors/${floor}/items`)).json()).items;
  69  | }
  70  | 
  71  | test("С9: проект оснащения — правка на плане, сравнение, смета, PDF, применение с выдачей со склада", async ({ page }) => {
  72  |   await loginAdmin(page);
  73  |   const f = await floorWithRooms(page);
  74  |   const [desk, cabinet, couch, table] = await Promise.all(
  75  |     ["Стол письменный 1200×600", "Шкаф для документов", "Кушетка смотровая", "Стол процедурный"].map((n) => typeId(page, n)),
  76  |   );
  77  |   const r = await page.request.post(`/api/floors/${f.floor}/items/changes`, {
  78  |     headers: H,
  79  |     data: { create: [{ type_id: desk, x: 3000, y: 4500 }, { type_id: cabinet, x: 800, y: 5300 }] },
  80  |   });
  81  |   const [deskItem] = (await r.json()).items as Item[];
  82  |   // на складе — одна кушетка
  83  |   const wh = await (await page.request.post("/api/inventory/warehouses", { headers: H, data: { name: unique("Склад ") } })).json();
  84  |   const doc = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind: "receipt", header: { to_place: wh.key }, lines: [{ type_id: couch, qty: 1, price: 18000 }] } })).json();
  85  |   expect((await page.request.post(`/api/inventory/documents/${doc.id}/post`, { headers: H, data: { version: doc.version } })).ok()).toBeTruthy();
  86  | 
  87  |   // новый проект из текущей расстановки
  88  |   await page.goto(`/projects?building=${f.building}`);
  89  |   await page.getByRole("button", { name: "Новый проект" }).click();
  90  |   await page.getByRole("dialog", { name: "Новый проект" }).getByLabel("Название").fill("Процедурный 301");
  91  |   await page.getByRole("dialog", { name: "Новый проект" }).getByRole("button", { name: "Создать" }).click();
  92  |   await expect(page.getByRole("heading", { name: "Проект «Процедурный 301»" })).toBeVisible();
  93  |   const projectId = page.url().split("/").pop()!.split("?")[0]!;
  94  | 
  95  |   // правка в редакторе: убрать стол, поставить кушетку и процедурный стол
  96  |   await page.getByRole("link", { name: "Открыть на плане" }).click();
  97  |   await expect(page.getByRole("status", { name: "Режим проекта" })).toContainText("Проект «Процедурный 301»");
  98  |   await expect(page.getByRole("tab", { name: "Строительство" })).toBeHidden();
  99  |   await expect(page.getByRole("img", { name: "План этажа" })).toBeVisible();
  100 |   await page.waitForTimeout(300);
  101 |   const place = async (name: string, x: number, y: number) => {
  102 |     await page.getByRole("tab", { name: "Каталог" }).click();
  103 |     await page.getByLabel("Поиск в каталоге").fill(name);
  104 |     await page.getByRole("list", { name: "Типы для расстановки" }).getByRole("button", { name }).first().click();
  105 |     const p = await screen(page, x, y);
  106 |     await page.mouse.click(p.x, p.y);
  107 |   };
  108 |   await place("Кушетка смотровая", 1500, 3500);
  109 |   await place("Стол процедурный", 4500, 3500);
  110 |   const d = await screen(page, 3000, 4500);
  111 |   await page.mouse.click(d.x, d.y);
  112 |   await expect(page.getByRole("heading", { name: "Стол письменный 1200×600" })).toBeVisible();
  113 |   await page.keyboard.press("Delete");
  114 |   await expect(page.locator("[data-removed]")).toHaveCount(1);
  115 |   // расстановка не тронута
  116 |   await expect.poll(async () => (await page.request.get(`/api/projects/${projectId}`).then((x) => x.json())).changes).toBe(3);
  117 |   expect((await layout(page, f.floor)).map((i) => i.id)).toContain(deskItem!.id);
  118 |   expect(await layout(page, f.floor)).toHaveLength(2);
  119 | 
  120 |   // сравнение с расстановкой и спецификация
  121 |   await page.goto(`/projects/${projectId}`);
  122 |   const diff = page.getByRole("table", { name: "Отличия" });
  123 |   await expect(diff).toContainText("Кушетка смотровая");
  124 |   await expect(diff).toContainText("убран");
  125 |   await page.getByRole("tab", { name: "Спецификация и смета" }).click();
  126 |   const spec = page.getByRole("table", { name: "Спецификация" });
  127 |   await expect(spec.getByRole("row", { name: /Кушетка смотровая/ })).toContainText("1");
  128 |   await expect(spec).toContainText("Итого к закупке");
  129 | 
  130 |   // второй вариант — копия без кушетки; сравнение двух проектов
  131 |   await page.getByRole("button", { name: "Копия — второй вариант" }).click();
  132 |   await page.getByRole("dialog", { name: "Новый проект" }).getByRole("button", { name: "Создать" }).click();
  133 |   await expect(page.getByRole("heading", { name: /вариант 2/ })).toBeVisible();
  134 |   const variant = page.url().split("/").pop()!.split("?")[0]!;
  135 |   const state = await (await page.request.get(`/api/projects/${variant}/floors/${f.floor}`)).json();
  136 |   const added = state.items.find((i: { type_id: string; state: string }) => i.type_id === couch && i.state === "added");
  137 |   await page.request.post(`/api/projects/${variant}/floors/${f.floor}/changes`, { headers: H, data: { delete: [{ id: added.id }] } });
  138 |   await page.goto(`/projects/${projectId}?compare=${variant}`);
  139 |   await expect(page.getByRole("table", { name: "Отличия" }).getByRole("row")).toHaveCount(2);
  140 |   await expect(page.getByRole("table", { name: "Отличия" })).toContainText("добавлен");
  141 | 
  142 |   // PDF для руководства
  143 |   const download = page.waitForEvent("download");
  144 |   await page.getByRole("button", { name: "PDF для руководства" }).click();
  145 |   expect((await download).suggestedFilename()).toContain("Процедурный 301");
  146 | 
  147 |   // применить: кушетку — со склада, процедурный стол — к закупке
  148 |   await page.getByRole("button", { name: "Применить" }).click();
  149 |   const apply = page.getByRole("dialog", { name: "Применить проект «Процедурный 301»?" });
  150 |   await expect(apply.getByLabel("Учёт: Кушетка смотровая")).toHaveValue(/.+/);
  151 |   await expect(apply.getByLabel("Учёт: Стол процедурный")).toHaveValue("buy");
  152 |   await apply.getByRole("button", { name: "Применить" }).click();
  153 |   const done = page.getByRole("dialog", { name: "Проект применён" });
> 154 |   await expect(done).toContainText("Оформлено «Перемещение");
      |                      ^ Error: expect(locator).toContainText(expected) failed
  155 |   await done.getByRole("button", { name: "Готово" }).click();
  156 |   await expect(page.getByText("применён", { exact: true })).toBeVisible();
  157 |   const after = await layout(page, f.floor);
  158 |   expect(after.some((i) => i.id === deskItem!.id)).toBe(false);
  159 |   const placed = after.find((i) => i.type_id === couch)!;
  160 |   expect(placed.unit_id).toBeTruthy();
  161 |   expect(after.find((i) => i.type_id === table)!.params).toEqual({ "project.buy": true });
  162 |   const unit = await (await page.request.get(`/api/inventory/units/${placed.unit_id}`)).json();
  163 |   expect(unit.place.key).toBe(`r:${f.rooms["301"]}`);
  164 | });
  165 | 
```