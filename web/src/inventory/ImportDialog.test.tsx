// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { get } from "@/lib/api";
import { ImportDialog } from "./ImportDialog";

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), get: vi.fn() }));

const room = (key: string, number: string, name: string, how: string, place: string | null, title: string | null, confirm = false) => ({
  key,
  floor: "1",
  room: number,
  room_name: name,
  rows: [Number(number) - 98],
  how,
  confirm,
  place,
  place_title: title,
});

// Проверка образца: 101 совпала номером, а не названием; 102 — точно; 109 на плане нет
const report = {
  building: { id: "b1", name: "Поликлиника" },
  names: [
    { name: "Аппарат УЗИ", layer: "", accounting: "поштучно", rows: [2], how: "exact", type_id: "t1", candidates: [] },
    { name: "Тонометр", layer: "", accounting: "поштучно", rows: [3], how: "none", type_id: null, candidates: [] },
  ],
  rooms: [
    room("1|102", "102", "Холл", "exact", "r:2", "1 этаж › 102 Холл"),
    room("1|101", "101", "Регистратура", "similar", "r:1", "1 этаж › 101 Холл", true),
    room("1|109", "109", "Склад", "none", null, null),
  ],
  rows: 3,
  errors: [
    { row: 2, message: "инвентарный номер 000001 уже занят" },
    { row: 3, message: "«Тонометр» не сопоставлено с типом каталога — выберите тип или «создать тип»", name: "Тонометр" },
    { row: 3, message: "помещение 101 «Регистратура» (1 этаж) сопоставлено по номеру с «101 Холл» — названия разные: подтвердите или выберите другое место", room: "1|101" },
    { row: 11, message: "помещение 109 (1 этаж) не найдено на плане — выберите место", room: "1|109" },
  ],
  units: 2,
  stock: 0,
  total: 100,
  ok: false,
  applied: false,
};

const fetchMock = vi.fn();

beforeEach(() => {
  vi.mocked(get).mockImplementation(async (url: string) => {
    if (url.startsWith("/api/buildings")) return { items: [{ id: "b1", name: "Поликлиника" }] };
    if (url.startsWith("/api/catalog")) return { types: [] };
    return { buildings: [], warehouses: [] };
  });
  fetchMock.mockResolvedValue({ ok: true, json: async () => report });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function checked() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ImportDialog open onClose={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const dialog = await screen.findByRole("dialog", { name: "Загрузить имущество из Excel" });
  const building = within(dialog).getByLabelText<HTMLSelectElement>("Здание");
  await waitFor(() => expect(building.options.length).toBe(2));
  fireEvent.change(building, { target: { value: "b1" } });
  const file = new File(["x"], "имущество.xlsx");
  fireEvent.change(within(dialog).getByLabelText("Файл со списком имущества"), { target: { files: [file] } });
  await within(dialog).findByText(/Есть что исправить \(4\)/);
  return dialog;
}

const rowsOf = (dialog: HTMLElement, heading: RegExp) => within(within(dialog).getByRole("region", { name: heading })).getAllByRole("row");

// R-045: что требует внимания — сверху, статус виден не только мелким текстом
test("строки «не найдено» и «похоже» — над «точно», статус — отметкой", async () => {
  const dialog = await checked();
  const rooms = rowsOf(dialog, /^Помещения/);
  expect(rooms.map((r) => r.querySelector("[data-how]")?.getAttribute("data-how"))).toEqual(["none", "similar", "exact"]);
  expect(within(rooms[0]!).getByText("не найдено")).toBeTruthy();
  expect(within(rooms[2]!).getByText("точно")).toBeTruthy();
  const names = rowsOf(dialog, /^Наименования/);
  expect(names.map((r) => r.querySelector("[data-how]")?.getAttribute("data-how"))).toEqual(["none", "exact"]);
});

// R-047: ошибка сопоставления — у своей строки таблицы, ошибки строк файла — общим списком
test("ошибки сопоставления — у своих строк, остальные — списком", async () => {
  const dialog = await checked();
  const [missing, reg] = rowsOf(dialog, /^Помещения/);
  expect(within(missing!).getByText(/109 \(1 этаж\) не найдено на плане/)).toBeTruthy();
  expect(within(reg!).getByText(/сопоставлено по номеру с «101 Холл»/)).toBeTruthy();
  const [tonometer] = rowsOf(dialog, /^Наименования/);
  expect(within(tonometer!).getByText(/«Тонометр» не сопоставлено/)).toBeTruthy();
  const list = within(dialog).getByRole("list", { name: "Ошибки по строкам файла" });
  expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Строка 2: инвентарный номер 000001 уже занят"]);
});

// R-002: помещение, совпавшее номером, но не названием, — оба названия и «Верно»
test("«Верно» подтверждает помещение, найденное по номеру", async () => {
  const dialog = await checked();
  const reg = rowsOf(dialog, /^Помещения/)[1]!;
  fireEvent.click(within(reg).getByRole("button", { name: "Верно" }));
  expect(within(reg).queryByRole("button", { name: "Верно" })).toBeNull();
  // после проверки ошибки нет — остаётся, куда попадут вещи, и что это подтверждено
  fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ ...report, errors: report.errors.filter((e) => e.room !== "1|101") }) });
  fireEvent.click(within(dialog).getByRole("button", { name: "Проверить снова" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  const form = fetchMock.mock.calls[1]![1].body as FormData;
  expect(JSON.parse(form.get("mapping") as string).rooms).toEqual({ "1|101": "r:1" });
  const again = rowsOf(dialog, /^Помещения/)[1]!;
  expect(await within(again).findByText("на плане — 1 этаж › 101 Холл")).toBeTruthy();
  expect(within(again).getByText("подтверждено")).toBeTruthy();
});
