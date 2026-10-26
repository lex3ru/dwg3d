// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api, ApiError, get } from "@/lib/api";
import { CountPage } from "./CountPage";
import { loadQueue } from "./queue";

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), get: vi.fn(), post: vi.fn(), api: vi.fn() }));
vi.mock("@/shell/context", () => ({ useCardTitle: () => {} }));
vi.mock("@/shell/Shell", () => ({ PageBody: ({ children }: { children: ReactNode }) => <div>{children}</div> }));
vi.mock("./scanner", () => ({ QrCamera: () => null }));

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

const view = {
  id: "c1",
  title: "Инвентаризация ИН-00001",
  status: "draft",
  date: "2026-10-26",
  version: 3,
  places: [{ key: "w:1", title: "Склад", short: "Склад", expected: 0, found: 0, foreign: 0, extras: 0 }],
  summary: { expected: 0, found_in_place: 0, found_elsewhere: 0, missing: 0, extras: 0, stock_diff: 0 },
  place: {
    key: "w:1",
    title: "Склад",
    items: [],
    foreign: [],
    extras: [],
    stock: [{ type_id: "t1", model_id: "m1", title: "Бахилы 100 пар", unit: "упак.", expected: 25, counted: null }],
  },
};

function page() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/inventory/counts/c1"]}>
        <Routes>
          <Route path="/inventory/counts/:countId" element={<CountPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// R-030, 6.7 п. 1: пересчёт остатков — тоже отметка обхода; сервер перезапускается (502 у
// Caddy) — число не теряется, а провести, пока оно не дошло, нельзя
test("пересчёт уходит через очередь, переживает 502, и «Провести» ждёт, пока очередь не опустеет", async () => {
  vi.mocked(get).mockResolvedValue(view);
  vi.mocked(api).mockRejectedValueOnce(new ApiError(502, "http", "Сервер ответил ошибкой 502.")).mockResolvedValue(undefined);
  page();

  const input = await screen.findByLabelText<HTMLInputElement>("Фактически: Бахилы 100 пар");
  fireEvent.change(input, { target: { value: "23" } });
  fireEvent.blur(input);

  const banner = await screen.findByRole("alert");
  expect(banner.textContent).toContain("Сервер не принимает отметки — отметок ждёт отправки: 1");
  expect(api).toHaveBeenCalledWith("PUT", "/api/inventory/counts/c1/stock", { place: "w:1", type_id: "t1", model_id: "m1", counted: 23 });
  expect(loadQueue("count-queue:c1")).toEqual([{ kind: "stock", place: "w:1", type_id: "t1", model_id: "m1", counted: 23 }]);
  expect(input.value).toBe("23");

  fireEvent.click(screen.getByRole("button", { name: "Провести" }));
  const ask = await screen.findByRole("dialog", { name: "Провести инвентаризацию?" });
  expect(within(ask).getByText(/Ещё не отправлено отметок: 1/)).toBeTruthy();
  const go = within(ask).getByRole<HTMLButtonElement>("button", { name: "Провести" });
  expect(go.disabled).toBe(true);

  // сервер поднялся — очередь досылает сама, раз в 4 с
  await act(() => vi.advanceTimersByTimeAsync(4000));
  expect(api).toHaveBeenCalledTimes(2);
  expect(loadQueue("count-queue:c1")).toEqual([]);
  expect(within(ask).queryByText(/Ещё не отправлено/)).toBeNull();
  expect(go.disabled).toBe(false);
});

test("сеанс кончился (401) — отметка ждёт входа, а не выбрасывается", async () => {
  vi.mocked(get).mockResolvedValue(view);
  vi.mocked(api).mockRejectedValue(new ApiError(401, "not_authenticated", "Нужно войти в систему."));
  page();

  const input = await screen.findByLabelText<HTMLInputElement>("Фактически: Бахилы 100 пар");
  fireEvent.change(input, { target: { value: "0" } });
  fireEvent.keyDown(input, { key: "Enter" });

  const banner = await screen.findByRole("alert");
  expect(banner.textContent).toContain("Нужно войти снова — отметок ждёт отправки: 1");
  await act(() => vi.advanceTimersByTimeAsync(8000));
  expect(loadQueue("count-queue:c1")).toHaveLength(1);
  expect(screen.queryByText("Нужно войти в систему.")).toBeNull();
});
