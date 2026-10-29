// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { get } from "@/lib/api";
import { PlacePicker } from "./parts";

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), get: vi.fn() }));

// склад с ячейкой и три этажа по 50 помещений (на объёмах 8.1 — 10 000)
const tree = {
  warehouses: [{ id: "w1", key: "w:1", name: "Основной", cells: [{ id: "c1", key: "c:1", name: "Стеллаж 1", label_code: "" }] }],
  buildings: [
    {
      id: "b1",
      name: "Поликлиника",
      floors: [1, 2, 3].map((f) => ({
        id: `f${f}`,
        name: `${f} этаж`,
        rooms: Array.from({ length: 50 }, (_, i) => ({ key: `r:${f}-${i}`, title: `${f}${String(i).padStart(2, "0")} Кабинет`, number: `${f}${String(i).padStart(2, "0")}`, name: "Кабинет" })),
      })),
    },
  ],
};
const ALL = 1 + 1 + 1 + 150; // пустой пункт, склад, ячейка, помещения

beforeEach(() => {
  vi.mocked(get).mockResolvedValue(tree);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function picker(value: string | null, extra: { onlyStorage?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PlacePicker value={value} onChange={() => {}} allowEmpty {...extra} />
    </QueryClientProvider>,
  );
  const select = screen.getByLabelText<HTMLSelectElement>("Место");
  await waitFor(() => expect(vi.mocked(get)).toHaveBeenCalled());
  return select;
}

test("R-036: пока к полю не обратились, в нём только пустой пункт и выбранное место — 10 000 помещений не рисуются на каждом экране", async () => {
  const select = await picker("r:2-7");
  await waitFor(() => expect(select.selectedOptions[0]?.textContent).toBe("207 Кабинет"));
  expect(select.options).toHaveLength(2);
  expect(select.value).toBe("r:2-7");
  fireEvent.focus(select);
  expect(select.options).toHaveLength(ALL);
  expect(select.value).toBe("r:2-7");
});

test("весь список дорисовывается и при наведении, и при нажатии", async () => {
  const hovered = await picker(null);
  expect(hovered.options).toHaveLength(1);
  fireEvent.pointerEnter(hovered);
  await waitFor(() => expect(hovered.options).toHaveLength(ALL));
  cleanup();
  const pressed = await picker("c:1");
  await waitFor(() => expect(pressed.selectedOptions[0]?.textContent).toBe("Основной › Стеллаж 1"));
  fireEvent.pointerDown(pressed);
  expect(pressed.options).toHaveLength(ALL);
});

test("только склады: помещение не подставляется и в полном списке его нет", async () => {
  const select = await picker("w:1", { onlyStorage: true });
  await waitFor(() => expect(select.selectedOptions[0]?.textContent).toBe("Склад «Основной»"));
  fireEvent.focus(select);
  expect(select.options).toHaveLength(3);
});
