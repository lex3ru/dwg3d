import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ApiError, get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { useJob, watchJob } from "@/lib/jobs";
import type { FloorInfo } from "@/editor/plan";
import { Button } from "@/ui/button";
import { FormError } from "@/ui/form";
import { Chip, type Tone } from "@/ui/misc";

// Загрузка чертежа и перевод его частей в планы этажей (5.1.3, С1)

interface PartInfo {
  key: string;
  name: string;
  level: number | null;
  width: number;
  height: number;
  preview: string;
  floor_like: boolean;
  roof?: boolean;
}

interface PartResult {
  floor_id: string;
  floor: string;
  walls: number;
  openings: number;
  rooms: number;
  labelled: number;
  issues: number;
  notes: string[];
}

interface DrawingInfo {
  id: string;
  name: string;
  status: "analyzing" | "ready" | "converting" | "done" | "failed";
  error: string | null;
  job_id: string | null;
  created_at: string;
  parts: PartInfo[] | number;
  results: Record<string, PartResult>;
}

const STATUS: Record<DrawingInfo["status"], [string, Tone]> = {
  analyzing: ["разбирается", "muted"],
  ready: ["выберите этажи", "accent"],
  converting: ["переводится", "warn"],
  done: ["переведён", "ok"],
  failed: ["не получилось", "bad"],
};

function floorName(part: PartInfo): string {
  if (part.level !== null && part.level !== undefined) return part.level < 0 ? "Подвал" : `${part.level} этаж`;
  if (/техн/i.test(part.name)) return "Технический этаж";
  if (/мансард/i.test(part.name)) return "Мансарда";
  if (/цокол/i.test(part.name)) return "Цокольный этаж";
  const name = part.name.replace(/^план\s+/i, "").trim();
  return name ? name[0]!.toUpperCase() + name.slice(1) : "";
}

export function DrawingsSection({ buildingId, buildingName, floors }: { buildingId: string; buildingName: string; floors: FloorInfo[] }) {
  const client = useQueryClient();
  const list = useQuery({ queryKey: ["drawings", buildingId], queryFn: () => get<{ items: DrawingInfo[] }>(`/api/buildings/${buildingId}/drawings`) });
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const items = list.data?.items ?? [];
  const current = open ?? items[0]?.id ?? null;

  const upload = async (f: File) => {
    setError(null);
    setUploading(true);
    const form = new FormData();
    form.append("file", f);
    try {
      const response = await fetch(`/api/buildings/${buildingId}/drawings`, { method: "POST", body: form, headers: { "X-Requested-With": "app" }, credentials: "same-origin" });
      const body = await response.json();
      if (!response.ok) throw new Error(body?.error?.message ?? "Чертёж не загрузился.");
      setOpen(body.id);
      if (body.job_id) watchJob({ id: body.job_id, title: `Разбор чертежа «${body.name}»`, href: `/buildings?b=${buildingId}` });
      client.invalidateQueries({ queryKey: ["drawings", buildingId] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="flex flex-col gap-3 border-t border-line p-4" aria-label="Чертежи">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="m-0 text-base font-semibold">Чертежи</h3>
        <input ref={file} type="file" accept=".dwg,.dxf" className="hidden" aria-label="Файл чертежа" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
        <Button size="sm" onClick={() => file.current?.click()} disabled={uploading}>
          <FileUp /> {uploading ? "Загружается…" : "Загрузить DWG или DXF"}
        </Button>
      </div>
      <FormError message={error} />
      {!items.length ? (
        <p className="m-0 text-[13px] text-ink-2">Чертежей нет. Загрузите DWG или DXF — система найдёт на листе планы этажей и переведёт их в планы: стены, проёмы, помещения с номерами из подписей.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {items.map((d) => (
            <li key={d.id} className="rounded-lg border border-line">
              <button type="button" onClick={() => setOpen(current === d.id ? "" : d.id)} className="flex w-full cursor-pointer items-center gap-3 border-0 bg-transparent px-3 py-2 text-left">
                <span className="flex-1 truncate text-sm font-medium text-ink">{d.name}</span>
                <span className="text-[12px] text-ink-2">{formatDateTime(d.created_at)}</span>
                <Chip tone={STATUS[d.status][1]}>{STATUS[d.status][0]}</Chip>
              </button>
              {current === d.id && <DrawingDetail id={d.id} buildingId={buildingId} buildingName={buildingName} floors={floors} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function DrawingDetail({ id, buildingId, buildingName, floors }: { id: string; buildingId: string; buildingName: string; floors: FloorInfo[] }) {
  const client = useQueryClient();
  const drawing = useQuery({ queryKey: ["drawing", id], queryFn: () => get<DrawingInfo>(`/api/drawings/${id}`) });
  const job = useJob(drawing.data?.status === "analyzing" || drawing.data?.status === "converting" ? drawing.data.job_id : null);
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const parts = Array.isArray(drawing.data?.parts) ? drawing.data.parts : [];

  // по окончании задачи — перечитать
  useEffect(() => {
    if (job && (job.status === "done" || job.status === "failed")) {
      client.invalidateQueries({ queryKey: ["drawing", id] });
      client.invalidateQueries({ queryKey: ["drawings", buildingId] });
      client.invalidateQueries({ queryKey: ["building", buildingId] });
    }
  }, [job, client, id, buildingId]);

  // предложение: часть-этаж — на этаж с тем же названием или новый; мелочь — не переводить
  useEffect(() => {
    if (!parts.length) return;
    setChoice((c) => {
      if (Object.keys(c).length) return c;
      const out: Record<string, string> = {};
      for (const p of parts) {
        const result = drawing.data?.results[p.key];
        const same = floors.find((f) => f.name.toLowerCase() === floorName(p).toLowerCase());
        out[p.key] = result ? result.floor_id : !p.floor_like ? "" : same ? same.id : "new";
      }
      return out;
    });
    // часть без подписи — «N этаж» по порядку среди частей-этажей
    const order = parts.filter((p) => p.floor_like);
    setNames((n) => (Object.keys(n).length ? n : Object.fromEntries(parts.map((p) => [p.key, floorName(p) || `${order.indexOf(p) + 1 || 1} этаж`]))));
  }, [parts, floors, drawing.data]);

  const convert = useMutation({
    mutationFn: () =>
      post<{ job_id: string }>(`/api/drawings/${id}/convert`, {
        parts: parts
          .filter((p) => choice[p.key])
          .map((p) => (choice[p.key] === "new" ? { key: p.key, new_floor: { name: names[p.key] } } : { key: p.key, floor_id: choice[p.key] })),
      }),
    onSuccess: (r) => {
      watchJob({ id: r.job_id, title: `Перевод чертежа в планы — ${buildingName}`, href: `/buildings?b=${buildingId}` });
      client.invalidateQueries({ queryKey: ["drawing", id] });
    },
    onError: (e) => setError((e as ApiError).message),
  });

  if (!drawing.data) return null;
  const d = drawing.data;
  if (d.status === "analyzing" || d.status === "converting") {
    const p = job?.progress;
    const share = p?.total ? p.done / p.total : 0;
    return (
      <div className="flex flex-col gap-2 border-t border-line px-3 py-3">
        <div className="text-[13px] text-ink-2">{job?.message ?? (d.status === "analyzing" ? "Разбор чертежа…" : "Перевод…")}</div>
        <div className="h-2 rounded bg-muted-soft" role="progressbar" aria-valuenow={Math.round(share * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-2 rounded bg-accent transition-all" style={{ width: `${Math.max(5, share * 100)}%` }} />
        </div>
        <p className="m-0 text-[12px] text-ink-3">Можно уйти с экрана — по окончании придёт сообщение.</p>
      </div>
    );
  }
  if (d.status === "failed") return <div className="border-t border-line px-3 py-3 text-sm text-bad">{d.error}</div>;
  const existing = parts.filter((p) => choice[p.key] && choice[p.key] !== "new" && floors.find((f) => f.id === choice[p.key])?.walls);
  return (
    <div className="flex flex-col gap-3 border-t border-line px-3 py-3">
      <p className="m-0 text-[13px] text-ink-2">На листе найдено частей: {parts.length}. Укажите, какая часть — какой этаж; таблицы, штампы и подписи переводить не нужно.</p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {parts.map((p, i) => {
          const result = d.results[p.key];
          return (
            <div key={p.key} className={cn("flex flex-col gap-2 rounded-lg border p-2", choice[p.key] ? "border-accent" : "border-line")}>
              <svg viewBox="-20 -20 1040 1040" className="aspect-square w-full rounded bg-surface-2" role="img" aria-label={`Часть ${i + 1}`}>
                <path d={p.preview} stroke="var(--ink)" strokeWidth={3} fill="none" vectorEffect="non-scaling-stroke" />
              </svg>
              <div className="text-[13px] font-medium">
                {p.name || `Часть ${i + 1}`}
                {p.roof && <span className="font-normal text-ink-2"> — кровля, не этаж</span>}
              </div>
              <div className="text-[12px] text-ink-2">
                {(p.width / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} × {(p.height / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} м
              </div>
              <label className="flex flex-col gap-1 text-[12px] text-ink-2">
                Этаж
                <select
                  aria-label={`Этаж для части ${p.name || i + 1}`}
                  value={choice[p.key] ?? ""}
                  onChange={(e) => setChoice({ ...choice, [p.key]: e.target.value })}
                  className="h-8 rounded-md border border-line-strong bg-surface px-1.5 text-[13px] text-ink max-md:h-11"
                >
                  <option value="">не переводить</option>
                  {[...floors].reverse().map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                  <option value="new">новый этаж…</option>
                </select>
              </label>
              {choice[p.key] === "new" && (
                <input
                  aria-label={`Название нового этажа для части ${p.name || i + 1}`}
                  value={names[p.key] ?? ""}
                  onChange={(e) => setNames({ ...names, [p.key]: e.target.value })}
                  className="h-8 rounded-md border border-line-strong bg-surface px-2 text-[13px] max-md:h-11"
                />
              )}
              {result && (
                <div className="flex flex-col gap-0.5 rounded bg-surface-2 p-2 text-[12px]">
                  <Link to={`/plan/${buildingId}/${result.floor_id}`} className="font-medium text-accent">
                    {result.floor} — открыть план
                  </Link>
                  <span className="text-ink-2">
                    стен {result.walls}, проёмов {result.openings}, помещений {result.rooms} (с номерами {result.labelled})
                  </span>
                  <span className={result.issues ? "text-warn" : "text-ok"}>{result.issues ? `замечаний проверки: ${result.issues}` : "без замечаний проверки"}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {existing.length > 0 && (
        <p className="m-0 rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">
          План этажей {existing.map((p) => floors.find((f) => f.id === choice[p.key])?.name).join(", ")} будет заменён переводом. Помещения, которые узнаются по номерам, останутся теми же, с их предметами и историей.
        </p>
      )}
      <FormError message={error} />
      <div>
        <Button variant="primary" onClick={() => convert.mutate()} disabled={convert.isPending || !Object.values(choice).some(Boolean)}>
          Перевести в планы
        </Button>
      </div>
    </div>
  );
}
