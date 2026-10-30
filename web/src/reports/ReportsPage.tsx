import { useMutation, useQuery } from "@tanstack/react-query";
import { Archive, FileDown } from "lucide-react";
import { type MouseEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useTree } from "@/catalog/parts";
import type { ProjectView } from "@/editor/Editor";
import { PlacePicker, usePlaceTree } from "@/inventory/parts";
import { today, type Doc } from "@/inventory/types";
import { ApiError, get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { CancelJob, type Job, useJob, watchJob } from "@/lib/jobs";
import type { BuildingSummary } from "@/pages/Buildings";
import { lastBuilding } from "@/pages/PlanIndex";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { FormError, Input } from "@/ui/form";
import { Card, Loading, PageHeader } from "@/ui/misc";

interface Param {
  key: string;
  title: string;
  kind: "building" | "floor" | "place" | "date" | "project" | "count" | "document" | "choice" | "layers";
  required: boolean;
  choices: [string, string][];
  multiple: boolean;
}

interface Definition {
  key: string;
  title: string;
  about: string;
  formats: ("pdf" | "xlsx" | "dxf")[];
  scenarios: string;
  params: Param[];
}

const FORMAT = { pdf: "PDF", xlsx: "Excel", dxf: "DXF" } as const;

async function download(url: string) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) {
    const e = await r.json().catch(() => null);
    throw new Error(e?.error?.message ?? "Отчёт не построился.");
  }
  const name = decodeURIComponent((r.headers.get("Content-Disposition") ?? "").split("''")[1] ?? "отчёт");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = name;
  a.click();
}

// Отчёты (5.6): выбор, параметры, выгрузка; полная выгрузка здания (7.4)
export function ReportsPage() {
  const [params] = useSearchParams();
  const defs = useQuery({ queryKey: ["reports"], queryFn: () => get<{ items: Definition[] }>("/api/reports") });
  const buildings = useQuery({ queryKey: ["buildings", false], queryFn: () => get<{ items: BuildingSummary[] }>("/api/buildings") });
  const all = buildings.data?.items ?? [];
  const building = all.find((b) => b.id === (params.get("building_id") ?? lastBuilding())) ?? all[0];
  const [open, setOpen] = useState<string | null>(params.get("report"));
  if (defs.isLoading || buildings.isLoading) return <Loading />;
  return (
    <PageBody>
      <PageHeader title="Отчёты" subtitle="Выберите отчёт, задайте параметры и выгрузите в Excel или PDF." />
      {/* items-start: раскрытый отчёт не растягивает соседний в той же строке (R-046) */}
      <div className="grid items-start gap-3 md:grid-cols-2">
        {defs.data?.items.map((d) => (
          <Card key={d.key} className={cn("flex flex-col gap-2 p-4", open === d.key && "border-accent")}>
            <button type="button" onClick={() => setOpen(open === d.key ? null : d.key)} className="cursor-pointer border-0 bg-transparent p-0 text-left" aria-expanded={open === d.key}>
              <h3 className="m-0 text-sm font-semibold">{d.title}</h3>
              <p className="m-0 text-[12px] text-ink-2">
                {d.about}
                {d.scenarios && <span className="text-ink-3"> · {d.scenarios}</span>}
              </p>
            </button>
            {open === d.key && <ReportForm def={d} buildingId={building?.id ?? ""} initial={Object.fromEntries(params.entries())} />}
          </Card>
        ))}
      </div>
      {building && <FullExport building={building} />}
    </PageBody>
  );
}

function ReportForm({ def, buildingId, initial }: { def: Definition; buildingId: string; initial: Record<string, string> }) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const p of def.params) {
      if (initial[p.key]) out[p.key] = initial[p.key]!;
      else if (p.kind === "building") out[p.key] = buildingId;
      else if (p.kind === "date" && p.key !== "since") out[p.key] = today();
      else if (p.kind === "choice" && !p.multiple && p.choices.length) out[p.key] = p.choices[0]![0];
    }
    return out;
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const set = (k: string, v: string) => setValues((x) => ({ ...x, [k]: v }));
  const run = async (fmt: string) => {
    setBusy(fmt);
    setError(null);
    try {
      const q = new URLSearchParams(Object.entries(values).filter(([, v]) => v)).toString();
      await download(`/api/reports/${def.key}.${fmt}${q ? `?${q}` : ""}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-2" aria-label={`Параметры: ${def.title}`}>
      {def.params.map((p) => (
        <ParamField key={p.key} p={p} value={values[p.key] ?? ""} onChange={(v) => set(p.key, v)} buildingId={values.building_id || buildingId} />
      ))}
      <FormError message={error} />
      <div className="flex flex-wrap gap-2">
        {def.formats.map((f) => (
          <Button key={f} size="sm" variant={f === def.formats[0] ? "primary" : "secondary"} disabled={!!busy} onClick={() => void run(f)}>
            <FileDown /> {busy === f ? "Строю…" : FORMAT[f]}
          </Button>
        ))}
      </div>
    </div>
  );
}

function ParamField({ p, value, onChange, buildingId }: { p: Param; value: string; onChange: (v: string) => void; buildingId: string }) {
  const tree = usePlaceTree();
  const catalog = useTree();
  const buildings = useQuery({ queryKey: ["buildings", false], queryFn: () => get<{ items: BuildingSummary[] }>("/api/buildings"), enabled: p.kind === "building" });
  const projects = useQuery({ queryKey: ["projects", buildingId, false], queryFn: () => get<{ items: ProjectView[] }>(`/api/projects?building_id=${buildingId}`), enabled: p.kind === "project" && !!buildingId });
  const counts = useQuery({ queryKey: ["inventory", "counts"], queryFn: () => get<{ items: Doc[] }>("/api/inventory/counts"), enabled: p.kind === "count" });
  const docs = useQuery({ queryKey: ["inventory", "documents", {}], queryFn: () => get<{ items: Doc[] }>("/api/inventory/documents"), enabled: p.kind === "document" });
  const select = "h-9 w-full rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11";
  const empty = !p.required ? <option value="">— любое —</option> : <option value="">— выберите —</option>;
  const label = `${p.title}${p.required ? "" : " (необязательно)"}`;
  let control;
  if (p.kind === "building")
    control = (
      <select aria-label={p.title} value={value} onChange={(e) => onChange(e.target.value)} className={select}>
        {empty}
        {buildings.data?.items.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
          </option>
        ))}
      </select>
    );
  else if (p.kind === "floor")
    control = (
      <select aria-label={p.title} value={value} onChange={(e) => onChange(e.target.value)} className={select}>
        {p.required ? <option value="">— выберите —</option> : <option value="">все этажи здания</option>}
        {tree.data?.buildings
          .filter((b) => !buildingId || b.id === buildingId)
          .flatMap((b) =>
            b.floors.map((f) => (
              <option key={f.id} value={f.id}>
                {b.name} · {f.name}
              </option>
            )),
          )}
      </select>
    );
  else if (p.kind === "place") control = <PlacePicker value={value || null} onChange={(v) => onChange(v ?? "")} label={p.title} allowEmpty={!p.required} emptyTitle={p.required ? "— выберите —" : "все места"} />;
  else if (p.kind === "date") control = <Input type="date" aria-label={p.title} max={today()} value={value} onChange={(e) => onChange(e.target.value)} />;
  else if (p.kind === "project")
    control = (
      <select aria-label={p.title} value={value} onChange={(e) => onChange(e.target.value)} className={select}>
        {empty}
        {projects.data?.items.map((x) => (
          <option key={x.id} value={x.id}>
            {x.name}
          </option>
        ))}
      </select>
    );
  else if (p.kind === "count" || p.kind === "document")
    control = (
      <select aria-label={p.title} value={value} onChange={(e) => onChange(e.target.value)} className={select}>
        {empty}
        {(p.kind === "count" ? counts.data?.items : docs.data?.items)?.map((d) => (
          <option key={d.id} value={d.id}>
            {d.title}
          </option>
        ))}
      </select>
    );
  else if (p.kind === "layers" || (p.kind === "choice" && p.multiple)) {
    const options: [string, string][] = p.kind === "layers" ? (catalog.data?.layers.map((l) => [l.id, l.name] as [string, string]) ?? []) : p.choices;
    const chosen = new Set(value.split(",").filter(Boolean));
    control = (
      <div className="flex flex-wrap gap-x-3 gap-y-1" role="group" aria-label={p.title}>
        {options.map(([v, t]) => (
          <label key={v} className="flex items-center gap-1.5 text-[13px]">
            <input
              type="checkbox"
              checked={chosen.has(v)}
              onChange={(e) => {
                const next = new Set(chosen);
                if (e.target.checked) next.add(v);
                else next.delete(v);
                onChange([...next].join(","));
              }}
            />
            {t}
          </label>
        ))}
      </div>
    );
  } else
    control = (
      <select aria-label={p.title} value={value} onChange={(e) => onChange(e.target.value)} className={select}>
        {p.choices.map(([v, t]) => (
          <option key={v} value={v}>
            {t}
          </option>
        ))}
      </select>
    );
  return (
    <div className="flex flex-col gap-1 text-[12px] text-ink-2">
      {label}
      {control}
    </div>
  );
}

const EXPORT_KEY = "full-export-job";
const GONE = "Архива больше нет. Соберите выгрузку заново.";

// R-027: архив удаляют по сроку, в резервной копии его нет — до скачивания сервер говорит, есть ли
// он (HEAD), иначе браузер покажет лишь сбой загрузки; почему архива нет — в итоге задачи
export function ArchiveLink({ job }: { job: Job }) {
  const [gone, setGone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const deleted = typeof job.result?.deleted === "string" ? job.result.deleted : null;
  const href = `/api/reports/exports/${job.id}`;
  const fetchArchive = async (e: MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    setError(null);
    const head = await fetch(href, { method: "HEAD", credentials: "same-origin" }).catch(() => null);
    if (head?.ok) {
      const a = document.createElement("a");
      a.href = href;
      a.download = "";
      a.click();
      return;
    }
    if (head?.status !== 404) return setError(head ? "Архив не скачался — попробуйте ещё раз." : "Нет связи с сервером.");
    // у HEAD нет тела — почему архива нет, скажет GET: на удалённый архив ответ короткий
    const body = await fetch(href, { credentials: "same-origin" })
      .then((r) => r.json())
      .catch(() => null);
    setGone(body?.error?.message ?? GONE);
  };
  if (deleted || gone) {
    return (
      <p className="m-0 text-[13px] text-ink-2" role="status">
        {deleted ?? gone}
      </p>
    );
  }
  return (
    <>
      <a href={href} download onClick={fetchArchive} className="text-[13px]">
        Скачать архив
      </a>
      <FormError message={error} />
    </>
  );
}

// 7.4: архив здания — таблицы Excel и все файлы; фоновой задачей
function FullExport({ building }: { building: BuildingSummary }) {
  const [params] = useSearchParams();
  const [jobId, setJobId] = useState<string | null>(() => {
    try {
      return params.get("export") ?? localStorage.getItem(EXPORT_KEY);
    } catch {
      return params.get("export");
    }
  });
  useEffect(() => {
    try {
      if (jobId) localStorage.setItem(EXPORT_KEY, jobId);
    } catch {
      /* не запомнится */
    }
  }, [jobId]);
  const job = useJob(jobId);
  const [error, setError] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: (all: boolean) => post<{ job_id: string }>(`/api/reports/exports${all ? "" : `?building_id=${building.id}`}`),
    onSuccess: (r, all) => {
      setJobId(r.job_id);
      watchJob({ id: r.job_id, title: `Полная выгрузка: ${all ? "все здания" : building.name}`, href: `/reports?export=${r.job_id}` });
    },
    onError: (e) => setError((e as ApiError).message),
  });
  const running = job && (job.status === "queued" || job.status === "running");
  return (
    <Card className="flex flex-col gap-2 p-4" aria-label="Полная выгрузка">
      <h2 className="m-0 flex items-center gap-2 text-sm font-semibold">
        <Archive className="size-4" /> Полная выгрузка
      </h2>
      <p className="m-0 text-[13px] text-ink-2">
        Архив: таблицы Excel (помещения, расстановка, имущество, остатки, документы, история) и все файлы — чертежи, подложки, фото и документы, 3D-модели. Его можно хранить отдельно и
        прочитать без системы. В системе архив хранится срок из «Настроек» и в резервные копии не входит — скачайте его и сохраните отдельно.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={!!running || start.isPending} onClick={() => start.mutate(false)}>
          Здание «{building.name}»
        </Button>
        <Button disabled={!!running || start.isPending} onClick={() => start.mutate(true)}>
          Все здания
        </Button>
      </div>
      {job && running && (
        <p className="m-0 text-[13px] text-ink-2" role="status">
          {job.message ?? "Собираю…"} {job.progress.total ? `(${job.progress.done} из ${job.progress.total})` : ""} — можно уйти с экрана, по окончании придёт сообщение.
        </p>
      )}
      {running && <CancelJob job={job} />}
      {job?.status === "done" && <ArchiveLink key={job.id} job={job} />}
      {job?.status === "failed" && <FormError message={job.error ?? "Выгрузка не удалась."} />}
      {job?.status === "cancelled" && <p className="m-0 text-[13px] text-ink-2">Выгрузка отменена.</p>}
      <FormError message={error} />
    </Card>
  );
}
