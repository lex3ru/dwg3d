import { expect, test, type Page, type Request } from "./fixtures";
import { ADMIN, login, loginAdmin, PASSWORD, unique } from "./helpers";

// Приёмка этапа 9 (10.1): инвентаризация с телефона (5.4.6, 6.5.8) — С18; «просмотр» (5.7.1)
// — С20; ссылка на просмотр (5.7.2) — С21; история предмета и журнал помещения (5.7.3) — С22;
// отчёты (5.6), полная выгрузка (7.4) и главная (6.5.1).

const H = { "X-Requested-With": "app" };

// Этаж: кабинеты 214 и 215 рядом, коридор вдоль них
async function floorWithRooms(page: Page) {
  const b = await (await page.request.post("/api/buildings", { headers: H, data: { name: unique("Инвентаризация-") } })).json();
  const floor = await (await page.request.post(`/api/buildings/${b.id}/floors`, { headers: H, data: { name: "2 этаж" } })).json();
  const wall = (id: string, a: string, z: string, thickness = 300, kind = "bearing") => ({ id, a, b: z, thickness, kind });
  const saved = await page.request.put(`/api/floors/${floor.id}/plan`, {
    headers: H,
    data: {
      plan_version: 1,
      plan: {
        nodes: { a: [0, 0], b: [12000, 0], c: [12000, 6000], d: [0, 6000], e: [0, 2000], f: [12000, 2000], g: [6000, 2000], h: [6000, 6000] },
        walls: [
          wall("w1", "a", "b"), wall("w2", "b", "f"), wall("w3", "f", "c"), wall("w4", "c", "h"), wall("w5", "h", "d"), wall("w6", "d", "e"), wall("w7", "e", "a"),
          wall("p1", "e", "g", 120, "partition"), wall("p2", "g", "f", 120, "partition"), wall("p3", "g", "h", 120, "partition"),
        ],
        openings: [
          { id: "o1", wall: "p1", kind: "door", at: 4500, width: 900, height: 2100 },
          { id: "o2", wall: "p2", kind: "door", at: 1500, width: 900, height: 2100 },
        ],
        rooms: [
          { id: "new-1", x: 3000, y: 4000, number: "214", name: "Кабинет" },
          { id: "new-2", x: 9000, y: 4000, number: "215", name: "Кабинет" },
          { id: "new-3", x: 6000, y: 1000, number: "1К", name: "Коридор" },
        ],
      },
    },
  });
  expect(saved.ok()).toBeTruthy();
  const rooms = Object.fromEntries((await saved.json()).rooms.map((r: { number: string; id: string }) => [r.number, r.id])) as Record<string, string>;
  return { building: b.id as string, name: b.name as string, floor: floor.id as string, rooms };
}

async function typeId(page: Page, name: string): Promise<string> {
  const tree = await (await page.request.get("/api/catalog")).json();
  return tree.types.find((t: { name: string }) => t.name === name).id;
}

interface Unit {
  id: string;
  number: string;
  place: { key: string };
  state: string;
  label_code: string;
}

// Приход в помещение — единицы с номерами
async function receipt(page: Page, room: string, type: string, qty: number, price: number): Promise<Unit[]> {
  const doc = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind: "receipt", header: { to_place: `r:${room}` }, lines: [{ type_id: type, qty, price }] } })).json();
  const r = await page.request.post(`/api/inventory/documents/${doc.id}/post`, { headers: H, data: { version: doc.version } });
  expect(r.ok()).toBeTruthy();
  const lines = (await (await page.request.get(`/api/inventory/documents/${doc.id}`)).json()).lines;
  return Promise.all(lines[0].created_units.map((u: { id: string }) => unit(page, u.id)));
}

async function unit(page: Page, id: string): Promise<Unit> {
  return (await page.request.get(`/api/inventory/units/${id}`)).json();
}

test("С18: инвентаризация этажа с телефона — отметки по номеру и вручную, найденное не там, проведение и акт @телефон", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const [monitor, ecg] = await Promise.all(["Монитор 24″", "Электрокардиограф"].map((n) => typeId(page, n)));
  const monitors = await receipt(page, f.rooms["214"]!, monitor, 3, 14500);
  const [cardio] = await receipt(page, f.rooms["215"]!, ecg, 1, 85000);

  // ведомость этажа
  await page.goto("/inventory");
  await page.getByRole("button", { name: "Новая ведомость" }).click();
  await page.getByLabel("Этаж", { exact: true }).selectOption({ label: `${f.name} · 2 этаж` });
  await page.getByRole("button", { name: "Сформировать" }).click();
  await expect(page).toHaveURL(/\/inventory\/[0-9a-f-]{36}$/);
  const totals = page.getByLabel("Итоги обхода");
  await expect(totals).toContainText("Числится4");

  // 214: метка первого монитора (номер с наклейки набран руками), третий — галочкой
  const place = page.getByLabel("Место обхода");
  await place.selectOption(`r:${f.rooms["214"]}`);
  await page.getByLabel("Номер или код метки").fill(monitors[0]!.number);
  await page.getByRole("button", { name: "Отметить" }).click();
  await expect(page.getByRole("status", { name: "Последняя метка" })).toContainText("Найдена:");
  const third = page.getByLabel(new RegExp(`^Найдена: .* № ${monitors[2]!.number}$`));
  await third.click();
  await expect(third).toBeChecked();
  await expect(page.getByRole("heading", { name: /214.*: найдено 2 из 3/ })).toBeVisible();

  // 215: второй монитор нашёлся здесь — «не здесь», переместится; кардиограф не нашли
  await place.selectOption(`r:${f.rooms["215"]}`);
  await page.getByLabel("Номер или код метки").fill(monitors[1]!.label_code);
  await page.getByRole("button", { name: "Отметить" }).click();
  await expect(page.getByRole("status", { name: "Последняя метка" })).toContainText("Не здесь:");
  await expect(page.getByRole("list", { name: "Найдено здесь чужое" })).toContainText(monitors[1]!.number);
  await expect(totals).toContainText("На своём месте2");
  await expect(totals).toContainText("Найдено не там1");
  await expect(totals).toContainText("Не найдено1");

  await page.getByRole("button", { name: "Провести" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Провести" }).click();
  await expect(page.getByText("проведён", { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Акт расхождений" })).toBeVisible();

  // учёт совпадает с действительностью
  expect((await unit(page, monitors[1]!.id)).place.key).toBe(`r:${f.rooms["215"]}`);
  expect((await unit(page, cardio!.id)).state).toBe("not_found");
  expect((await unit(page, monitors[0]!.id)).state).not.toBe("not_found");
  const id = page.url().split("/").pop();
  const act = await page.request.get(`/api/inventory/counts/${id}/act.pdf`);
  expect(act.ok()).toBeTruthy();
  expect(act.headers()["content-type"]).toContain("pdf");
  // документом задним числом в эти места больше не провести
  const late = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind: "transfer", header: { from_place: `r:${f.rooms["214"]}`, to_place: `r:${f.rooms["215"]}`, date: "2020-01-01" }, lines: [{ unit_id: monitors[0]!.id }] } })).json();
  expect((await page.request.post(`/api/inventory/documents/${late.id}/post`, { headers: H, data: { version: late.version } })).ok()).toBeFalsy();
});

// Количественный тип с двумя моделями и приход каждой в помещение (ADR-0005: остаток — по
// позиции «место + тип + модель»)
async function stockWithModels(page: Page, room: string, lots: [model: string, qty: number][]) {
  const type = await (await page.request.post("/api/catalog/types", { headers: H, data: { name: unique("Бахилы-"), accounting: "quantity", unit: "упак." } })).json();
  const models: Record<string, string> = {};
  for (const [name] of lots) {
    const t = await (await page.request.post(`/api/catalog/types/${type.id}/models`, { headers: H, data: { name } })).json();
    models[name] = t.models.find((m: { name: string }) => m.name === name).id;
  }
  const lines = lots.map(([name, qty]) => ({ type_id: type.id, model_id: models[name], qty, price: 260 }));
  const doc = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind: "receipt", header: { to_place: `r:${room}` }, lines } })).json();
  expect((await page.request.post(`/api/inventory/documents/${doc.id}/post`, { headers: H, data: { version: doc.version } })).ok()).toBeTruthy();
  return { type: type.id as string, name: type.name as string, models };
}

async function countOf(page: Page, room: string): Promise<string> {
  const count = await (await page.request.post("/api/inventory/counts", { headers: H, data: { places: [`r:${room}`] } })).json();
  return count.id;
}

async function counted(page: Page, id: string, room: string): Promise<Record<string, number | null>> {
  const view = await (await page.request.get(`/api/inventory/counts/${id}?place=${encodeURIComponent(`r:${room}`)}`)).json();
  return Object.fromEntries(view.place.stock.map((s: { title: string; counted: number | null }) => [s.title, s.counted]));
}

async function balances(page: Page, room: string): Promise<[string, number][]> {
  const items = (await (await page.request.get(`/api/inventory/balances?place=${encodeURIComponent(`r:${room}`)}`)).json()).items;
  return items.map((b: { model_name: string; qty: number }) => [b.model_name, b.qty] as [string, number]).sort();
}

test("С18, R-021: пересчёт остатка с моделью — недостача и излишек ложатся на свою модель @телефон", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const s = await stockWithModels(page, f.rooms["214"]!, [["100 пар", 10], ["50 пар", 5]]);
  const id = await countOf(page, f.rooms["214"]!);

  await page.goto(`/inventory/${id}`);
  const big = page.getByLabel(`Фактически: ${s.name} 100 пар`);
  const small = page.getByLabel(`Фактически: ${s.name} 50 пар`);
  await big.fill("8");
  await big.press("Enter");
  await small.fill("6");
  await small.press("Enter");
  await expect.poll(() => counted(page, id, f.rooms["214"]!)).toEqual({ [`${s.name} 100 пар`]: 8, [`${s.name} 50 пар`]: 6 });

  await page.getByRole("button", { name: "Провести" }).first().click();
  await expect(page.getByRole("dialog")).toContainText("Остатки с расхождением: 2");
  await page.getByRole("dialog").getByRole("button", { name: "Провести" }).click();
  await expect(page.getByRole("button", { name: "Акт расхождений" })).toBeVisible();
  expect(await balances(page, f.rooms["214"]!)).toEqual([["100 пар", 8], ["50 пар", 6]]);
});

test("6.7 п. 1, R-030: отметки и пересчёт ждут, пока сервер перезапускается и пока сеанс не возобновлён, — и досылаются @телефон", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const [monitor] = await receipt(page, f.rooms["214"]!, await typeId(page, "Монитор 24″"), 1, 14500);
  const s = await stockWithModels(page, f.rooms["214"]!, [["100 пар", 10]]);
  const id = await countOf(page, f.rooms["214"]!);
  const title = `${s.name} 100 пар`;
  const sends = /\/api\/inventory\/counts\/[0-9a-f-]+\/(marks|stock|scan)/;

  await page.goto(`/inventory/${id}`);
  const found = page.getByLabel(new RegExp(`^Найдена: .* № ${monitor!.number}$`));
  const fact = page.getByLabel(`Фактически: ${title}`);
  await expect(found).toBeVisible();

  // сервер перезапускается — Caddy отвечает 502
  await page.route(sends, (route) => route.fulfill({ status: 502, contentType: "text/html", body: "Bad Gateway" }));
  await found.click();
  await fact.fill("7");
  await fact.press("Enter");
  await expect(page.getByRole("alert")).toContainText("Сервер не принимает отметки — отметок ждёт отправки: 2");
  await page.getByRole("button", { name: "Провести" }).first().click();
  const ask = page.getByRole("dialog");
  await expect(ask).toContainText("Ещё не отправлено отметок: 2");
  await expect(ask.getByRole("button", { name: "Провести" })).toBeDisabled();
  await ask.getByRole("button", { name: "Отмена" }).click();

  // сервер поднялся — очередь досылается сама
  await page.unroute(sends);
  await expect(page.getByRole("alert")).toHaveCount(0, { timeout: 10_000 });
  await expect(found).toBeChecked();
  expect((await counted(page, id, f.rooms["214"]!))[title]).toBe(7);

  // сеанс кончился — на вход, а пересчёт ждёт; после входа — снова ведомость, и он дослан
  await page.route(sends, (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: { code: "not_authenticated", message: "Нужно войти в систему." } }) }));
  await fact.fill("9");
  await fact.press("Enter");
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.unroute(sends);
  await page.getByLabel("Имя для входа").fill(ADMIN);
  await page.getByLabel("Пароль", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(new RegExp(`/inventory/${id}$`));
  await expect.poll(() => counted(page, id, f.rooms["214"]!)).toEqual({ [title]: 9 });
  await expect(fact).toHaveValue("9");
});

test("6.7 п. 1, R-049: зависший запрос не держит очередь — через 15 с «Нет связи», и опоздавший старый пересчёт не затирает новый @телефон", async ({ page }) => {
  test.setTimeout(60_000);
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const s = await stockWithModels(page, f.rooms["214"]!, [["100 пар", 10]]);
  const id = await countOf(page, f.rooms["214"]!);
  const title = `${s.name} 100 пар`;
  const stock = /\/api\/inventory\/counts\/[0-9a-f-]+\/stock$/;

  await page.goto(`/inventory/${id}`);
  const fact = page.getByLabel(`Фактически: ${title}`);
  await expect(fact).toBeVisible();

  // соединение повисло: первый запрос пересчёта не получает ни ответа, ни ошибки
  let hung: Request | undefined;
  await page.route(stock, (route) => {
    if (hung) return route.continue();
    hung = route.request();
  });
  await fact.fill("7");
  await fact.press("Enter");
  await expect(page.getByRole("alert")).toContainText("Нет связи — отметок ждёт отправки: 1", { timeout: 20_000 });
  // досылается само — тем же номером
  await expect(page.getByRole("alert")).toHaveCount(0, { timeout: 10_000 });
  expect((await counted(page, id, f.rooms["214"]!))[title]).toBe(7);

  // комиссия поправила на 9 — и только теперь старый запрос с 7 дошёл до сервера
  await fact.fill("9");
  await fact.press("Enter");
  await expect.poll(() => counted(page, id, f.rooms["214"]!)).toEqual({ [title]: 9 });
  const sent = await hung!.allHeaders();
  expect(sent["x-count-seq"]).toMatch(/^[1-9]\d*$/);
  const late = await page.request.put(hung!.url(), {
    headers: { ...H, "X-Count-Device": sent["x-count-device"]!, "X-Count-Seq": sent["x-count-seq"]! },
    data: hung!.postDataJSON(),
  });
  expect(late.status()).toBe(204);
  expect(await counted(page, id, f.rooms["214"]!)).toEqual({ [title]: 9 });
  await page.reload();
  await expect(fact).toHaveValue("9");
});

test("С20: заведующий с «просмотром» видит план и карточки без стоимости, номеров и проектов", async ({ page, browser }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const [one] = await receipt(page, f.rooms["214"]!, await typeId(page, "Монитор 24″"), 1, 14500);
  const name = unique("zav");
  const created = await page.request.post("/api/users", { headers: H, data: { login: name, full_name: "Заведующий З. З.", role: "viewer", building_ids: [f.building], password: "Temporary-pass-1" } });
  expect(created.status()).toBe(201);

  const viewer = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage();
  await login(viewer, name, "Temporary-pass-1");
  await viewer.getByLabel("Текущий пароль").fill("Temporary-pass-1");
  await viewer.getByLabel("Новый пароль", { exact: true }).fill("Viewer-pass-12");
  await viewer.getByLabel("Новый пароль ещё раз").fill("Viewer-pass-12");
  await viewer.getByRole("button", { name: "Сменить и продолжить" }).click();
  const menu = viewer.getByRole("navigation", { name: "Разделы" });
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("link", { name: "Проекты" })).toHaveCount(0);
  await expect(menu.getByRole("link", { name: "Отчёты" })).toHaveCount(0);

  await viewer.goto(`/plan/${f.building}/${f.floor}`);
  await expect(viewer.getByRole("img", { name: "План этажа" })).toBeVisible();
  await expect(viewer.getByRole("tab", { name: /^Учёт/ })).toHaveCount(0);

  await viewer.goto(`/property?card=unit:${one!.id}`);
  await expect(viewer.getByRole("complementary", { name: "Карточка" })).toContainText("Монитор");
  await expect(viewer.getByText(one!.number)).toHaveCount(0);
  await expect(viewer.getByText(/14\s500/)).toHaveCount(0);

  const card = await (await viewer.request.get(`/api/inventory/units/${one!.id}`)).json();
  expect(card.number ?? null).toBeNull();
  expect(card.price ?? null).toBeNull();
  expect((await viewer.request.get(`/api/projects?building_id=${f.building}`)).status()).toBe(403);
  expect((await viewer.request.get("/api/reports")).status()).toBe(403);
  expect((await viewer.request.get(`/api/home?building_id=${f.building}`)).status()).toBe(403);
});

test("С21: ссылка подрядчику — план без учётной записи, без учёта; отзыв досрочно", async ({ page, browser }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  await receipt(page, f.rooms["214"]!, await typeId(page, "Монитор 24″"), 1, 14500);
  const note = unique("ЧОП «Щит» ");

  await page.goto("/links");
  await page.getByRole("button", { name: "Выдать ссылку" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Здание").selectOption(f.building);
  await dialog.getByLabel("Для кого").fill(note);
  await dialog.getByRole("button", { name: "Выдать" }).click();
  const url = await dialog.getByLabel("Ссылка").inputValue();
  expect(url).toMatch(/\/share\/[\w-]{20,}$/);
  await dialog.getByRole("button", { name: "Готово" }).click();

  // подрядчик: без входа — план здания, учёт ему не показывается
  const guestContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const guest = await guestContext.newPage();
  await guest.goto(new URL(url).pathname);
  await expect(guest.getByText("просмотр по ссылке")).toBeVisible();
  await expect(guest.getByText(f.name)).toBeVisible();
  await expect(guest.getByRole("img", { name: "План этажа" })).toBeVisible();
  await expect(guest.getByRole("navigation", { name: "Разделы" })).toHaveCount(0);
  await expect(guest.getByRole("tab", { name: /^Учёт/ })).toHaveCount(0);
  expect((await guest.request.get("/api/inventory/units")).status()).toBe(403);
  expect((await guest.request.get(`/api/projects?building_id=${f.building}`)).status()).toBe(403);
  expect((await guest.request.get("/api/users")).status()).toBe(403);
  // другое здание — не его
  const others = (await (await guest.request.get("/api/buildings")).json()).items;
  expect(others.map((b: { id: string }) => b.id)).toEqual([f.building]);

  // открытие записано; администратор отзывает ссылку
  const row = page.getByRole("row").filter({ hasText: note });
  await page.reload();
  await expect(row).toContainText("1");
  await row.getByRole("button", { name: "Отозвать" }).click();
  await expect(row).toContainText("отозвана");
  await guest.reload();
  await expect(guest.getByRole("img", { name: "План этажа" })).toHaveCount(0);
  const late = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage();
  await late.goto(new URL(url).pathname);
  await expect(late.getByRole("heading", { name: "Ссылка не действует" })).toBeVisible();

  await page.goto("/journal?action=access.share");
  await expect(page.getByText(note).first()).toBeVisible();
});

test("С22: кто переставил кушетку — история предмета и журнал помещения", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const couch = await typeId(page, "Кушетка смотровая");
  const made = await (await page.request.post(`/api/floors/${f.floor}/items/changes`, { headers: H, data: { create: [{ type_id: couch, x: 3000, y: 4500 }] } })).json();
  const item = made.items.find((i: { type_id: string }) => i.type_id === couch)?.id;
  expect(item).toBeTruthy();
  const r = await page.request.post(`/api/floors/${f.floor}/items/changes`, { headers: H, data: { update: [{ id: item, x: 9000, y: 4500 }] } });
  expect(r.ok()).toBeTruthy();

  await page.goto(`/plan/${f.building}/${f.floor}?item=${item}`);
  await expect(page.getByRole("img", { name: "План этажа" })).toBeVisible();
  await page.getByRole("link", { name: "История" }).click();
  await expect(page).toHaveURL(new RegExp(`/journal\\?ref=item(:|%3A)${item}`));
  await expect(page.getByText(/поставлены: Кушетка смотровая/)).toBeVisible();
  await expect(page.getByText(/изменены: Кушетка смотровая/)).toBeVisible();
  // кто — тот, кто вошёл
  const me = (await (await page.request.get("/api/auth/me")).json()).full_name as string;
  await expect(page.getByRole("main").getByText(me).first()).toBeVisible();

  await page.goto(`/plan/${f.building}/${f.floor}?room=${f.rooms["215"]}`);
  await page.getByRole("link", { name: "Журнал помещения" }).click();
  await expect(page).toHaveURL(new RegExp(`/journal\\?ref=room(:|%3A)${f.rooms["215"]}`));
  await expect(page.getByText(/изменены: Кушетка смотровая/)).toBeVisible();
});

test("С22: ленты здания, этажа и документа; удалённый черновик оставляет след (R-041, R-011)", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const [monitor] = await receipt(page, f.rooms["214"]!, await typeId(page, "Монитор 24″"), 1, 14500);
  const draft = await (await page.request.post("/api/inventory/documents", { headers: H, data: { kind: "writeoff", header: { reason: "разбит" }, lines: [{ unit_id: monitor!.id }] } })).json();

  // лента документа — из документа; черновик удалён, а след остался
  await page.goto(`/documents/${draft.id}`);
  await page.getByRole("main").getByRole("link", { name: "Журнал", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/journal\\?ref=document(:|%3A)${draft.id}`));
  await expect(page.getByText(/Лента: Списание/)).toBeVisible();
  await expect(page.getByText(/Создан черновик «Списание/)).toBeVisible();
  expect((await page.request.delete(`/api/inventory/documents/${draft.id}`, { headers: H })).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByText(/Удалён черновик «Списание/)).toBeVisible();

  // лента здания — из «Зданий»: план, учёт, черновики
  await page.goto(`/buildings?b=${f.building}`);
  await page.getByRole("main").getByRole("link", { name: "Журнал", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/journal\\?building=${f.building}`));
  await expect(page.getByRole("main").getByLabel("Здание")).toHaveValue(f.building);
  await expect(page.getByText(/Сохранён план «2 этаж»/)).toBeVisible();
  await expect(page.getByText(/Проведён «Приход/)).toBeVisible();
  await expect(page.getByText(/Удалён черновик «Списание/)).toBeVisible();

  // лента этажа — фильтром «Этаж»
  await page.getByRole("main").getByRole("combobox", { name: /^Этаж/ }).selectOption({ label: "2 этаж" });
  await expect(page).toHaveURL(new RegExp(`floor=${f.floor}`));
  await expect(page.getByText(/Проведён «Приход/)).toBeVisible();
});

test("главная, отчёты и полная выгрузка здания", async ({ page }) => {
  await loginAdmin(page);
  const f = await floorWithRooms(page);
  const [broken] = await receipt(page, f.rooms["214"]!, await typeId(page, "Монитор 24″"), 2, 14500);
  const card = await unit(page, broken!.id);
  const patched = await page.request.patch(`/api/inventory/units/${broken!.id}`, { headers: H, data: { version: (card as unknown as { version: number }).version, values: { state: "broken" } } });
  expect(patched.ok()).toBeTruthy();

  // главная: что требует внимания — со ссылкой на отбор
  await page.goto(`/?building=${f.building}`);
  await expect(page.getByRole("heading", { name: "Главная" })).toBeVisible();
  const attention = page.getByRole("region", { name: "Требует внимания" });
  await expect(attention.getByRole("link", { name: /^1\s*Неисправные/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Стоимость имущества" })).toContainText("29 000");
  await attention.getByRole("link", { name: /Неисправные/ }).click();
  await expect(page).toHaveURL(/\/property\?.*state=broken/);
  await expect(page.getByText(broken!.number)).toBeVisible();

  // отчёт: реестр в Excel и ведомость помещения в PDF
  await page.goto(`/reports?building_id=${f.building}`);
  await page.getByRole("button", { name: /Реестр инвентарных единиц/ }).click();
  const xlsx = page.waitForEvent("download");
  await page.getByLabel("Параметры: Реестр инвентарных единиц").getByRole("button", { name: "Excel" }).click();
  expect((await xlsx).suggestedFilename()).toMatch(/\.xlsx$/);
  await page.getByRole("button", { name: /Ведомость помещения/ }).click();
  const form = page.getByLabel("Параметры: Ведомость помещения");
  await form.getByLabel("Место").selectOption(`r:${f.rooms["214"]}`);
  const pdf = page.waitForEvent("download");
  await form.getByRole("button", { name: "PDF" }).click();
  expect((await pdf).suggestedFilename()).toMatch(/\.pdf$/);

  // 7.4: архив здания фоновой задачей
  await page.getByRole("button", { name: `Здание «${f.name}»` }).click();
  await expect(page.getByRole("link", { name: "Скачать архив" })).toBeVisible({ timeout: 60_000 });
  const href = await page.getByRole("link", { name: "Скачать архив" }).getAttribute("href");
  const zip = await page.request.get(href!);
  expect(zip.ok()).toBeTruthy();
  expect((await zip.body()).subarray(0, 2).toString()).toBe("PK");
});

test("R-046: раскрытый отчёт не растягивает соседний в той же строке", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/reports");
  const toggles = page.getByRole("main").locator("button[aria-expanded]");
  const [first, second] = [toggles.nth(0).locator(".."), toggles.nth(1).locator("..")];
  const before = (await second.boundingBox())!;
  // в одной строке сетки — иначе проверять нечего
  expect(Math.abs((await first.boundingBox())!.y - before.y)).toBeLessThan(1);
  await toggles.nth(0).click();
  await expect(toggles.nth(0)).toHaveAttribute("aria-expanded", "true");
  expect((await first.boundingBox())!.height).toBeGreaterThan(before.height + 20);
  expect((await second.boundingBox())!.height).toBeCloseTo(before.height, 0);
});
