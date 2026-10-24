// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { ProjectView } from "@/editor/Editor";
import { get, post } from "@/lib/api";
import { ApplyDialog } from "./ApplyDialog";

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), get: vi.fn(), post: vi.fn() }));

afterEach(cleanup);

const preview = () => ({ items: [], conflicts: [], linked_removed: 0 });

// Страница проекта: после «Применить» она перечитывает проект, и у него новый updated_at
function Page() {
  const [project, setProject] = useState({ id: "p1", name: "Процедурный 301", added: 1, moved: 0, removed: 0, updated_at: "t1", version: 1 } as ProjectView);
  return <ApplyDialog open onClose={() => {}} project={project} onDone={() => setProject({ ...project, added: 0, updated_at: "t2", version: 2 })} />;
}

// R-007, 5.3.6 п. 7, 6.1 п. 5: итог применения не подменяется вопросом «Применить?», когда
// предпросмотр по новому updated_at приходит уже после итога
test("после «Применить» окно показывает итог и после нового предпросмотра", async () => {
  let release!: (plan: ReturnType<typeof preview>) => void;
  vi.mocked(get)
    .mockResolvedValueOnce(preview())
    .mockReturnValueOnce(new Promise((r) => (release = r)));
  vi.mocked(post).mockResolvedValue({ applied: 1, kept: 0, notes: ["Оформлено «Перемещение № 7»"] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Page />
    </QueryClientProvider>,
  );

  const ask = await screen.findByRole("dialog", { name: "Применить проект «Процедурный 301»?" });
  const apply = within(ask).getByRole<HTMLButtonElement>("button", { name: "Применить" });
  await waitFor(() => expect(apply.disabled).toBe(false));
  fireEvent.click(apply);
  await screen.findByRole("dialog", { name: "Проект применён" });
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));

  // новый предпросмотр приходит; внутри act React успевает отрисовать его и выполнить эффекты
  await act(async () => {
    release(preview());
    await new Promise((r) => setTimeout(r, 50));
  });

  const done = screen.getByRole("dialog", { name: "Проект применён" });
  expect(within(done).getByText("Оформлено «Перемещение № 7»")).toBeTruthy();
  expect(within(done).queryByRole("button", { name: "Применить" })).toBeNull();
});
