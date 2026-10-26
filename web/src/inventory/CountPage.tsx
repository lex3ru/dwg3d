import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, FileDown, LogIn, PackagePlus, ScanLine, ServerCrash, Trash2, WifiOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router";
import type { TypeBrief } from "@/catalog/types";
import { ApiError, api, get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useCardTitle } from "@/shell/context";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";
import { Card, Chip, Empty, Loading, PageHeader } from "@/ui/misc";
import { STATUS } from "./DocumentsPage";
import { TypePicker, useInvalidateInventory } from "./parts";
import { drainQueue, type Job, loadQueue, pushQueue, type Wait } from "./queue";
import { QrCamera } from "./scanner";
import { dateRu, STATES, type State } from "./types";

interface Row {
  unit_id: string;
  number: string;
  title: string;
  state: State;
  status: "here" | "elsewhere" | "foreign" | "missing";
  manual: boolean;
  found_place: string;
  home_place: string;
}

interface CountView {
  id: string;
  title: string;
  status: "draft" | "posted" | "cancelled";
  date: string;
  version: number;
  places: { key: string; title: string; short: string; expected: number; found: number; foreign: number; extras: number }[];
  summary: { expected: number; found_in_place: number; found_elsewhere: number; missing: number; extras: number; stock_diff: number };
  place?: {
    key: string;
    title: string;
    items: Row[];
    foreign: Row[];
    extras: { id: string; title: string; serial: string; note: string }[];
    // позиция остатка — место, тип и модель, как он хранится (ADR-0005)
    stock: { type_id: string; model_id: string | null; title: string; unit: string; expected: number; counted: number | null }[];
  };
}

interface ScanResult {
  result: "here" | "again" | "elsewhere" | "unknown" | "room" | "other_room";
  text: string;
  place?: string;
}

// почему отметки ждут отправки — и что будет дальше (6.7 п. 1, R-030)
const WAIT: Record<Wait, { icon: typeof WifiOff; what: string; next: string }> = {
  offline: { icon: WifiOff, what: "Нет связи", next: "Досылаются сами, когда связь вернётся." },
  server: { icon: ServerCrash, what: "Сервер не принимает отметки", next: "Досылаются сами, когда он ответит." },
  session: { icon: LogIn, what: "Нужно войти снова", next: "После входа под учётной записью администратора они досылаются сами." },
};

const stockKey = (place: string, type: string, model: string | null) => `${place}|${type}|${model ?? ""}`;

const TONE: Record<ScanResult["result"], string> = {
  here: "bg-ok-soft text-ok border-ok/40",
  again: "bg-ok-soft text-ok border-ok/40",
  elsewhere: "bg-warn-soft text-warn border-warn/40",
  room: "bg-accent-soft text-accent-ink border-accent/40",
  other_room: "bg-warn-soft text-warn border-warn/40",
  unknown: "bg-bad-soft text-bad border-bad/40",
};

// звук отметки: найдено — высокий, не здесь — средний, неизвестна — низкий
function beep(result: ScanResult["result"]) {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = result === "unknown" ? 220 : result === "elsewhere" || result === "other_room" ? 520 : 880;
    gain.gain.value = 0.15;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.15);
    navigator.vibrate?.(result === "unknown" ? [80, 60, 80] : 80);
  } catch {
    /* без звука */
  }
}

// Обход инвентаризации (6.5.8): место — из списка или по метке на двери; метки — подряд
export function CountPage() {
  const { countId } = useParams();
  const client = useQueryClient();
  const refreshInventory = useInvalidateInventory();
  const [place, setPlace] = useState<string | null>(null);
  const view = useQuery({
    queryKey: ["inventory", "count", countId, place],
    queryFn: () => get<CountView>(`/api/inventory/counts/${countId}${place ? `?place=${encodeURIComponent(place)}` : ""}`),
  });
  const c = view.data;
  useCardTitle(c?.title ?? null);
  useEffect(() => {
    if (c && !place && c.places.length) setPlace(c.places[0]!.key);
  }, [c, place]);
  const [last, setLast] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [manual, setManual] = useState("");
  const [adding, setAdding] = useState(false);
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // очередь отметок с досылкой: метки, ручные отметки и пересчёт остатков (R-030)
  const storeKey = `count-queue:${countId}`;
  const [queue, setQueue] = useState<Job[]>(() => loadQueue(storeKey));
  const [wait, setWait] = useState<Wait | null>(null);
  const refresh = useCallback(() => client.invalidateQueries({ queryKey: ["inventory", "count", countId] }), [client, countId]);
  const drain = useCallback(async () => {
    const send = async (job: Job) => {
      if (job.kind === "scan") {
        const r = await post<ScanResult>(`/api/inventory/counts/${countId}/scan`, { code: job.code, place: job.place });
        setLast(r);
        beep(r.result);
        if (r.result === "room" && r.place) setPlace(r.place);
      } else if (job.kind === "mark") await post(`/api/inventory/counts/${countId}/marks`, { unit_id: job.unit_id, place: job.place });
      else if (job.kind === "unmark") await api("DELETE", `/api/inventory/counts/${countId}/marks/${job.unit_id}`);
      else await api("PUT", `/api/inventory/counts/${countId}/stock`, { place: job.place, type_id: job.type_id, model_id: job.model_id, counted: job.counted });
    };
    const ran = await drainQueue(storeKey, send, { changed: setQueue, waiting: setWait, dropped: setError });
    if (ran) void refresh();
  }, [countId, refresh, storeKey]);
  const push = (job: Job) => {
    setQueue(pushQueue(storeKey, job));
    void drain();
  };
  useEffect(() => {
    void drain();
    const t = setInterval(() => void drain(), 4000);
    return () => clearInterval(t);
  }, [drain]);

  if (view.isLoading && !c) return <Loading />;
  if (!c) return <Empty title="Ведомость не найдена" />;
  const draft = c.status === "draft";
  const here = c.places.find((p) => p.key === place);
  const scan = (text: string) => {
    if (!place) return;
    setError(null);
    push({ kind: "scan", code: text, place });
  };
  const pdf = (what: "statement" | "act") => window.open(`/api/inventory/counts/${c.id}/${what}.pdf`, "_blank");
  // пересчёт, который ещё в очереди, показываем как введённый — последнее значение позиции
  const pending = new Map(queue.flatMap((j) => (j.kind === "stock" ? [[stockKey(j.place, j.type_id, j.model_id), j.counted] as const] : [])));
  const waitNote = wait && queue.length > 0 ? WAIT[wait] : null;

  return (
    <PageBody>
      <PageHeader
        title={c.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Chip tone={STATUS[c.status][1]}>{draft ? "идёт обход" : STATUS[c.status][0]}</Chip>
            от {dateRu(c.date)}
          </span>
        }
        actions={
          <>
            <Button onClick={() => pdf("statement")}>
              <FileDown /> Ведомость
            </Button>
            {c.status === "posted" && (
              <Button onClick={() => pdf("act")}>
                <FileDown /> Акт расхождений
              </Button>
            )}
            {draft && (
              <Button variant="primary" onClick={() => setPosting(true)}>
                <CheckCheck /> Провести
              </Button>
            )}
          </>
        }
      />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" aria-label="Итоги обхода">
        {[
          ["Числится", c.summary.expected, ""],
          ["На своём месте", c.summary.found_in_place, "text-ok"],
          ["Найдено не там", c.summary.found_elsewhere, "text-warn"],
          ["Не найдено", c.summary.missing, "text-bad"],
          ["Не числилось", c.summary.extras, "text-accent-ink"],
        ].map(([t, v, tone]) => (
          <Card key={t as string} className="px-3 py-2">
            <div className="text-[11px] text-ink-2">{t}</div>
            <div className={cn("font-mono text-lg font-semibold", tone as string)}>{v}</div>
          </Card>
        ))}
      </div>
      {waitNote && (
        <div role="alert" className="flex items-center gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn">
          <waitNote.icon className="size-4 shrink-0" /> {waitNote.what} — отметок ждёт отправки: {queue.length}. {waitNote.next}
        </div>
      )}
      <label className="flex flex-col gap-1 text-[13px] text-ink-2">
        Место обхода
        <select aria-label="Место обхода" value={place ?? ""} onChange={(e) => setPlace(e.target.value)} className="h-11 rounded-lg border border-line-strong bg-surface px-2 text-sm text-ink">
          {c.places.map((p) => (
            <option key={p.key} value={p.key}>
              {p.title} — найдено {p.found} из {p.expected}
              {p.foreign ? `, чужих ${p.foreign}` : ""}
            </option>
          ))}
        </select>
      </label>
      {draft && (
        <Card className="flex flex-col gap-2 p-3">
          {scanning ? (
            <QrCamera continuous onCode={scan} />
          ) : (
            <Button variant="primary" className="h-12" onClick={() => setScanning(true)}>
              <ScanLine /> Сканировать метки
            </Button>
          )}
          {last && (
            <div role="status" aria-label="Последняя метка" className={cn("rounded-lg border px-3 py-2 text-sm font-medium", TONE[last.result])}>
              {last.result === "here" ? "Найдена: " : last.result === "again" ? "Уже отмечена: " : last.result === "elsewhere" ? "Не здесь: " : last.result === "room" ? "Помещение: " : ""}
              {last.text}
            </div>
          )}
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (manual.trim()) scan(manual.trim());
              setManual("");
            }}
          >
            <Input aria-label="Номер или код метки" placeholder="Инв. номер или код метки" value={manual} onChange={(e) => setManual(e.target.value)} className="flex-1" />
            <Button type="submit">Отметить</Button>
          </form>
        </Card>
      )}
      <FormError message={error} />
      {c.place && here && (
        <Card className="overflow-hidden">
          <h3 className="m-0 border-b border-line px-4 py-2.5 text-sm font-semibold">
            {c.place.title}: найдено {here.found} из {here.expected}
          </h3>
          <ul aria-label="Числится в месте" className="m-0 list-none p-0">
            {c.place.items.map((r) => (
              <RowItem key={r.unit_id} r={r} draft={draft} onToggle={(on) => push(on ? { kind: "mark", unit_id: r.unit_id, place: c.place!.key } : { kind: "unmark", unit_id: r.unit_id })} />
            ))}
            {!c.place.items.length && <li className="px-4 py-3 text-[13px] text-ink-3">Здесь ничего не числится.</li>}
          </ul>
          {c.place.foreign.length > 0 && (
            <>
              <h4 className="m-0 border-y border-line bg-warn-soft px-4 py-2 text-[13px] font-semibold text-warn">Найдено здесь, числится в другом месте — переместится при проведении</h4>
              <ul aria-label="Найдено здесь чужое" className="m-0 list-none p-0">
                {c.place.foreign.map((r) => (
                  <RowItem key={r.unit_id} r={r} draft={draft} onToggle={(on) => !on && push({ kind: "unmark", unit_id: r.unit_id })} />
                ))}
              </ul>
            </>
          )}
          <div className="flex flex-col gap-1 border-t border-line px-4 py-3">
            <div className="flex items-center justify-between">
              <span className="text-[13px] font-semibold">Не числилось</span>
              {draft && (
                <Button size="sm" onClick={() => setAdding(true)}>
                  <PackagePlus /> Завести вещь без метки
                </Button>
              )}
            </div>
            {c.place.extras.map((e) => (
              <div key={e.id} className="flex items-center gap-2 text-[13px]">
                <span className="flex-1">
                  {e.title}
                  <span className="text-ink-3">{[e.serial && `SN ${e.serial}`, e.note].filter(Boolean).map((x) => ` · ${x}`)}</span>
                </span>
                {draft && (
                  <Button size="icon" variant="ghost" aria-label={`Убрать «${e.title}»`} onClick={async () => { await api("DELETE", `/api/inventory/counts/${c.id}/extras/${e.id}`); void refresh(); }}>
                    <Trash2 />
                  </Button>
                )}
              </div>
            ))}
          </div>
          {c.place.stock.length > 0 && (
            <div className="flex flex-col gap-2 border-t border-line px-4 py-3">
              <span className="text-[13px] font-semibold">Остатки — пересчитать</span>
              {c.place.stock.map((s) => {
                const key = stockKey(c.place!.key, s.type_id, s.model_id);
                const counted = pending.has(key) ? pending.get(key)! : s.counted;
                return <StockRow key={key} s={{ ...s, counted }} disabled={!draft} onSave={(v) => push({ kind: "stock", place: c.place!.key, type_id: s.type_id, model_id: s.model_id, counted: v })} />;
              })}
            </div>
          )}
        </Card>
      )}
      {place && <ExtraDialog open={adding} onClose={() => setAdding(false)} countId={c.id} place={place} onDone={() => void refresh()} />}
      <PostDialog open={posting} onClose={() => setPosting(false)} count={c} unsent={queue.length} onDone={() => { void refresh(); refreshInventory(); }} />
    </PageBody>
  );
}

function RowItem({ r, draft, onToggle }: { r: Row; draft: boolean; onToggle: (on: boolean) => void }) {
  const tone = r.status === "here" ? "bg-ok-soft" : r.status === "elsewhere" || r.status === "foreign" ? "bg-warn-soft" : "";
  const found = r.status !== "missing";
  return (
    <li className={cn("flex min-h-12 items-center gap-3 border-b border-line px-4 py-2 last:border-b-0", tone)} data-status={r.status}>
      <input type="checkbox" className="size-5" aria-label={`Найдена: ${r.title} № ${r.number}`} checked={found} disabled={!draft || (r.status === "elsewhere" && !r.manual)} onChange={(e) => onToggle(e.target.checked)} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{r.title}</span>
        <span className="block text-[11px] text-ink-3">
          № {r.number}
          {r.state !== "in_use" && ` · ${STATES[r.state]}`}
          {r.status === "elsewhere" && ` · найдена: ${r.found_place}`}
          {r.status === "foreign" && ` · числится: ${r.home_place}`}
          {r.manual && " · отмечена вручную"}
        </span>
      </span>
    </li>
  );
}

function StockRow({ s, disabled, onSave }: { s: { title: string; unit: string; expected: number; counted: number | null }; disabled: boolean; onSave: (v: number | null) => void }) {
  const [text, setText] = useState(s.counted === null ? "" : String(s.counted));
  useEffect(() => setText(s.counted === null ? "" : String(s.counted)), [s.counted]);
  const commit = () => {
    const t = text.trim().replace(",", ".");
    const v = t === "" ? null : Number(t);
    if ((v === null || Number.isFinite(v)) && v !== s.counted) onSave(v);
  };
  return (
    <label className="flex items-center gap-2 text-[13px]">
      <span className="flex-1">
        {s.title} <span className="text-ink-3">· по учёту {s.expected.toLocaleString("ru-RU")} {s.unit}</span>
      </span>
      <input
        aria-label={`Фактически: ${s.title}`}
        inputMode="decimal"
        value={text}
        disabled={disabled}
        placeholder="факт"
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
        className={cn("h-10 w-24 rounded-md border border-line-strong bg-surface px-2 text-right font-mono", s.counted !== null && s.counted !== s.expected && "border-warn text-warn")}
      />
    </label>
  );
}

function ExtraDialog({ open, onClose, countId, place, onDone }: { open: boolean; onClose: () => void; countId: string; place: string; onDone: () => void }) {
  const [type, setType] = useState<TypeBrief | null>(null);
  const [serial, setSerial] = useState("");
  const [note, setNote] = useState("");
  const [photo, setPhoto] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setType(null);
      setSerial("");
      setNote("");
      setPhoto(null);
      setError(null);
    }
  }, [open]);
  const upload = async (f: File) => {
    const form = new FormData();
    form.append("file", f);
    const r = await fetch("/api/files?accept=jpeg,png,webp,heic", { method: "POST", body: form, headers: { "X-Requested-With": "app" }, credentials: "same-origin" });
    const body = await r.json();
    if (!r.ok) setError(body?.error?.message ?? "Фото не загрузилось.");
    else setPhoto(body.id);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Вещь без метки"
      description="Не числится — при проведении встанет на учёт с новым номером."
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button
            variant="primary"
            disabled={!type}
            onClick={async () => {
              try {
                await post(`/api/inventory/counts/${countId}/extras`, { place, type_id: type!.id, serial, note, photo_file_id: photo });
                onDone();
                onClose();
              } catch (e) {
                setError((e as ApiError).message);
              }
            }}
          >
            Завести
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <TypePicker value={type?.id} onChange={setType} filter={(t) => t.accounting === "piece"} />
        <Field label="Серийный номер">{(p) => <Input {...p} value={serial} onChange={(e) => setSerial(e.target.value)} />}</Field>
        <Field label="Примечание">{(p) => <Input {...p} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        <label className="flex items-center gap-2 text-[13px]">
          <span className="text-ink-2">Фото</span>
          <input type="file" accept="image/*" capture="environment" aria-label="Фото вещи" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
          {photo && <span className="text-ok">загружено</span>}
        </label>
        <FormError message={error} />
      </div>
    </Dialog>
  );
}

// unsent — отметки этого устройства, которых сервер ещё не получил: проведи сейчас — и
// неотправленное станет «не найдена», пересчёт не попадёт в документ (R-030)
function PostDialog({ open, onClose, count, unsent, onDone }: { open: boolean; onClose: () => void; count: CountView; unsent: number; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const s = count.summary;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Провести инвентаризацию?"
      description="Одним документом: найденное не там — перемещается, ненайденное — «не найдена» (для разбирательства или списания), не числившееся — ставится на учёт, остатки — по пересчёту. Проведённое правится только отменой."
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button
            variant="primary"
            disabled={busy || unsent > 0}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await post(`/api/inventory/counts/${count.id}/post`, { version: count.version });
                onDone();
                onClose();
              } catch (e) {
                setError((e as ApiError).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <CheckCheck /> Провести
          </Button>
        </>
      }
    >
      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[13px]">
        <li>Переместится (найдено не там): {s.found_elsewhere}</li>
        <li>Будет «не найдена»: {s.missing}</li>
        <li>Встанет на учёт (не числилось): {s.extras}</li>
        <li>Остатки с расхождением: {s.stock_diff}</li>
      </ul>
      {unsent > 0 && (
        <p role="alert" className="m-0 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[13px] text-warn">
          Ещё не отправлено отметок: {unsent}. Провести можно, когда они дойдут до сервера, — иначе неотправленное не попадёт в документ.
        </p>
      )}
      <FormError message={error} />
    </Dialog>
  );
}
