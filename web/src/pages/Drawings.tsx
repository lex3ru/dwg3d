import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ApiError, get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { CancelJob, finished, useJob, watchJob } from "@/lib/jobs";
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
  // что это за часть листа — по подписи, штампу и форме (R-061); "" — не понять
  kind?: string;
}

// части листа, которые не этажи: по умолчанию «не переводить»
const KIND: Record<string, string> = {
  roof: "кровля",
  frame: "рамка листа",
  stamp: "штамп",
  table: "таблица",
  facade: "фасад",
  section: "разрез",
  detail: "узел",
  scheme: "схема",
  site: "генплан",
};

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

// что нашёл разбор о масштабе листа (ADR-0025)
interface SheetInfo {
  scale?: number;
  by?: "units" | "dimensions" | "admin";
  largest?: number;
  small?: boolean;
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
  scale: number | null;
  sheet: SheetInfo;
}

const SCALES = [1, 50, 100, 200, 250, 500, 1000];
const SCALE_BY: Record<NonNullable<SheetInfo["by"]>, string> = {
  units: "как начерчен",
  dimensions: "по размерам чертежа",
  admin: "задан вручную",
};

const metres = (mm: number) => (mm / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 });

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
    if (finished(job)) {
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
      client.invalidateQueries({ queryKey: ["drawings", buildingId] });
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
        <CancelJob job={job} />
      </div>
    );
  }
  const rescaled = () => {
    // части после разбора — другие: выбор этажей заново
    setChoice({});
    setNames({});
  };
  if (d.status === "failed")
    return (
      <div className="flex flex-col gap-3 border-t border-line px-3 py-3">
        <div className="text-sm text-bad">{d.error}</div>
        <SheetScale key={String(d.scale)} drawing={d} buildingId={buildingId} onChange={rescaled} />
      </div>
    );
  const existing = parts.filter((p) => choice[p.key] && choice[p.key] !== "new" && floors.find((f) => f.id === choice[p.key])?.walls);
  return (
    <div className="flex flex-col gap-3 border-t border-line px-3 py-3">
      <SheetScale key={String(d.scale)} drawing={d} buildingId={buildingId} onChange={rescaled} />
      {d.error && (
        <p className="m-0 rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad" role="alert">
          Перевод не выполнен: {d.error} Планы этажей не изменились — перевод можно повторить.
        </p>
      )}
      <p className="m-0 text-[13px] text-ink-2">На листе найдено частей: {parts.length}. Укажите, какая часть — какой этаж. Этажами предложены планы; рамки, штампы, таблицы, фасады и разрезы переводить не нужно.</p>
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
                {p.kind && KIND[p.kind] && <span className="font-normal text-ink-2"> — {KIND[p.kind]}, не этаж</span>}
              </div>
              <div className="text-[12px] text-ink-2">
                {metres(p.width)} × {metres(p.height)} м
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

// Масштаб листа: как он определён, предупреждение, если на листе нет части размером с этаж, и
// выбор масштаба — чертёж разбирается заново (5.1.3 п. 1, R-057, ADR-0025)
function SheetScale({ drawing, buildingId, onChange }: { drawing: DrawingInfo; buildingId: string; onChange: () => void }) {
  const client = useQueryClient();
  const current = drawing.scale === null ? "" : String(drawing.scale);
  const [value, setValue] = useState(current);
  const [error, setError] = useState<string | null>(null);
  const apply = useMutation({
    mutationFn: () => post<DrawingInfo>(`/api/drawings/${drawing.id}/scale`, { scale: value ? Number(value) : null }),
    onSuccess: (r) => {
      onChange();
      if (r.job_id) watchJob({ id: r.job_id, title: `Разбор чертежа «${r.name}»`, href: `/buildings?b=${buildingId}` });
      client.invalidateQueries({ queryKey: ["drawing", drawing.id] });
      client.invalidateQueries({ queryKey: ["drawings", buildingId] });
    },
    onError: (e) => setError((e as ApiError).message),
  });
  const sheet = drawing.sheet ?? {};
  const options = drawing.scale === null || SCALES.includes(drawing.scale) ? SCALES : [...SCALES, drawing.scale].sort((a, b) => a - b);
  const converted = Object.keys(drawing.results).length > 0;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        {sheet.scale !== undefined && sheet.by && (
          <span className="text-ink-2">
            Масштаб листа 1:{sheet.scale.toLocaleString("ru-RU")} — {SCALE_BY[sheet.by]}.
          </span>
        )}
        <select
          aria-label="Масштаб листа"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="h-8 rounded-md border border-line-strong bg-surface px-1.5 text-[13px] text-ink max-md:h-11"
        >
          <option value="">масштаб — по чертежу</option>
          {options.map((s) => (
            <option key={s} value={String(s)}>
              масштаб 1:{s}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          onClick={() => {
            setError(null);
            apply.mutate();
          }}
          disabled={value === current || apply.isPending}
        >
          Разобрать заново
        </Button>
      </div>
      {sheet.small && (
        <p className="m-0 rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn" role="alert">
          На листе нет ни одной части размером с этаж (наибольшая — {metres(sheet.largest ?? 0)} м): похоже, чертёж начерчен в масштабе листа. Выберите масштаб и разберите чертёж заново.
        </p>
      )}
      {converted && value !== current && <p className="m-0 text-[12px] text-ink-2">Итоги перевода частей сбросятся; переведённые этажи останутся как есть.</p>}
      <FormError message={error} />
    </div>
  );
}
