// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { CameraWindow } from "./CameraWindow";

vi.mock("@/lib/auth", () => ({ useMe: () => ({ role: "admin" }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><CameraWindow itemId="camera" title="Камера у входа" /></QueryClientProvider>);
}

test("настройка новой камеры сохраняет адрес и секрет и открывает поток", async () => {
  let configured = false;
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/preview")) return new Response(null, { status: 503 });
    if (options?.method === "PUT") configured = true;
    return new Response(JSON.stringify({ configured, version: configured ? 1 : 0, address: "", username: "", has_password: false }));
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Настроить подключение" }));
  fireEvent.change(screen.getByLabelText("Адрес потока RTSP"), { target: { value: "rtsp://camera/stream1" } });
  fireEvent.change(screen.getByLabelText("Логин камеры"), { target: { value: "user" } });
  fireEvent.change(screen.getByLabelText("Пароль камеры"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и открыть видео" }));
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith("/preview"))).toBe(true));
  const saved = fetch.mock.calls.find(([, options]) => options?.method === "PUT")!;
  expect(JSON.parse(saved[1]!.body as string)).toEqual({ address: "rtsp://camera/stream1", username: "user", password: "secret", version: 0 });
});

test("пустой пароль сохраняет существующий; конфликт показывает ошибку", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === "PUT") return new Response(JSON.stringify({ error: { message: "Подключение изменено другим пользователем." } }), { status: 409 });
    if (url.endsWith("/preview")) return new Response(null, { status: 503 });
    return new Response(JSON.stringify({ configured: true, version: 3, address: "rtsp://camera/stream1", username: "user", has_password: true }));
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Настройки" }));
  await screen.findByLabelText("Пароль камеры");
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и открыть видео" }));
  expect((await screen.findByRole("alert")).textContent).toContain("изменено другим");
  const saved = fetch.mock.calls.find(([, options]) => options?.method === "PUT")!;
  expect(JSON.parse(saved[1]!.body as string).password).toBeNull();
});

test("закрытие окна прерывает запрос видеопотока", async () => {
  let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/preview")) {
      signal = options?.signal as AbortSignal;
      return new Promise<Response>((_, reject) => signal!.addEventListener("abort", () => reject(new Error("aborted"))));
    }
    return new Response(JSON.stringify({ configured: true, version: 1 }));
  }));
  mount();
  await waitFor(() => expect(signal).toBeDefined());
  fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
  await waitFor(() => expect(signal?.aborted).toBe(true));
});
