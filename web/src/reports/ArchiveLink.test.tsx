// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { Job } from "@/lib/jobs";
import { ArchiveLink } from "./ReportsPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const job = (result: Record<string, unknown> = {}): Job => ({
  id: "j1",
  title: "Полная выгрузка",
  status: "done",
  progress: { done: 8, total: 8 },
  message: "Готово",
  error: null,
  result: { file: "Выгрузка.zip", href: "/api/reports/exports/j1", ...result },
});

const respond = (status: number, body?: unknown) => new Response(body === undefined ? null : JSON.stringify(body), { status });

// R-027: архив удалили по сроку — карточка говорит почему, ссылки нет
test("удалённый по сроку архив — сообщение вместо ссылки", () => {
  render(<ArchiveLink job={job({ deleted: "Архив удалён 05.11.2026 — истёк срок хранения из «Настроек». Соберите выгрузку заново." })} />);
  expect(screen.queryByRole("link", { name: "Скачать архив" })).toBeNull();
  expect(screen.getByRole("status").textContent).toMatch(/истёк срок хранения/);
});

test("архив есть — скачивается после проверки HEAD", async () => {
  const fetch = vi.fn().mockResolvedValue(respond(200));
  vi.stubGlobal("fetch", fetch);
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<ArchiveLink job={job()} />);
  fireEvent.click(screen.getByRole("link", { name: "Скачать архив" }));
  await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
  expect(fetch).toHaveBeenCalledWith("/api/reports/exports/j1", { method: "HEAD", credentials: "same-origin" });
});

test("архив пропал (восстановили копию) — сообщение сервера, а не сбой загрузки", async () => {
  const message = "Архива больше нет — например, после восстановления резервной копии: архивы в неё не входят. Соберите выгрузку заново.";
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(respond(404)).mockResolvedValueOnce(respond(404, { error: { message } })));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<ArchiveLink job={job()} />);
  fireEvent.click(screen.getByRole("link", { name: "Скачать архив" }));
  expect((await screen.findByRole("status")).textContent).toBe(message);
  expect(screen.queryByRole("link", { name: "Скачать архив" })).toBeNull();
  expect(click).not.toHaveBeenCalled();
});

test("нет связи — ошибка рядом со ссылкой, скачать можно снова", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
  render(<ArchiveLink job={job()} />);
  fireEvent.click(screen.getByRole("link", { name: "Скачать архив" }));
  await screen.findByText("Нет связи с сервером.");
  expect(screen.getByRole("link", { name: "Скачать архив" })).toBeTruthy();
});
