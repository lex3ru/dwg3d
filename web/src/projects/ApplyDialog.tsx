import { useQuery } from "@tanstack/react-query";
import { CheckCheck } from "lucide-react";
import { useEffect, useState } from "react";
import type { ProjectView } from "@/editor/Editor";
import type { UnitBrief } from "@/inventory/types";
import { ApiError, get, post } from "@/lib/api";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { FormError } from "@/ui/form";
import { Loading } from "@/ui/misc";

interface ApplyPlan {
  items: { item_id: string; floor: string; type: string; accounting: "piece" | "quantity"; candidates: (UnitBrief & { place_title: string })[]; suggested: string | null }[];
  conflicts: { item_id: string; text: string }[];
  linked_removed: number;
}

// 5.3.6 п. 7, 5.5: применить — новые предметы встают без связи, с выданной со склада единицей
// или «к закупке»; что столкнулось с расстановкой — остаётся в проекте
export function ApplyDialog({ open, onClose, project, onDone }: { open: boolean; onClose: () => void; project: ProjectView; onDone: () => void }) {
  const plan = useQuery({ queryKey: ["project-apply", project.id, project.updated_at], queryFn: () => get<ApplyPlan>(`/api/projects/${project.id}/apply`), enabled: open });
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ applied: number; kept: number; notes: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  // итог сбрасывается только при открытии окна: после «Применить» у проекта новый updated_at,
  // предпросмотр приходит заново и не должен подменять итог вопросом «Применить?» (6.1 п. 5)
  useEffect(() => {
    if (open) setDone(null);
  }, [open]);
  useEffect(() => {
    if (!plan.data || !open) return;
    setChoices(Object.fromEntries(plan.data.items.map((i) => [i.item_id, i.suggested ?? (i.accounting === "piece" ? "buy" : "")])));
    setError(null);
  }, [plan.data, open]);
  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ applied: number; kept: number; notes: string[] }>(`/api/projects/${project.id}/apply`, { version: project.version, choices });
      setDone(r);
      onDone();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };
  const issued = Object.values(choices).filter((v) => v && v !== "buy").length;
  const buy = Object.values(choices).filter((v) => v === "buy").length;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={done ? "Проект применён" : `Применить проект «${project.name}»?`}
      wide
      description={
        done
          ? `Перенесено изменений: ${done.applied}${done.kept ? `, осталось в проекте: ${done.kept}` : ""}.`
          : `Изменения перейдут в расстановку: добавится ${project.added}, переместится или изменится ${project.moved}, уберётся ${project.removed}. Со склада выдаётся ${issued} (документами «Перемещение»), к закупке — ${buy}.`
      }
      footer={
        done ? (
          <Button variant="primary" onClick={onClose}>
            Готово
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>Отмена</Button>
            <Button variant="primary" disabled={busy || !plan.data} onClick={() => void apply()}>
              <CheckCheck /> Применить
            </Button>
          </>
        )
      }
    >
      {done ? (
        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[13px]">
          {done.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      ) : !plan.data ? (
        <Loading />
      ) : (
        <div className="flex flex-col gap-3">
          {plan.data.conflicts.length > 0 && (
            <div className="rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">
              Не перенесётся и останется в проекте ({plan.data.conflicts.length}):
              <ul className="m-0 mt-1 pl-4">
                {plan.data.conflicts.map((c) => (
                  <li key={c.item_id}>{c.text}</li>
                ))}
              </ul>
            </div>
          )}
          {plan.data.linked_removed > 0 && <p className="m-0 text-[13px] text-ink-2">Убираемые учтённые вещи ({plan.data.linked_removed}) остаются числиться в своих помещениях и попадут в «Неразмещённые».</p>}
          {plan.data.items.length > 0 && (
            <table className="w-full border-collapse text-[13px]" aria-label="Новые предметы">
              <thead>
                <tr className="text-left text-xs text-ink-2">
                  <th className="border-b border-line py-1.5 font-medium">Новый предмет</th>
                  <th className="border-b border-line py-1.5 font-medium">Учёт</th>
                </tr>
              </thead>
              <tbody>
                {plan.data.items.map((i) => (
                  <tr key={i.item_id}>
                    <td className="border-b border-line py-1.5 pr-3">
                      {i.type}
                      <span className="block text-[11px] text-ink-3">{i.floor}</span>
                    </td>
                    <td className="border-b border-line py-1.5">
                      {i.accounting === "quantity" ? (
                        <span className="text-[12px] text-ink-3">количественный учёт — без связи</span>
                      ) : (
                        <select
                          aria-label={`Учёт: ${i.type}`}
                          value={choices[i.item_id] ?? ""}
                          onChange={(e) => setChoices({ ...choices, [i.item_id]: e.target.value })}
                          className="h-8 w-full rounded-md border border-line-strong bg-surface px-1.5 text-[12px]"
                        >
                          {i.candidates.map((u) => (
                            <option key={u.id} value={u.id} disabled={Object.entries(choices).some(([k, v]) => v === u.id && k !== i.item_id)}>
                              выдать со склада: {u.number ? `№ ${u.number} · ` : ""}
                              {u.title} · {u.place_title}
                            </option>
                          ))}
                          <option value="buy">к закупке</option>
                          <option value="">без учёта</option>
                        </select>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <FormError message={error} />
        </div>
      )}
    </Dialog>
  );
}
