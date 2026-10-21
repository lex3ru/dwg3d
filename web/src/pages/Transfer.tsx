import { useQueryClient } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { ApiError, post } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useJob, watchJob } from "@/lib/jobs";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";

// Перенос здания на другую установку: пакет выгружается в карточке здания («Выгрузить для
// переноса»), здесь — загружается: сначала проверка (что заведётся в каталоге, какие номера
// заняты), затем загрузка фоновой задачей.

interface Check {
  upload_id: string;
  exported_at: string | null;
  exported_by: string | null;
  building: { name: string; address: string; suggested: string; exists: boolean };
  floors: number;
  rooms: number;
  items: number;
  units: number;
  stock: number;
  warehouses: number;
  files: number;
  taken_numbers: string[];
  catalog: { layers: string[]; sets: string[]; types: string[]; models: string[]; purposes: string[]; characteristics: string[] };
}

const n = (v: number) => v.toLocaleString("ru-RU");

export function TransferImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [check, setCheck] = useState<Check | null>(null);
  const [name, setName] = useState("");
  const [renumber, setRenumber] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  useEffect(() => {
    if (!open) {
      setCheck(null);
      setError(null);
      setJobId(null);
      setRenumber(false);
    }
  }, [open]);
  useEffect(() => {
    if (job?.status !== "done") return;
    void client.invalidateQueries({ queryKey: ["buildings"] });
    const id = job.result?.building_id as string | undefined;
    if (id) {
      onClose();
      navigate(`/buildings?b=${id}`);
    }
  }, [job, client, navigate, onClose]);

  const send = async (file: File) => {
    setBusy(true);
    setError(null);
    setCheck(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await fetch("/api/transfer/check", { method: "POST", body: form, headers: { "X-Requested-With": "app" }, credentials: "same-origin" });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.error?.message ?? "Пакет не проверен.");
      setCheck(body as Check);
      setName((body as Check).building.suggested);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const start = async () => {
    if (!check) return;
    setError(null);
    try {
      const r = await post<{ job_id: string }>("/api/transfer/import", { upload_id: check.upload_id, name, renumber });
      setJobId(r.job_id);
      watchJob({ id: r.job_id, title: `Загрузка здания «${name}»`, href: "/buildings" });
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  const running = !!job && (job.status === "queued" || job.status === "running");
  const taken = check?.taken_numbers ?? [];
  const added = check ? Object.entries(check.catalog).filter(([, v]) => v.length) : [];
  const TITLES: Record<string, string> = { layers: "слои", sets: "наборы характеристик", types: "типы", models: "модели", purposes: "назначения помещений", characteristics: "характеристики у найденных типов" };
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && !running && onClose()}
      title="Загрузить здание из файла"
      description="Пакет, выгруженный на другой установке кнопкой «Выгрузить для переноса»: этажи с планами, мебель и оборудование, учёт имущества."
      wide
      footer={
        <>
          <Button onClick={onClose} disabled={running}>
            Отмена
          </Button>
          {check && (
            <Button variant="primary" disabled={running || !name.trim() || (taken.length > 0 && !renumber)} onClick={() => void start()}>
              <FileUp /> {running ? "Загружаю…" : "Загрузить"}
            </Button>
          )}
        </>
      }
    >
      {!check && (
        <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">
          Файл пакета (.zip)
          <input type="file" accept=".zip,application/zip" aria-label="Файл пакета" disabled={busy} onChange={(e) => e.target.files?.[0] && void send(e.target.files[0])} />
          {busy && <span>Проверяю пакет…</span>}
        </label>
      )}
      {check && (
        <div className="flex flex-col gap-3 text-[13px]" aria-label="Проверка пакета">
          <p className="m-0 text-ink-2">
            Здание «{check.building.name}»{check.exported_at ? `, выгружено ${formatDateTime(check.exported_at)}` : ""}
            {check.exported_by ? ` (${check.exported_by})` : ""}.
          </p>
          <ul className="m-0 grid list-none grid-cols-2 gap-x-6 gap-y-1 p-0 sm:grid-cols-3">
            <li>Этажей: {n(check.floors)}</li>
            <li>Помещений: {n(check.rooms)}</li>
            <li>Предметов: {n(check.items)}</li>
            <li>Инвентарных единиц: {n(check.units)}</li>
            <li>Позиций остатков: {n(check.stock)}</li>
            <li>Складов: {n(check.warehouses)}</li>
            <li>Файлов: {n(check.files)}</li>
          </ul>
          <div>
            <span className="font-medium">Каталог: </span>
            {added.length === 0 ? (
              <span className="text-ink-2">всё нашлось на этой установке, ничего не заводится.</span>
            ) : (
              <span className="text-ink-2">чего нет на этой установке — заведётся из пакета (существующее не меняется):</span>
            )}
            {added.map(([k, v]) => (
              <div key={k} className="text-ink-2">
                {TITLES[k] ?? k} ({v.length}): <span className="text-ink">{v.slice(0, 12).join(", ")}{v.length > 12 ? "…" : ""}</span>
              </div>
            ))}
          </div>
          {taken.length > 0 && (
            <div className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-warn" role="alert">
              Инвентарные номера уже заняты на этой установке: {n(taken.length)} ({taken.slice(0, 8).join(", ")}
              {taken.length > 8 ? "…" : ""}).
              <label className="mt-1.5 flex items-center gap-2 text-ink">
                <input type="checkbox" checked={renumber} onChange={(e) => setRenumber(e.target.checked)} /> Выдать этим единицам новые номера (по шаблону этой установки)
              </label>
            </div>
          )}
          <Field label="Название здания" hint={check.building.exists ? "Здание с таким названием здесь уже есть — предложено другое." : undefined}>
            {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
          </Field>
          <p className="m-0 text-[12px] text-ink-3">
            Учёт ставится одним «Вводом остатков» в текущем состоянии; история документов не переносится. Коды QR-меток сохраняются, если здесь они свободны.
          </p>
          {running && (
            <p className="m-0 text-ink-2" role="status">
              {job?.message ?? "Загружаю…"} {job?.progress.total ? `(${job.progress.done} из ${job.progress.total})` : ""}
            </p>
          )}
          {job?.status === "failed" && <FormError message={job.error ?? "Загрузка не удалась — ничего не заведено."} />}
        </div>
      )}
      <FormError message={error} />
    </Dialog>
  );
}
