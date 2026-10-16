import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Pencil, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError, api, get, patch, post, query } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import type { FloorInfo } from "@/editor/plan";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";
import { Card, Chip, Empty, Loading, PageHeader } from "@/ui/misc";

export interface BuildingSummary {
  id: string;
  name: string;
  address: string;
  archived: boolean;
  floors: number;
  rooms: number;
  version: number;
}

interface BuildingFull extends Omit<BuildingSummary, "floors"> {
  floors: FloorInfo[];
}

const elevationText = (mm: number) => (mm === 0 ? "±0,000" : `${mm > 0 ? "+" : "−"}${(Math.abs(mm) / 1000).toLocaleString("ru-RU", { minimumFractionDigits: 3 })}`);

// Здания и этажи (5.1.1, 5.1.2). Загрузка чертежей появится на этапе 2.
export function Buildings() {
  const [params, setParams] = useSearchParams();
  const [archived, setArchived] = useState(false);
  const list = useQuery({ queryKey: ["buildings", archived], queryFn: () => get<{ items: BuildingSummary[] }>(`/api/buildings${query({ archived: archived ? "true" : undefined })}`) });
  const [creating, setCreating] = useState(false);
  const selected = params.get("b") ?? list.data?.items[0]?.id ?? null;
  return (
    <PageBody>
      <PageHeader
        title="Здания"
        subtitle="Здания, этажи и их планы"
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus /> Новое здание
          </Button>
        }
      />
      <div className="grid items-start gap-5 lg:grid-cols-[320px_1fr]">
        <Card className="overflow-hidden">
          {list.isLoading ? (
            <Loading />
          ) : !list.data?.items.length ? (
            <Empty title="Зданий нет">Создайте первое — «Новое здание».</Empty>
          ) : (
            <ul className="m-0 list-none p-0">
              {list.data.items.map((b) => (
                <li key={b.id}>
                  <button
                    type="button"
                    onClick={() => setParams({ b: b.id })}
                    className={cn("flex w-full cursor-pointer flex-col gap-0.5 border-0 border-b border-line bg-transparent px-4 py-3 text-left", selected === b.id ? "bg-accent-soft" : "hover:bg-surface-2")}
                  >
                    <span className="flex items-center gap-2 font-medium text-ink">
                      {b.name} {b.archived && <Chip>в архиве</Chip>}
                    </span>
                    <span className="text-[13px] text-ink-2">{[b.address, `этажей ${b.floors}`, `помещений ${b.rooms}`].filter(Boolean).join(" · ")}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <label className="flex items-center gap-2 px-4 py-3 text-[13px] text-ink-2">
            <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> показывать здания в архиве
          </label>
        </Card>
        {selected ? <BuildingCard id={selected} /> : null}
      </div>
      <BuildingDialog open={creating} onOpenChange={setCreating} onDone={(b) => setParams({ b: b.id })} />
    </PageBody>
  );
}

function BuildingCard({ id }: { id: string }) {
  const client = useQueryClient();
  const [, setParams] = useSearchParams();
  const building = useQuery({ queryKey: ["building", id], queryFn: () => get<BuildingFull>(`/api/buildings/${id}`) });
  const [editing, setEditing] = useState(false);
  const [floorDialog, setFloorDialog] = useState<FloorInfo | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["building", id] });
    client.invalidateQueries({ queryKey: ["buildings"] });
  };
  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: refresh,
    onError: (e) => setError((e as ApiError).message),
  });
  if (building.isLoading) return <Loading />;
  if (!building.data) return null;
  const b = building.data;
  const floors = [...b.floors].reverse();
  return (
    <Card className="flex flex-col">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line p-4">
        <div>
          <h2 className="m-0 flex items-center gap-2 text-lg font-semibold">
            {b.name} {b.archived && <Chip>в архиве</Chip>}
          </h2>
          <div className="text-[13px] text-ink-2">{b.address || "адрес не указан"}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setEditing(true)}>
            <Pencil /> Переименовать
          </Button>
          <Button size="sm" variant="primary" onClick={() => setFloorDialog("new")}>
            <Plus /> Добавить этаж
          </Button>
          <Button size="sm" onClick={() => act.mutate(() => post(`/api/buildings/${id}/${b.archived ? "unarchive" : "archive"}`))}>
            {b.archived ? <ArchiveRestore /> : <Archive />} {b.archived ? "Вернуть из архива" : "В архив"}
          </Button>
          {!b.floors.length && (
            <Button
              size="sm"
              variant="danger"
              onClick={() =>
                act.mutate(async () => {
                  await api("DELETE", `/api/buildings/${id}`);
                  setParams({});
                })
              }
            >
              <Trash2 /> Удалить
            </Button>
          )}
        </div>
      </div>
      <FormError message={error} />
      {!floors.length ? (
        <Empty title="Этажей нет">Добавьте этаж — потом нарисуйте его план в редакторе.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-xs text-ink-2">
                {["Этаж", "Отметка пола", "Высота", "Помещений", "План", ""].map((h) => (
                  <th key={h} className="border-b border-line px-4 py-2.5 font-medium whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {floors.map((f) => (
                <tr key={f.id}>
                  <td className="border-b border-line px-4 py-3 font-medium">{f.name}</td>
                  <td className="border-b border-line px-4 py-3 font-mono text-[13px]">{elevationText(f.elevation)}</td>
                  <td className="border-b border-line px-4 py-3 font-mono text-[13px]">{(f.height / 1000).toLocaleString("ru-RU", { minimumFractionDigits: 2 })} м</td>
                  <td className="border-b border-line px-4 py-3">{f.rooms}</td>
                  <td className="border-b border-line px-4 py-3 text-[13px] text-ink-2">{f.walls ? `сохранён ${formatDateTime(f.plan_saved_at)}` : "не нарисован"}</td>
                  <td className="border-b border-line px-4 py-3">
                    <div className="flex justify-end gap-1.5">
                      <Button size="sm" asChild>
                        <Link to={`/plan/${b.id}/${f.id}`}>Открыть</Link>
                      </Button>
                      <Button size="sm" variant="ghost" aria-label={`Изменить ${f.name}`} onClick={() => setFloorDialog(f)}>
                        <Pencil />
                      </Button>
                      {!f.walls && !f.rooms && (
                        <Button size="sm" variant="ghost" aria-label={`Удалить ${f.name}`} onClick={() => act.mutate(() => api("DELETE", `/api/floors/${f.id}`))}>
                          <Trash2 />
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="m-0 px-4 py-3 text-[13px] text-ink-2">Загрузка чертежей DWG и DXF появится на этапе 2 «Перевод чертежей».</p>
      <BuildingDialog open={editing} onOpenChange={setEditing} building={b} onDone={refresh} />
      <FloorDialog building={b} floor={floorDialog} onClose={() => setFloorDialog(null)} onDone={refresh} />
    </Card>
  );
}

function BuildingDialog({ open, onOpenChange, building, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; building?: BuildingFull; onDone: (b: BuildingFull) => void }) {
  const client = useQueryClient();
  const [name, setName] = useState(building?.name ?? "");
  const [address, setAddress] = useState(building?.address ?? "");
  const [error, setError] = useState<ApiError | null>(null);
  const save = useMutation({
    mutationFn: () => (building ? patch<BuildingFull>(`/api/buildings/${building.id}`, { version: building.version, name, address }) : post<BuildingFull>("/api/buildings", { name, address })),
    onSuccess: (b) => {
      client.invalidateQueries({ queryKey: ["buildings"] });
      onOpenChange(false);
      onDone(b);
    },
    onError: (e) => setError(e as ApiError),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    save.mutate();
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={building ? "Здание" : "Новое здание"}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Название" error={error?.field === "name" ? error.message : undefined}>
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} placeholder="Поликлиника" required autoFocus />}
        </Field>
        <Field label="Адрес">
          {(p) => <Input {...p} value={address} onChange={(e) => setAddress(e.target.value)} placeholder="ул. Садовая, 12" />}
        </Field>
        <FormError message={error && error.field !== "name" ? error.message : null} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {building ? "Сохранить" : "Создать"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function FloorDialog({ building, floor, onClose, onDone }: { building: Pick<BuildingFull, "id" | "floors">; floor: FloorInfo | "new" | null; onClose: () => void; onDone: (floor: FloorInfo) => void }) {
  const editing = floor && floor !== "new" ? floor : null;
  const top = building.floors[building.floors.length - 1];
  const [name, setName] = useState("");
  const [elevation, setElevation] = useState("");
  const [height, setHeight] = useState("3300");
  const [copyFrom, setCopyFrom] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [lastKey, setLastKey] = useState<string | null>(null);
  const key = floor === "new" ? "new" : (editing?.id ?? null);
  if (key !== lastKey) {
    setLastKey(key);
    setName(editing?.name ?? `${building.floors.length + 1} этаж`);
    setElevation(String(editing ? editing.elevation : top ? top.elevation + top.height : 0));
    setHeight(String(editing?.height ?? top?.height ?? 3300));
    setCopyFrom("");
    setError(null);
  }
  const save = useMutation({
    mutationFn: () => {
      const body = { name, elevation: Number(elevation), height: Number(height) };
      return editing ? patch<FloorInfo>(`/api/floors/${editing.id}`, { ...body, version: editing.version }) : post<FloorInfo>(`/api/buildings/${building.id}/floors`, { ...body, copy_bearing_from: copyFrom || null });
    },
    onSuccess: (floor) => {
      onDone(floor);
      onClose();
    },
    onError: (e) => setError(e as ApiError),
  });
  return (
    <Dialog open={floor !== null} onOpenChange={(o) => !o && onClose()} title={editing ? `Этаж «${editing.name}»` : "Новый этаж"}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
        className="flex flex-col gap-4"
      >
        <Field label="Название" error={error?.field === "name" ? error.message : undefined}>
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} required autoFocus />}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Отметка пола, мм" hint="От уровня первого этажа; этажи упорядочиваются по ней.">
            {(p) => <Input {...p} inputMode="numeric" value={elevation} onChange={(e) => setElevation(e.target.value)} />}
          </Field>
          <Field label="Высота этажа, мм" hint="Для 3D и подвесного." error={error?.field === "height" ? error.message : undefined}>
            {(p) => <Input {...p} inputMode="numeric" value={height} onChange={(e) => setHeight(e.target.value)} />}
          </Field>
        </div>
        {!editing && building.floors.length > 0 && (
          <Field label="Несущие стены — как на этаже" hint="Перенести несущие стены и колонны как основу нового этажа.">
            {(p) => (
              <select {...p} value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)} className="h-9 rounded-lg border border-line-strong bg-surface px-2.5 text-sm max-md:h-11">
                <option value="">не переносить</option>
                {[...building.floors].reverse().map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
        <FormError message={error && error.field !== "name" && error.field !== "height" ? error.message : null} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {editing ? "Сохранить" : "Добавить"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
