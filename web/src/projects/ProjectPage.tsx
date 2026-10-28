import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, CheckCheck, Copy, FileDown, FileSpreadsheet, Map as MapIcon, Pencil, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import type { ProjectView } from "@/editor/Editor";
import { lastFloor, projectFloor } from "@/editor/floors";
import { money } from "@/inventory/types";
import { ApiError, api, get, patch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useCardTitle } from "@/shell/context";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";
import { Card, Chip, Empty, Loading, PageHeader } from "@/ui/misc";
import { ApplyDialog } from "./ApplyDialog";
import { NewProject, STATUS_TONE, useProjects } from "./ProjectsPage";

interface CompareRow {
  floor_id: string;
  floor: string;
  room: string;
  type: string;
  what: "добавлен" | "убран" | "перемещён" | "изменён";
  item_id: string;
}

interface Comparison {
  a: string;
  b: string;
  rows: CompareRow[];
  counts: Record<string, number>;
  total_a: number;
  total_b: number;
}

interface SpecRow {
  type: string;
  model: string;
  unit: string;
  need: number;
  have: number;
  buy: number;
  price: number;
  sum: number;
}

const WHAT_TONE: Record<CompareRow["what"], string> = { добавлен: "text-ok", перемещён: "text-warn", изменён: "text-accent-ink", убран: "text-bad" };

async function download(url: string) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) throw new Error("Файл не выгрузился.");
  const name = decodeURIComponent((r.headers.get("Content-Disposition") ?? "").split("''")[1] ?? "проект");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = name;
  a.click();
}

// Карточка проекта (5.3.6): что меняет, сравнение, спецификация и смета, выгрузка, применение
export function ProjectPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => get<ProjectView>(`/api/projects/${projectId}`) });
  const p = project.data;
  const others = useProjects(p?.building_id ?? null);
  const building = useQuery({
    queryKey: ["building", p?.building_id],
    queryFn: () => get<{ id: string; name: string; floors: { id: string; name: string; elevation: number }[] }>(`/api/buildings/${p!.building_id}`),
    enabled: !!p,
  });
  const tab = params.get("tab") === "spec" ? "spec" : "changes";
  const against = params.get("compare") ?? "layout";
  const comparison = useQuery({
    queryKey: ["project-compare", projectId, against, p?.version, p?.updated_at],
    queryFn: () => get<Comparison>(`/api/projects/${projectId}/compare${against !== "layout" ? `?other=${against}` : ""}`),
    enabled: !!p,
  });
  const spec = useQuery({
    queryKey: ["project-spec", projectId, p?.updated_at],
    queryFn: () => get<{ rows: SpecRow[]; total: number }>(`/api/projects/${projectId}/specification`),
    enabled: !!p && tab === "spec",
  });
  const [renaming, setRenaming] = useState(false);
  const [copying, setCopying] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useCardTitle(p ? `Проект «${p.name}»` : null);
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["project", projectId] });
    client.invalidateQueries({ queryKey: ["projects"] });
  };
  const archive = useMutation({
    mutationFn: () => patch<ProjectView>(`/api/projects/${projectId}`, { version: p!.version, archived: !p!.archived }),
    onSuccess: refresh,
    onError: (e) => setError((e as ApiError).message),
  });
  if (project.isLoading) return <Loading />;
  if (!p) return <Empty title="Проект не найден" />;
  const floors = building.data?.floors ?? [];
  // «Открыть на плане» — туда, где проект правят (R-043)
  const openFloor = projectFloor(floors, p.floor_ids, lastFloor(p.building_id));
  const planUrl = (floorId?: string, itemId?: string) => `/plan/${p.building_id}/${floorId ?? openFloor?.id ?? ""}?project=${p.id}${itemId ? `&item=${itemId}` : ""}`;
  const setTab = (t: string) =>
    setParams((x) => {
      const out = new URLSearchParams(x);
      if (t === "changes") out.delete("tab");
      else out.set("tab", t);
      return out;
    });
  const c = comparison.data;
  return (
    <PageBody>
      <PageHeader
        title={`Проект «${p.name}»`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Chip tone={STATUS_TONE[p.status]}>{p.status_title}</Chip>
            {building.data?.name} · {p.rooms.length ? p.rooms.join(", ") : "изменений пока нет"}
          </span>
        }
        actions={
          <>
            {/* этаж известен, когда загрузилось здание */}
            {openFloor ? (
              <Button variant="primary" asChild>
                <Link to={planUrl()}>
                  <MapIcon /> Открыть на плане
                </Link>
              </Button>
            ) : (
              <Button variant="primary" disabled>
                <MapIcon /> Открыть на плане
              </Button>
            )}
            <Button onClick={() => setApplying(true)} disabled={!p.changes || p.archived}>
              <CheckCheck /> Применить
            </Button>
          </>
        }
      />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" onClick={() => setRenaming(true)}>
          <Pencil /> Переименовать
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setCopying(true)}>
          <Copy /> Копия — второй вариант
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void download(`/api/projects/${p.id}/export.pdf`).catch((e: Error) => setError(e.message))}>
          <FileDown /> PDF для руководства
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void download(`/api/projects/${p.id}/export.xlsx`).catch((e: Error) => setError(e.message))}>
          <FileSpreadsheet /> Спецификация в Excel
        </Button>
        <Button size="sm" variant="ghost" onClick={() => archive.mutate()}>
          {p.archived ? <ArchiveRestore /> : <Archive />} {p.archived ? "Вернуть из архива" : "В архив"}
        </Button>
        <Button size="sm" variant="danger" onClick={() => setDeleting(true)}>
          <Trash2 /> Удалить
        </Button>
      </div>
      <FormError message={error} />
      {p.conflicts.length > 0 && (
        <Card className="border-warn/40 bg-warn-soft p-4">
          <h3 className="m-0 mb-2 flex items-center gap-2 text-sm font-semibold text-warn">
            <TriangleAlert className="size-4" /> Проект устарел: расстановку изменили там, где он что-то меняет
          </h3>
          <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[13px]">
            {p.conflicts.map((x) => (
              <li key={x.item_id} className="flex items-center gap-2">
                <span className="flex-1">{x.text}</span>
                <Link to={planUrl(x.floor_id, x.item_id)}>Показать</Link>
              </li>
            ))}
          </ul>
          <p className="m-0 mt-2 text-[12px] text-ink-2">При применении эти изменения не переносятся и остаются в проекте.</p>
        </Card>
      )}
      <div role="tablist" className="flex gap-1 border-b border-line">
        {[
          ["changes", "Изменения и сравнение"],
          ["spec", "Спецификация и смета"],
        ].map(([k, t]) => (
          <button
            key={k}
            role="tab"
            type="button"
            aria-selected={tab === k}
            onClick={() => setTab(k!)}
            className={cn("-mb-px h-10 cursor-pointer border-0 border-b-2 bg-transparent px-3 text-sm", tab === k ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink")}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "changes" ? (
        <Card className="overflow-x-auto">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
            <label className="flex items-center gap-2 text-[13px] text-ink-2">
              Сравнить с
              <select
                aria-label="Сравнить с"
                value={against}
                onChange={(e) =>
                  setParams((x) => {
                    const out = new URLSearchParams(x);
                    out.set("compare", e.target.value);
                    return out;
                  })
                }
                className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm text-ink"
              >
                <option value="layout">Как есть (расстановка)</option>
                {others.data?.items
                  .filter((x) => x.id !== p.id)
                  .map((x) => (
                    <option key={x.id} value={x.id}>
                      Проект «{x.name}»
                    </option>
                  ))}
              </select>
            </label>
            {c && (
              <span className="text-[13px] text-ink-2">
                {Object.entries(c.counts)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" · ") || "отличий нет"}
                {against !== "layout" && ` · к закупке: ${money(c.total_a)} против ${money(c.total_b)}`}
              </span>
            )}
          </div>
          {!c ? (
            <Loading />
          ) : !c.rows.length ? (
            <Empty title="Отличий нет">Откройте проект на плане и поставьте, передвиньте или уберите предметы — расстановка при этом не меняется.</Empty>
          ) : (
            <table className="w-full border-collapse text-[13px]" aria-label="Отличия">
              <thead>
                <tr className="text-left text-xs text-ink-2">
                  {["Этаж", "Помещение", "Предмет", `«${c.a}» относительно «${c.b}»`, ""].map((h) => (
                    <th key={h} className="border-b border-line px-3 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {c.rows.map((r) => (
                  <tr key={r.item_id + r.what}>
                    <td className="border-b border-line px-3 py-2">{r.floor}</td>
                    <td className="border-b border-line px-3 py-2">{r.room}</td>
                    <td className="border-b border-line px-3 py-2">{r.type}</td>
                    <td className={cn("border-b border-line px-3 py-2 font-medium", WHAT_TONE[r.what])}>{r.what}</td>
                    <td className="border-b border-line px-3 py-2 text-right">
                      {r.what !== "убран" && <Link to={planUrl(r.floor_id, r.item_id)}>на плане</Link>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      ) : (
        <Card className="overflow-x-auto">
          {!spec.data ? (
            <Loading />
          ) : !spec.data.rows.length ? (
            <Empty title="Новых предметов нет">Спецификация — что проект добавляет: сколько нужно, сколько свободно на складе, что купить и во сколько это обойдётся.</Empty>
          ) : (
            <table className="w-full border-collapse text-[13px]" aria-label="Спецификация">
              <thead>
                <tr className="text-left text-xs text-ink-2">
                  {["Тип", "Модель", "Нужно", "Есть на складе", "Купить", "Цена", "Сумма"].map((h) => (
                    <th key={h} className="border-b border-line px-3 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {spec.data.rows.map((r, i) => (
                  <tr key={i}>
                    <td className="border-b border-line px-3 py-2">{r.type}</td>
                    <td className="border-b border-line px-3 py-2 text-ink-2">{r.model || "—"}</td>
                    <td className="border-b border-line px-3 py-2 font-mono">
                      {r.need} {r.unit}
                    </td>
                    <td className="border-b border-line px-3 py-2 font-mono">{r.have}</td>
                    <td className={cn("border-b border-line px-3 py-2 font-mono", r.buy > 0 && "font-semibold")}>{r.buy}</td>
                    <td className="border-b border-line px-3 py-2 font-mono">{money(r.price)}</td>
                    <td className="border-b border-line px-3 py-2 font-mono">{money(r.sum)}</td>
                  </tr>
                ))}
                <tr>
                  <td colSpan={6} className="px-3 py-2 font-semibold">
                    Итого к закупке
                  </td>
                  <td className="px-3 py-2 font-mono font-semibold">{money(spec.data.total)}</td>
                </tr>
              </tbody>
            </table>
          )}
        </Card>
      )}
      <Rename open={renaming} onClose={() => setRenaming(false)} project={p} onDone={refresh} />
      <NewProject open={copying} onClose={() => setCopying(false)} buildingId={p.building_id} projects={[p, ...(others.data?.items.filter((x) => x.id !== p.id) ?? [])]} copyOf={p.id} />
      <ApplyDialog open={applying} onClose={() => setApplying(false)} project={p} onDone={refresh} />
      <Dialog
        open={deleting}
        onOpenChange={setDeleting}
        title="Удалить проект?"
        description={`Проект «${p.name}» и все его изменения удалятся. Расстановку это не трогает.`}
        footer={
          <>
            <Button onClick={() => setDeleting(false)}>Отмена</Button>
            <Button
              variant="danger"
              onClick={async () => {
                await api("DELETE", `/api/projects/${p.id}`);
                client.invalidateQueries({ queryKey: ["projects"] });
                navigate("/projects");
              }}
            >
              <Trash2 /> Удалить
            </Button>
          </>
        }
      />
    </PageBody>
  );
}

function Rename({ open, onClose, project, onDone }: { open: boolean; onClose: () => void; project: ProjectView; onDone: () => void }) {
  const [name, setName] = useState(project.name);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) setName(project.name);
  }, [open, project.name]);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Переименовать проект"
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button
            variant="primary"
            onClick={async () => {
              try {
                await patch(`/api/projects/${project.id}`, { version: project.version, name });
                onDone();
                onClose();
              } catch (e) {
                setError((e as ApiError).message);
              }
            }}
          >
            Сохранить
          </Button>
        </>
      }
    >
      <Field label="Название">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
      <FormError message={error} />
    </Dialog>
  );
}
