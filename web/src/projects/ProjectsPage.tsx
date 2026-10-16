import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitCompareArrows, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import type { ProjectView } from "@/editor/Editor";
import { money } from "@/inventory/types";
import { ApiError, get, post } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { BuildingSummary } from "@/pages/Buildings";
import { lastBuilding } from "@/pages/PlanIndex";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";
import { Card, Chip, Empty, Loading, PageHeader, type Tone } from "@/ui/misc";

export const STATUS_TONE: Record<ProjectView["status"], Tone> = { draft: "accent", outdated: "warn", applied: "ok", archived: "muted" };

export const useProjects = (buildingId: string | null, archived = false) =>
  useQuery({
    queryKey: ["projects", buildingId, archived],
    queryFn: () => get<{ items: ProjectView[] }>(`/api/projects?building_id=${buildingId}${archived ? "&archived=true" : ""}`),
    enabled: !!buildingId,
  });

// 6.5.7: список проектов здания — что меняет, статус, смета; создать, сравнить
export function ProjectsPage() {
  const navigate = useNavigate();
  // здание — из бокового меню (и адреса)
  const [params] = useSearchParams();
  const buildings = useQuery({ queryKey: ["buildings", false], queryFn: () => get<{ items: BuildingSummary[] }>("/api/buildings") });
  const all = buildings.data?.items ?? [];
  const wanted = params.get("building") ?? lastBuilding();
  const current = all.find((b) => b.id === wanted) ?? all[0];
  const buildingId = current?.id ?? null;
  const [archived, setArchived] = useState(false);
  const list = useProjects(buildingId, archived);
  const [creating, setCreating] = useState(false);
  const [comparing, setComparing] = useState(false);
  if (buildings.isLoading) return <Loading />;
  const items = list.data?.items ?? [];
  return (
    <PageBody>
      <PageHeader
        title="Проекты"
        subtitle="Предлагаемые изменения расстановки. Пока проект не применён, расстановка не меняется."
        actions={
          <>
            <Button onClick={() => setComparing(true)} disabled={!items.length}>
              <GitCompareArrows /> Сравнить
            </Button>
            <Button variant="primary" onClick={() => setCreating(true)} disabled={!buildingId}>
              <Plus /> Новый проект
            </Button>
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium">{current?.name}</span>
        <label className="flex items-center gap-2 text-[13px] text-ink-2">
          <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> с архивом
        </label>
      </div>
      <Card className="overflow-x-auto">
        {list.isLoading ? (
          <Loading />
        ) : !items.length ? (
          <Empty title="Проектов нет">Проект — это вариант перестановки или оснащения: «Процедурный 301», «Видеонаблюдение холла». Создайте его и правьте в редакторе.</Empty>
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-2">
                {["Проект", "Что меняет", "Изменений", "Статус", "К закупке", "Обновлён"].map((h) => (
                  <th key={h} className="border-b border-line px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} className="cursor-pointer hover:bg-surface-2" onClick={() => navigate(`/projects/${p.id}`)}>
                  <td className="border-b border-line px-3 py-2 font-medium">
                    <Link to={`/projects/${p.id}`} className="text-ink">
                      {p.name}
                    </Link>
                    <div className="text-[11px] text-ink-3">{p.created_by}</div>
                  </td>
                  <td className="border-b border-line px-3 py-2 text-ink-2">{p.rooms.length ? `${p.rooms.slice(0, 3).join(", ")}${p.rooms.length > 3 ? ` и ещё ${p.rooms.length - 3}` : ""}` : "—"}</td>
                  <td className="border-b border-line px-3 py-2 font-mono text-[12px]">
                    <span className="text-[#2E7D32]">+{p.added}</span> <span className="text-[#EF6C00]">~{p.moved}</span> <span className="text-[#C62828]">−{p.removed}</span>
                  </td>
                  <td className="border-b border-line px-3 py-2">
                    <Chip tone={STATUS_TONE[p.status]}>{p.status_title}</Chip>
                  </td>
                  <td className="border-b border-line px-3 py-2 font-mono">{money(p.total)}</td>
                  <td className="border-b border-line px-3 py-2 text-ink-2">{formatDateTime(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {buildingId && <NewProject open={creating} onClose={() => setCreating(false)} buildingId={buildingId} projects={items} />}
      <CompareDialog open={comparing} onClose={() => setComparing(false)} projects={items} />
    </PageBody>
  );
}

export function NewProject({ open, onClose, buildingId, projects, copyOf }: { open: boolean; onClose: () => void; buildingId: string; projects: ProjectView[]; copyOf?: string }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [source, setSource] = useState(copyOf ?? "");
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    if (open) {
      setSource(copyOf ?? "");
      setName(copyOf ? `${projects.find((p) => p.id === copyOf)?.name ?? ""} — вариант 2` : "");
      setError(null);
    }
  }, [open, copyOf, projects]);
  const create = useMutation({
    mutationFn: () => post<ProjectView>("/api/projects", { building_id: buildingId, name, copy_of: source || null }),
    onSuccess: (p) => {
      client.invalidateQueries({ queryKey: ["projects"] });
      onClose();
      navigate(`/projects/${p.id}`);
    },
    onError: (e) => setError(e as ApiError),
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Новый проект"
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={create.isPending || !name.trim()} onClick={() => create.mutate()}>
            Создать
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Название" error={error?.field === "name" ? error.message : undefined}>
          {(p) => <Input {...p} autoFocus value={name} placeholder="Процедурный 301" onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Основа">
          {(p) => (
            <select {...p} value={source} onChange={(e) => setSource(e.target.value)} className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11">
              <option value="">текущая расстановка</option>
              {projects.map((x) => (
                <option key={x.id} value={x.id}>
                  копия проекта «{x.name}»
                </option>
              ))}
            </select>
          )}
        </Field>
        <FormError message={error && error.field !== "name" ? error.message : null} />
      </div>
    </Dialog>
  );
}

function CompareDialog({ open, onClose, projects }: { open: boolean; onClose: () => void; projects: ProjectView[] }) {
  const navigate = useNavigate();
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  useEffect(() => {
    if (open) {
      setA(projects[0]?.id ?? "");
      setB(projects[1]?.id ?? "");
    }
  }, [open, projects]);
  const select = "h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11";
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Сравнить"
      description="Проект с расстановкой или с другим проектом — что добавлено, убрано, перемещено и во сколько обойдётся."
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={!a || a === b} onClick={() => navigate(`/projects/${a}?compare=${b || "layout"}`)}>
            Сравнить
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
        <Field label="Проект">
          {(p) => (
            <select {...p} value={a} onChange={(e) => setA(e.target.value)} className={select}>
              {projects.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="С чем">
          {(p) => (
            <select {...p} value={b} onChange={(e) => setB(e.target.value)} className={select}>
              <option value="">Как есть (расстановка)</option>
              {projects
                .filter((x) => x.id !== a)
                .map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
            </select>
          )}
        </Field>
      </div>
    </Dialog>
  );
}
