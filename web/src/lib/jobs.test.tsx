// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, post } from "@/lib/api";
import { CancelJob, inQueue, type Job } from "./jobs";

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), post: vi.fn() }));

afterEach(() => {
  cleanup();
  vi.mocked(post).mockReset();
});

const job = (status: Job["status"], extra: Partial<Job> = {}): Job => ({
  id: "j1",
  title: "Перевод чертежа в план",
  status,
  progress: { done: 1, total: 3 },
  message: null,
  error: null,
  ...extra,
});

// R-026, ADR-0011: тяжёлую задачу можно отменить; кнопка показывает, что отмена идёт
test("«Отменить» просит сервер отменить задачу", async () => {
  vi.mocked(post).mockResolvedValue({});
  render(<CancelJob job={job("running")} />);
  fireEvent.click(screen.getByRole("button", { name: "Отменить" }));
  await waitFor(() => expect(post).toHaveBeenCalledWith("/api/system/tasks/j1/cancel"));
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Отменяется…" }).disabled).toBe(true);
});

test("у завершённой задачи «Отменить» нет; отмену уже просили — «Отменяется…»", () => {
  for (const status of ["done", "failed", "cancelled"] as const) {
    render(<CancelJob job={job(status)} />);
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();
  }
  render(<CancelJob job={job("running", { cancel_requested: true })} />);
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Отменяется…" }).disabled).toBe(true);
});

test("задача успела завершиться — ошибки нет; другая ошибка — видна, отменить можно снова", async () => {
  vi.mocked(post).mockRejectedValueOnce(new ApiError(409, "finished", "Задача уже завершилась — отменять нечего."));
  render(<CancelJob job={job("queued")} />);
  fireEvent.click(screen.getByRole("button", { name: "Отменить" }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
  expect(screen.queryByText(/завершилась/)).toBeNull();
  cleanup();

  vi.mocked(post).mockRejectedValueOnce(new ApiError(0, "http", "Нет связи с сервером."));
  render(<CancelJob job={job("running")} />);
  fireEvent.click(screen.getByRole("button", { name: "Отменить" }));
  await screen.findByText("Нет связи с сервером.");
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Отменить" }).disabled).toBe(false);
});

// R-067: перевод, вставший в полосе чертежей за другим, показывался как «Перевод…»
test("задача в очереди дольше 3 с — ждёт очереди", () => {
  const at = Date.parse("2026-10-30T10:00:00Z");
  const queued = job("queued", { created_at: "2026-10-30T10:00:00.123456+00:00" });
  expect(inQueue(queued, at + 2000)).toBe(false);
  expect(inQueue(queued, at + 4000)).toBe(true);
  expect(inQueue({ ...queued, status: "running" }, at + 60_000)).toBe(false);
  expect(inQueue(job("queued"), at + 60_000)).toBe(false);
});
