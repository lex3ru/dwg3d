import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, get, patch, post } from "@/lib/api";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Choice, Field, FormError, Input } from "@/ui/form";
import { KINDS, LEVELS, type Characteristic, type Kind, type Level, type Purpose, type Tree } from "./types";

export const useTree = (archived = false) =>
  useQuery({ queryKey: ["catalog", archived], queryFn: () => get<Tree>(`/api/catalog${archived ? "?archived=true" : ""}`) });

export const usePurposes = (archived = false) =>
  useQuery({ queryKey: ["catalog", "purposes", archived], queryFn: () => get<{ items: Purpose[] }>(`/api/catalog/purposes${archived ? "?archived=true" : ""}`) });

export function useInvalidateCatalog() {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: ["catalog"] });
    client.invalidateQueries({ queryKey: ["catalog-type"] });
  };
}

// Правки одной записи идут по очереди и каждая — с версией, которую вернула предыдущая:
// быстрые правки подряд (Enter в одном поле, сразу в другом) не спорят друг с другом.
export function useSerialPatch<T extends { version: number }>(url: string, version: number, onSaved?: (next: T) => void) {
  const refresh = useInvalidateCatalog();
  const current = useRef(version);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    current.current = Math.max(current.current, version);
  }, [version]);
  const set = (values: Record<string, unknown>) => {
    const run = queue.current.then(async () => {
      try {
        const next = await patch<T>(url, { version: current.current, ...values });
        current.current = next.version;
        onSaved?.(next);
        setError(null);
        refresh();
      } catch (e) {
        setError(e as ApiError);
      }
    });
    queue.current = run;
    return run;
  };
  return { set, error };
}

// Поле значения характеристики по её виду
export function ValueInput({ c, value, onChange, disabled }: { c: Characteristic; value: unknown; onChange: (v: unknown) => void; disabled?: boolean }) {
  const cls = "h-8 w-full rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink max-md:h-11";
  if (c.kind === "bool")
    return (
      <select aria-label={c.name} className={cls} disabled={disabled} value={value === true ? "yes" : value === false ? "no" : ""} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value === "yes")}>
        <option value="">—</option>
        <option value="yes">да</option>
        <option value="no">нет</option>
      </select>
    );
  if (c.kind === "choice")
    return (
      <select aria-label={c.name} className={cls} disabled={disabled} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">—</option>
        {c.choices.map((x) => (
          <option key={x} value={x}>
            {x}
          </option>
        ))}
      </select>
    );
  return (
    <DeferredInput
      label={c.name}
      type={c.kind === "date" ? "date" : "text"}
      inputMode={c.kind === "number" ? "decimal" : undefined}
      value={value === null || value === undefined ? "" : String(value)}
      onCommit={(v) => onChange(v === "" ? null : v)}
      disabled={disabled}
      className={cls}
    />
  );
}

// Поле, которое отдаёт значение по уходу с поля или Enter
export function DeferredInput({ label, value, onCommit, className, ...rest }: { label: string; value: string; onCommit: (v: string) => void; className?: string } & Omit<React.ComponentProps<"input">, "value" | "onChange">) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <input
      aria-label={label}
      {...rest}
      value={text}
      className={className}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text !== value && onCommit(text.trim())}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

// Добавить или изменить характеристику (в наборе или свою у типа)
export function CharDialog({
  open,
  onOpenChange,
  owner,
  editing,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  owner: { set_id?: string; type_id?: string };
  editing?: Characteristic | null;
}) {
  const refresh = useInvalidateCatalog();
  const [form, setForm] = useState({ name: "", kind: "text" as Kind, unit: "", choices: "", level: "type" as Level, required: false, note: "" });
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(
      editing
        ? { name: editing.name, kind: editing.kind, unit: editing.unit, choices: editing.choices.join(" / "), level: editing.level, required: editing.required, note: editing.note }
        : { name: "", kind: "text", unit: "", choices: "", level: "type", required: false, note: "" },
    );
  }, [open, editing]);
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, choices: form.choices.split("/").map((x) => x.trim()).filter(Boolean) };
      return editing ? patch(`/api/catalog/characteristics/${editing.id}`, { ...body, version: editing.version }) : post("/api/catalog/characteristics", { ...body, ...owner });
    },
    onSuccess: () => {
      refresh();
      onOpenChange(false);
    },
    onError: (e) => setError(e as ApiError),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={editing ? "Характеристика" : "Новая характеристика"}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Название" error={error?.field === "name" ? error.message : undefined}>
          {(p) => <Input {...p} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus />}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Вид значения">
            {(p) => (
              <select {...p} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as Kind })} className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11">
                {(Object.keys(KINDS) as Kind[]).map((k) => (
                  <option key={k} value={k}>
                    {KINDS[k]}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Единица">{(p) => <Input {...p} value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} placeholder="кг, м, лм…" />}</Field>
        </div>
        {form.kind === "choice" && (
          <Field label="Варианты" hint="Через «/»: новый / хороший / изношен" error={error?.field === "choices" ? error.message : undefined}>
            {(p) => <Input {...p} value={form.choices} onChange={(e) => setForm({ ...form, choices: e.target.value })} />}
          </Field>
        )}
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-1.5 p-0 text-[13px] font-medium">Где задаётся значение</legend>
          {(Object.keys(LEVELS) as Level[]).map((l) => (
            <Choice
              key={l}
              name="level"
              value={l}
              checked={form.level === l}
              onChange={() => setForm({ ...form, level: l })}
              title={LEVELS[l]}
              description={l === "type" ? "одно на все вещи типа (вид кушетки)" : l === "model" ? "своё у каждой модели (разрешение камеры)" : "своё у каждой инвентарной единицы (дата ТО)"}
            />
          ))}
        </fieldset>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.required} onChange={(e) => setForm({ ...form, required: e.target.checked })} /> обязательная
        </label>
        <Field label="Примечание">{(p) => <Input {...p} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />}</Field>
        <FormError message={error && !error.field ? error.message : error?.field && !["name", "choices"].includes(error.field) ? error.message : null} />
        <div className="flex justify-end gap-2">
          {editing && (
            <Button
              variant="danger"
              onClick={async () => {
                await api("DELETE", `/api/catalog/characteristics/${editing.id}`);
                refresh();
                onOpenChange(false);
              }}
            >
              Удалить
            </Button>
          )}
          <Button onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
