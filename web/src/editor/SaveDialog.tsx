import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Choice, Field, FormError } from "@/ui/form";
import type { Check, RoomProperty, RoomShape } from "./plan";

// что спрашивает окно сохранения плана: какое помещение остаётся при объединении и куда
// переходит имущество убираемых помещений — {помещение: подпись помещения плана}
export type SaveState = { preview: Check; keep: Record<number, string>; moves: Record<string, string> };

/** Убираемые помещения, где числится имущество: им нужно место в этом плане (5.1.6 п. 3, R-023). */
export const holding = (p: Check) => p.removed.filter((r) => r.property);

const shapeTitle = (r: RoomShape) => [r.number, r.name].filter(Boolean).join(" ") || "помещение без номера";

/** Помещения сохраняемого плана, куда можно перенести имущество, — те, что с подписью, по номерам. */
export const targets = (p: Check) =>
  p.rooms
    .filter((r): r is RoomShape & { label: string } => r.label !== null)
    .sort((a, b) => shapeTitle(a).localeCompare(shapeTitle(b), "ru", { numeric: true }));

/** Выбрано ли место для имущества каждого убираемого помещения. */
export const placesChosen = (s: SaveState) => holding(s.preview).every((r) => s.moves[r.id]);

const propertyText = (p: RoomProperty) =>
  [p.units ? `единиц: ${p.units}` : "", p.stock ? `позиций остатков: ${p.stock}` : ""].filter(Boolean).join(", ");

export function SaveDialog({ state, setState, onConfirm, pending, error }: {
  state: SaveState | null; setState: (s: SaveState | null) => void; onConfirm: () => void; pending: boolean; error: string | null;
}) {
  const p = state?.preview;
  const empty = p ? p.removed.filter((r) => !r.property) : [];
  const ready = state ? placesChosen(state) : false;
  return (
    <Dialog
      open={state !== null}
      onOpenChange={(o) => !o && setState(null)}
      title="Сохранить план?"
      description={p?.needs_confirmation ? "Сохранение изменит помещения — проверьте, что изменится." : "В плане есть замечания проверки."}
      footer={
        <>
          <Button onClick={() => setState(null)}>Вернуться к плану</Button>
          <Button variant="primary" onClick={onConfirm} disabled={pending || !ready}>
            Сохранить
          </Button>
        </>
      }
    >
      {p && p.issues.length > 0 && (
        <div className="rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">
          Замечаний проверки: {p.issues.length} ({p.issues.slice(0, 3).map((i) => i.message.toLowerCase()).join(", ")}
          {p.issues.length > 3 ? "…" : ""}). План с замечаниями сохранить можно; 3D и печать построятся как есть.
        </div>
      )}
      {p?.merges.map((m) => (
        <fieldset key={m.index} className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-1 p-0 text-sm font-medium">
            Помещения {m.rooms.map((r) => r.title).join(" и ")} станут одним. Какое остаётся?
          </legend>
          {m.rooms.map((r) => (
            <Choice key={r.id} name={`merge-${m.index}`} value={r.id} checked={state!.keep[m.index] === r.id} onChange={() => setState({ ...state!, keep: { ...state!.keep, [m.index]: r.id } })} title={r.title} description="номер и название остаются; предметы и имущество другого переходят сюда" />
          ))}
        </fieldset>
      ))}
      {p?.splits.map((s) => (
        <p key={s.index} className="m-0 text-sm">
          От помещения <b>{s.from.title}</b> отделилась часть — она станет новым помещением. Номер остаётся за частью с подписью; чтобы выбрать другую, передвиньте подпись.
        </p>
      ))}
      {empty.length > 0 && (
        <p className="m-0 text-sm">
          Уйдут в архив (стен вокруг больше нет): <b>{empty.map((r) => r.title).join(", ")}</b>. История остаётся.
        </p>
      )}
      {/* имущество не остаётся в архиве без ведома администратора: место выбирают явно (R-023, ADR-0008) */}
      {p && holding(p).map((r) => (
        <Field
          key={r.id}
          label={`${r.title} уйдёт в архив, а в нём числится имущество (${propertyText(r.property!)}). Куда его перенести?`}
          hint={targets(p).length ? "Единицы и остатки перейдут в выбранное помещение; связанные с предметами потом уйдут за своими предметами." : "В плане нет подписанных помещений — подпишите помещение или заранее перенесите имущество документом."}
        >
          {(f) => (
            <select {...f} value={state!.moves[r.id] ?? ""} onChange={(e) => setState({ ...state!, moves: { ...state!.moves, [r.id]: e.target.value } })} className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11">
              <option value="">— выберите помещение —</option>
              {targets(p).map((t) => (
                <option key={t.label} value={t.label}>
                  {shapeTitle(t)}
                  {t.status === "new" ? " (новое)" : ""}
                </option>
              ))}
            </select>
          )}
        </Field>
      ))}
      {p && p.rooms.filter((r) => r.status === "new").length > 0 && (
        <p className="m-0 text-sm text-ink-2">Новых помещений: {p.rooms.filter((r) => r.status === "new").length}.</p>
      )}
      <FormError message={error} />
    </Dialog>
  );
}
