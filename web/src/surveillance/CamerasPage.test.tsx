// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { CamerasPage } from "./CamerasPage";

vi.mock("./CameraWindow", () => ({
  LivePreview: ({ itemId }: { itemId: string }) => <div data-testid="preview">{itemId}</div>,
  CameraWindow: ({ onClose }: { onClose: () => void }) => <button onClick={onClose}>Закрыть камеру</button>,
}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("сетка ограничивает потоки четырьмя, переключается и освобождает их для окна", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify({ items: url.startsWith("/api/buildings") ? [{ id: "b", name: "Здание" }] : Array.from({ length: 6 }, (_, i) => ({ id: String(i), title: `К${i}`, type_name: "Камера", floor_id: "f", floor_name: "Этаж", room: "Холл", configured: true })) }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><CamerasPage /></QueryClientProvider></MemoryRouter>);
  expect(await screen.findAllByTestId("preview")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "Далее" }));
  expect(screen.getAllByTestId("preview")).toHaveLength(2);
  expect(screen.getByRole("heading", { name: "К4" })).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button", { name: "Открыть камеру" })[0]!);
  expect(screen.queryAllByTestId("preview")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Закрыть камеру" }));
  expect(screen.getAllByTestId("preview")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "Приостановить просмотр" }));
  expect(screen.queryAllByTestId("preview")).toHaveLength(0);
});
