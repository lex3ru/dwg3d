import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, RefreshCw } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { ApiError, get, patch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatBytes, formatDateTime } from "@/lib/format";
import { labelWarning } from "@/inventory/parts";
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
  { key: "inventory", title: "Учёт имущества" },
  { key: "calc", title: "Расчёты" },
  { key: "uploads", title: "Загрузка файлов" },
  { key: "status", title: "Состояние сервера" },
];

export function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab");
  const tab = TABS.some((t) => t.key === asked) ? asked! : "general";
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
      {tab === "general" ? <General /> : tab === "inventory" ? <KeyedSettings key="inventory" keys={INVENTORY_KEYS}><LabelAddress /></KeyedSettings> : tab === "calc" ? <KeyedSettings key="calc" keys={CALC_KEYS} /> : tab === "uploads" ? <KeyedSettings key="uploads" keys={UPLOAD_KEYS} /> : <ServerStatus />}
    </PageBody>
  );
}

function General() {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => get<Settings>("/api/system/settings") });
  const [org, setOrg] = useState("");
  const [years, setYears] = useState("5");
  const [exportDays, setExportDays] = useState("30");
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (!settings.data) return;
    const value = (key: string) => settings.data.items.find((i) => i.key === key)?.value;
    setOrg(String(value("organization_name") ?? ""));
    setYears(String(value("journal_years") ?? 5));
    setExportDays(String(value("export_days") ?? 30));
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () =>
      patch<Settings>("/api/system/settings", {
        version: settings.data!.version,
        values: { organization_name: org, journal_years: Number.parseInt(years, 10), export_days: Number.parseInt(exportDays, 10) },
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
        {/* R-027: архив — почти все файлы системы ещё раз; его скачивают и хранят отдельно (7.4) */}
        <Field label="Срок хранения архивов полной выгрузки, дней" hint="Архивы старше удаляются автоматически раз в час. В резервные копии они не входят — скачанный архив храните отдельно." error={error?.field === "export_days" ? error.message : undefined}>
          {(p) => <Input {...p} type="number" min={1} max={365} value={exportDays} onChange={(e) => setExportDays(e.target.value)} className="w-32" />}
        </Field>
        <p className="m-0 text-[13px] text-ink-2">Вид инвентарного номера и наклейки — на вкладке «Учёт имущества»; пороги камер и освещённость появятся на этапе 7.</p>
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

// 4.6 п. 2, 5.4.7: вид номера, адрес и вид наклеек
const INVENTORY_KEYS: [string, string, string][] = [
  ["inventory_number_template", "Вид инвентарного номера", "Цифры нулями в конце: 000000 → 000154; ИН-0000 → ИН-0154. Номера выдаются подряд и после списания не повторяются."],
  ["label_url", "Адрес системы для QR-меток", "Постоянный адрес, который открывается с телефонов, например https://uchet.local. Пусто — адрес установки."],
  ["label_width_mm", "Наклейка: ширина, мм", ""],
  ["label_height_mm", "Наклейка: высота, мм", "40×25 или 58×40 мм — под принтер этикеток; на нём печатается по одной наклейке на страницу."],
  ["label_sheet_cols", "Лист А4: наклеек в ряду", ""],
  ["label_sheet_rows", "Лист А4: рядов", ""],
  ["label_sheet_top_mm", "Лист А4: поле сверху, мм", ""],
  ["label_sheet_left_mm", "Лист А4: поле слева, мм", ""],
  ["label_sheet_gap_mm", "Лист А4: промежуток между наклейками, мм", "Раскладка — под марку листа с готовыми наклейками."],
];

// Куда сейчас ведут QR-метки (5.4.7, R-016): адрес с телефона должен открываться
const SOURCE: Record<string, string> = {
  settings: "задан выше",
  install: "адрес установки, PUBLIC_URL",
  request: "адрес, по которому открыта система",
};

function LabelAddress() {
  const address = useQuery({ queryKey: ["label-address"], queryFn: () => get<{ url: string; source: string }>("/api/inventory/labels/address") });
  if (!address.data) return null;
  const { url, source } = address.data;
  const local = /^https?:\/\/(localhost|127\.|\[::1\])/i.test(url);
  const warnings = [
    source === "request" && "Адрес установки не задан: ссылка в метке зависит от того, по какому адресу открыли систему. Укажите постоянный адрес.",
    local && "С телефона такой адрес не откроется: укажите имя или IP-адрес сервера в сети учреждения.",
    labelWarning(url),
  ].filter(Boolean) as string[];
  return (
    <div className="flex flex-col gap-1.5 text-[13px]">
      <div className="text-ink-2">
        Сейчас метки ведут на <span className="font-mono text-ink">{url}</span> ({SOURCE[source]}).
      </div>
      {warnings.map((w) => (
        <div key={w} role="alert" className="rounded-lg bg-warn-soft px-3 py-2 text-warn">
          {w}
        </div>
      ))}
    </div>
  );
}

// 7.3 п. 4: наибольший размер загружаемого файла по видам; больший сервер не принимает
const UPLOAD_KEYS: [string, string, string][] = [
  ["drawing_max_mb", "Чертёж DWG/DXF — до, МБ", "До 300 МБ."],
  ["underlay_max_mb", "Подложка этажа — до, МБ", "PDF или картинка; до 300 МБ."],
  ["excel_max_mb", "Excel — до, МБ", "Имущество и каталог; до 50 МБ."],
  ["model3d_max_mb", "3D-модель GLB — до, МБ", "До 100 МБ."],
  ["photo_max_mb", "Фото — до, МБ", "Карточка единицы и снимок при обходе; до 100 МБ."],
  ["document_max_mb", "Документ — до, МБ", "Скан к единице или документу учёта; до 200 МБ."],
  ["transfer_max_mb", "Пакет переноса здания — до, МБ", "Несёт все файлы здания; до 10 240 МБ."],
];

// 4.6 п. 3, 4; 5.3.4, 5.3.5: пороги камер и параметры расчёта освещённости
const CALC_KEYS: [string, string, string][] = [
  ["calc_face_height_mm", "Камеры: высота лица, мм", "На этой высоте рисуется зона обзора (5.3.4)."],
  ["calc_camera_range_m", "Камеры: предельная дальность, м", ""],
  ["calc_px_detect", "Обнаружение, пк/м", "Плотность изображения по ГОСТ Р 51558 / IEC 62676-4."],
  ["calc_px_observe", "Наблюдение действий, пк/м", ""],
  ["calc_px_recognize", "Узнавание, пк/м", ""],
  ["calc_px_identify", "Идентификация, пк/м", "Установление личности."],
  ["calc_light_maintenance", "Освещённость: коэффициент запаса", "Делит расчётную освещённость: старение и загрязнение светильников."],
  ["calc_light_reflection", "Освещённость: прибавка за отражения, доля", "0,2 — к прямому свету прибавляется 20 % за отражения от стен и потолка."],
  ["calc_light_step_mm", "Освещённость: шаг сетки, мм", "Чем меньше, тем подробнее раскраска и дольше расчёт."],
];

// строкой, остальные — числа
const TEXT_KEYS = new Set(["inventory_number_template", "label_url"]);

function KeyedSettings({ keys, children }: { keys: [string, string, string][]; children?: ReactNode }) {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => get<Settings>("/api/system/settings") });
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (!settings.data) return;
    setValues(Object.fromEntries(keys.map(([k]) => [k, String(settings.data.items.find((i) => i.key === k)?.value ?? "")])));
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () =>
      patch<Settings>("/api/system/settings", {
        version: settings.data!.version,
        values: Object.fromEntries(keys.map(([k]) => [k, TEXT_KEYS.has(k) ? values[k] : Number(String(values[k]).replace(",", "."))])),
      }),
    onSuccess: (data) => {
      client.setQueryData(["settings"], data);
      client.invalidateQueries({ queryKey: ["label-address"] });
      setSaved(true);
    },
    onError: (e) => setError(e as ApiError),
  });
  if (settings.isLoading) return <Loading />;
  return (
    <Card className="max-w-2xl p-6 max-md:p-4">
      <form
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          setSaved(false);
          save.mutate();
        }}
      >
        {keys.map(([k, title, hint]) => (
          <Field key={k} label={title} hint={hint || undefined} error={error?.field === k ? error.message : undefined}>
            {(p) => <Input {...p} value={values[k] ?? ""} onChange={(e) => setValues({ ...values, [k]: e.target.value })} className={TEXT_KEYS.has(k) ? "font-mono" : "w-32"} />}
          </Field>
        ))}
        {children && <div className="sm:col-span-2">{children}</div>}
        <div className="sm:col-span-2">
          <FormError message={error && !error.field ? error.message : null} />
        </div>
        <div className="flex items-center gap-3 sm:col-span-2">
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Сохранить
          </Button>
          {saved && <span className="text-sm text-ok">Сохранено</span>}
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
