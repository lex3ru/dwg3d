// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { Check, RoomShape } from "./plan";
import { SaveDialog, type SaveState } from "./SaveDialog";

afterEach(cleanup);

const shape = (index: number, v: Partial<RoomShape>): RoomShape => ({
  index, id: null, label: null, labels: [], number: "", name: "", area: 10, outline: [], x: 0, y: 0, status: "new", ...v,
});

// перегородку сдвинули: 215 убирается (в нём числится имущество), 217 — тоже (пустое);
// 214 остаётся, справа новая 216 и неподписанное помещение
const preview: Check = {
  issues: [],
  rooms: [
    shape(0, { label: "new-3", labels: ["new-3"], number: "216", name: "Кладовая" }),
    shape(1, { id: "r214", label: "r214", labels: ["r214"], number: "214", name: "Кабинет", status: "kept" }),
    shape(2, {}),
  ],
  merges: [],
  splits: [],
  removed: [
    { id: "r215", number: "215", name: "Кабинет", title: "215 Кабинет", property: { units: 1, stock: 2 } },
    { id: "r217", number: "217", name: "", title: "217", property: null },
  ],
  needs_confirmation: true,
  slabs: [],
};

function Page({ onConfirm }: { onConfirm: (s: SaveState) => void }) {
  const [state, setState] = useState<SaveState | null>({ preview, keep: {}, moves: {} });
  return <SaveDialog state={state} setState={setState} onConfirm={() => onConfirm(state!)} pending={false} error={null} />;
}

// R-023, 5.1.6 п. 3, ADR-0008: имущество убираемого помещения не уходит в архив молча —
// окно показывает, что там числится, и не сохраняет, пока не выбрано место в этом плане
test("имущество убираемого помещения — только в выбранное помещение плана", () => {
  const onConfirm = vi.fn();
  render(<Page onConfirm={onConfirm} />);
  const dialog = screen.getByRole("dialog", { name: "Сохранить план?" });
  const save = within(dialog).getByRole<HTMLButtonElement>("button", { name: "Сохранить" });
  expect(save.disabled).toBe(true);
  expect(dialog.textContent).toContain("Уйдут в архив (стен вокруг больше нет): 217");

  const place = within(dialog).getByLabelText<HTMLSelectElement>(/215 Кабинет уйдёт в архив.*единиц: 1, позиций остатков: 2/);
  // выбрать можно только подписанные помещения плана, и новое тоже; по номерам
  expect([...place.options].map((o) => o.text)).toEqual(["— выберите помещение —", "214 Кабинет", "216 Кладовая (новое)"]);

  fireEvent.change(place, { target: { value: "new-3" } });
  expect(save.disabled).toBe(false);
  fireEvent.click(save);
  expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ moves: { r215: "new-3" } }));
});
