import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, RefreshCw } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { ApiError, get, patch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatBytes, formatDateTime } from "@/lib/format";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Field, FormError, Input } from "@/ui/form";
import { Card, Loading, PageHeader } from "@/ui/misc";

interface Settings {
  items: { key: string; title: string; value: unknown }[];
  version: number;
}

interface Status {
  ok: boolean;
  checks: { name: string; ok: boolean; detail: string }[];
  backup: { ok: boolean; at: string | null; message: string; size: number | null; kept: { daily?: number; monthly?: number } | null };
  disks: { path: string; total: number; used: number; free: number }[];
  checked_at: string;
}

const TABS = [
  { key: "general", title: "Общие" },
  { key: "status", title: "Состояние сервера" },
];

export function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "status" ? "status" : "general";
  return (
    <PageBody>
      <PageHeader title="Настройки" />
      <div role="tablist" className="flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={tab === t.key}
            onClick={() => setParams(t.key === "general" ? {} : { tab: t.key })}
            className={cn(
              "-mb-px h-10 cursor-pointer border-0 border-b-2 bg-transparent px-3 text-sm max-md:h-11",
              tab === t.key ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink",
            )}
          >
            {t.title}
          </button>
        ))}
      </div>
      {tab === "general" ? <General /> : <ServerStatus />}
    </PageBody>
  );
}

function General() {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => get<Settings>("/api/system/settings") });
  const [org, setOrg] = useState("");
  const [years, setYears] = useState("5");
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (!settings.data) return;
    const value = (key: string) => settings.data.items.find((i) => i.key === key)?.value;
    setOrg(String(value("organization_name") ?? ""));
    setYears(String(value("journal_years") ?? 5));
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () =>
      patch<Settings>("/api/system/settings", {
        version: settings.data!.version,
        values: { organization_name: org, journal_years: Number.parseInt(years, 10) },
      }),
    onSuccess: (data) => {
      client.setQueryData(["settings"], data);
      setSaved(true);
    },
    onError: (e) => setError(e as ApiError),
  });
  if (settings.isLoading) return <Loading />;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    save.mutate();
  };
  return (
    <Card className="max-w-2xl p-6 max-md:p-4">
      <form onSubmit={submit} className="flex flex-col gap-5">
        <Field label="Название учреждения" hint="Печатается в шапке документов, отчётов и на наклейках." error={error?.field === "organization_name" ? error.message : undefined}>
          {(p) => <Input {...p} value={org} onChange={(e) => setOrg(e.target.value)} placeholder="ГБУЗ «Городская поликлиника № 1»" />}
        </Field>
        <Field label="Срок хранения журнала, лет" hint="Записи старше удаляются автоматически раз в сутки." error={error?.field === "journal_years" ? error.message : undefined}>
          {(p) => <Input {...p} type="number" min={1} max={50} value={years} onChange={(e) => setYears(e.target.value)} className="w-32" />}
        </Field>
        <p className="m-0 text-[13px] text-ink-2">
          Вид инвентарного номера, размер наклеек, пороги различимости камер и параметры расчёта освещённости появятся здесь на этапах 5 и 7.
        </p>
        <FormError message={error && !error.field ? error.message : null} />
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Сохранить
          </Button>
          {saved && <span className="text-sm text-ok">Сохранено</span>}
          {error?.code === "stale" && <Button onClick={() => settings.refetch()}>Обновить</Button>}
        </div>
      </form>
    </Card>
  );
}

// 8.5 п. 4: работает ли всё, когда была последняя резервная копия, сколько места
function ServerStatus() {
  const status = useQuery({ queryKey: ["status"], queryFn: () => get<Status>("/api/system/status"), refetchInterval: 30_000 });
  if (status.isLoading || !status.data) return <Loading />;
  const s = status.data;
  return (
    <div className="flex flex-col gap-5">
      <div className={cn("flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3", s.ok ? "border-ok/30 bg-ok-soft text-ok" : "border-bad/30 bg-bad-soft text-bad")}>
        {s.ok ? <CircleCheck className="size-5" /> : <CircleAlert className="size-5" />}
        <span className="flex-1 font-medium">{s.ok ? "Всё работает" : "Есть неполадки — смотрите ниже"}</span>
        <span className="text-[13px]">проверено {formatDateTime(s.checked_at)}</span>
        <Button size="sm" onClick={() => status.refetch()} aria-label="Проверить снова">
          <RefreshCw /> Проверить
        </Button>
      </div>
      <Card className="overflow-hidden">
        <ul className="m-0 list-none p-0">
          {s.checks.map((c) => (
            <li key={c.name} className="flex items-start gap-3 border-b border-line px-4 py-3 last:border-b-0">
              {c.ok ? <CircleCheck className="mt-0.5 size-[18px] shrink-0 text-ok" /> : <CircleAlert className="mt-0.5 size-[18px] shrink-0 text-bad" />}
              <div className="flex flex-col">
                <span className="text-sm font-medium">{c.name}</span>
                <span className="text-[13px] text-ink-2">{c.detail}</span>
              </div>
            </li>
          ))}
        </ul>
      </Card>
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="flex flex-col gap-2 p-4">
          <h2 className="m-0 text-base font-semibold">Резервные копии</h2>
          <div className="text-sm">Последняя: {formatDateTime(s.backup.at)}</div>
          {s.backup.size != null && <div className="text-sm text-ink-2">Размер: {formatBytes(s.backup.size)}</div>}
          {s.backup.kept && (
            <div className="text-sm text-ink-2">
              Хранится ежедневных: {s.backup.kept.daily ?? 0}, ежемесячных: {s.backup.kept.monthly ?? 0}
            </div>
          )}
          <p className="m-0 text-[13px] text-ink-2">Копии делаются каждую ночь; ежедневные хранятся 30 дней, ежемесячные — 12 месяцев.</p>
        </Card>
        <Card className="flex flex-col gap-3 p-4">
          <h2 className="m-0 text-base font-semibold">Место на дисках</h2>
          {s.disks.map((d) => {
            const share = d.total ? d.used / d.total : 0;
            return (
              <div key={d.path} className="flex flex-col gap-1">
                <div className="flex justify-between text-sm">
                  <span className="font-mono text-[13px]">{d.path}</span>
                  <span className="text-ink-2">
                    свободно {formatBytes(d.free)} из {formatBytes(d.total)}
                  </span>
                </div>
                <div className="h-2 rounded bg-muted-soft">
                  <div className={cn("h-2 rounded", share > 0.9 ? "bg-bad" : "bg-accent")} style={{ width: `${Math.round(share * 100)}%` }} />
                </div>
              </div>
            );
          })}
        </Card>
      </div>
    </div>
  );
}
