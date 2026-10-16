import { Archive, ArchiveRestore, Plus } from "lucide-react";
import { useState } from "react";
import { ApiError, post } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { FormError, Input } from "@/ui/form";
import { Card, Empty, Loading, PageHeader } from "@/ui/misc";
import { DeferredInput, useInvalidateCatalog, usePurposes, useSerialPatch } from "./parts";
import type { Purpose } from "./types";

// Назначения помещений (5.2): норма освещённости и высота рабочей поверхности, по которым
// на этапе 7 считается освещённость помещения.
export function PurposesPage() {
  const me = useMe();
  const ro = me.role !== "admin";
  const [archived, setArchived] = useState(false);
  const list = usePurposes(archived);
  const refresh = useInvalidateCatalog();
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  return (
    <PageBody>
      <PageHeader
        title="Назначения помещений"
        subtitle="Норма освещённости и высота рабочей поверхности для каждого назначения"
        actions={
          <label className="flex items-center gap-2 text-[13px] text-ink-2">
            <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> с архивом
          </label>
        }
      />
      <FormError message={error} />
      <Card className="overflow-x-auto">
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.items.length ? (
          <Empty title="Назначений нет" />
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-2">
                {["Назначение", "Рабочая поверхность, м", "Норма, лк", "Примечание", ""].map((h) => (
                  <th key={h} className="border-b border-line px-3 py-2 font-medium whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((p) => (
                <PurposeRow key={p.id} p={p} ro={ro} onArchive={() => void act(() => post(`/api/catalog/purposes/${p.id}/${p.archived ? "unarchive" : "archive"}`))} />
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {!ro && (
        <form
          className="flex max-w-md gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) void act(() => post("/api/catalog/purposes", { name: name.trim() })).then(() => setName(""));
          }}
        >
          <Input aria-label="Новое назначение" placeholder="Новое назначение" value={name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit">
            <Plus /> Добавить
          </Button>
        </form>
      )}
    </PageBody>
  );
}

const num = (text: string) => Number.parseFloat(text.replace(",", "."));
const cell = "h-8 w-full rounded-md border border-transparent bg-transparent px-1 hover:border-line-strong focus:border-line-strong disabled:hover:border-transparent";

function PurposeRow({ p, ro, onArchive }: { p: Purpose; ro: boolean; onArchive: () => void }) {
  const { set, error } = useSerialPatch<Purpose>(`/api/catalog/purposes/${p.id}`, p.version);
  return (
    <>
      <tr className={cn(p.archived && "text-ink-3")}>
        <td className="min-w-56 border-b border-line px-3 py-1.5">
          <DeferredInput label="Назначение" disabled={ro} value={p.name} onCommit={(v) => v && void set({ name: v })} className={cn(cell, "font-medium")} />
        </td>
        <td className="w-40 border-b border-line px-3 py-1.5">
          <DeferredInput
            label={`Рабочая поверхность, ${p.name}`}
            disabled={ro}
            inputMode="decimal"
            value={String(p.surface / 1000)}
            onCommit={(v) => Number.isFinite(num(v)) && void set({ surface: Math.round(num(v) * 1000) })}
            className={cn(cell, "font-mono")}
          />
        </td>
        <td className="w-32 border-b border-line px-3 py-1.5">
          <DeferredInput
            label={`Норма освещённости, ${p.name}`}
            disabled={ro}
            inputMode="numeric"
            value={String(p.norm)}
            onCommit={(v) => Number.isFinite(num(v)) && void set({ norm: Math.round(num(v)) })}
            className={cn(cell, "font-mono")}
          />
        </td>
        <td className="border-b border-line px-3 py-1.5">
          <DeferredInput label={`Примечание, ${p.name}`} disabled={ro} value={p.note} onCommit={(v) => void set({ note: v })} className={cn(cell, "text-ink-2")} />
        </td>
        <td className="w-10 border-b border-line px-3 py-1.5">
          {!ro && (
            <Button
              size="icon"
              variant="ghost"
              aria-label={p.archived ? `Вернуть ${p.name} из архива` : `В архив ${p.name}`}
              title={p.archived ? "Вернуть из архива" : "В архив"}
              onClick={onArchive}
            >
              {p.archived ? <ArchiveRestore /> : <Archive />}
            </Button>
          )}
        </td>
      </tr>
      {error && (
        <tr>
          <td colSpan={5} className="px-3 pb-2">
            <FormError message={error.message} />
          </td>
        </tr>
      )}
    </>
  );
}
