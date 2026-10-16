import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, get, post } from "@/lib/api";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Choice, Field, FormError } from "@/ui/form";
import { Card, Chip, Empty, Loading, PageHeader } from "@/ui/misc";
import { STATUS } from "./DocumentsPage";
import { PlacePicker, usePlaceTree } from "./parts";
import { dateRu, type Doc } from "./types";

// Инвентаризация (5.4.6, 6.5.8): ведомости — черновые (идёт обход) и проведённые
export function CountsPage() {
  const navigate = useNavigate();
  const list = useQuery({ queryKey: ["inventory", "counts"], queryFn: () => get<{ items: Doc[] }>("/api/inventory/counts") });
  const [creating, setCreating] = useState(false);
  return (
    <PageBody>
      <PageHeader
        title="Инвентаризация"
        subtitle="Ведомость на места → обход с телефона по QR-меткам → проведение расхождений"
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus /> Новая ведомость
          </Button>
        }
      />
      <Card className="overflow-x-auto">
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.items.length ? (
          <Empty title="Ведомостей нет">Сформируйте ведомость на этаж, помещение или склад — и обходите места с телефоном.</Empty>
        ) : (
          <ul className="m-0 list-none p-0">
            {list.data.items.map((d) => (
              <li key={d.id}>
                <button type="button" onClick={() => navigate(`/inventory/${d.id}`)} className="flex min-h-12 w-full cursor-pointer items-center gap-3 border-0 border-b border-line bg-transparent px-4 py-2 text-left hover:bg-surface-2">
                  <span className="min-w-0 flex-1">
                    <Link to={`/inventory/${d.id}`} className="font-medium text-ink">
                      {d.title}
                    </Link>
                    <span className="block text-[12px] text-ink-3">от {dateRu(d.date)} · {d.created_by}</span>
                  </span>
                  <Chip tone={STATUS[d.status][1]}>{d.status === "draft" ? "идёт обход" : STATUS[d.status][0]}</Chip>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <NewCount open={creating} onClose={() => setCreating(false)} />
    </PageBody>
  );
}

function NewCount({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const tree = usePlaceTree();
  const [what, setWhat] = useState<"floor" | "warehouse" | "place">("floor");
  const [floor, setFloor] = useState("");
  const [warehouse, setWarehouse] = useState("");
  const [place, setPlace] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () =>
      post<{ id: string }>("/api/inventory/counts", {
        floor_id: what === "floor" ? floor || null : null,
        warehouse_id: what === "warehouse" ? warehouse || null : null,
        places: what === "place" && place ? [place] : [],
      }),
    onSuccess: (c) => navigate(`/inventory/${c.id}`),
    onError: (e) => setError((e as ApiError).message),
  });
  const select = "h-9 w-full rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11";
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Новая ведомость"
      description="В ведомости — всё, что числится в выбранных местах."
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={create.isPending} onClick={() => create.mutate()}>
            Сформировать
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-2">
        <Choice name="count-what" value="floor" checked={what === "floor"} onChange={() => setWhat("floor")} title="Этаж" description="Все помещения этажа" />
        {what === "floor" && (
          <Field label="Этаж">
            {(p) => (
              <select {...p} value={floor} onChange={(e) => setFloor(e.target.value)} className={select}>
                <option value="">— выберите —</option>
                {tree.data?.buildings.flatMap((b) =>
                  b.floors.map((f) => (
                    <option key={f.id} value={f.id}>
                      {b.name} · {f.name}
                    </option>
                  )),
                )}
              </select>
            )}
          </Field>
        )}
        <Choice name="count-what" value="warehouse" checked={what === "warehouse"} onChange={() => setWhat("warehouse")} title="Склад" description="Склад со всеми ячейками" />
        {what === "warehouse" && (
          <Field label="Склад">
            {(p) => (
              <select {...p} value={warehouse} onChange={(e) => setWarehouse(e.target.value)} className={select}>
                <option value="">— выберите —</option>
                {tree.data?.warehouses.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
        <Choice name="count-what" value="place" checked={what === "place"} onChange={() => setWhat("place")} title="Одно место" description="Помещение или ячейка" />
        {what === "place" && <PlacePicker value={place} onChange={setPlace} label="Место" />}
        <FormError message={error} />
      </div>
    </Dialog>
  );
}
