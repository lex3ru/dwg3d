import { useQuery } from "@tanstack/react-query";
import { Check, CircleX, Download, FileUp, TriangleAlert } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useTree } from "@/catalog/parts";
import { get } from "@/lib/api";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { FormError } from "@/ui/form";
import { Chip, type Tone } from "@/ui/misc";
import { PlacePicker, useInvalidateInventory } from "./parts";
import { money } from "./types";

type How = "exact" | "similar" | "none";

interface Report {
  building: { id: string; name: string };
  names: { name: string; layer: string; accounting: string; rows: number[]; how: How; type_id: string | null; candidates: { type_id: string; name: string; score: number }[] }[];
  // confirm — номер совпал, название нет: без явного выбора места не загрузится (R-002)
  rooms: { key: string; floor: string; room: string; room_name: string; rows: number[]; how: How; confirm: boolean; place: string | null; place_title: string | null }[];
  rows: number;
  // name / room — ошибка сопоставления, показывается у своей строки таблицы
  errors: { row: number; message: string; name?: string; room?: string }[];
  units: number;
  stock: number;
  total: number;
  ok: boolean;
  applied: boolean;
  document_id?: string;
  created_types?: string[];
}

// R-045: статус — цветом и значком; что требует внимания — сверху
const HOW: Record<How, { text: string; tone: Tone; icon: typeof Check; rank: number }> = {
  none: { text: "не найдено", tone: "bad", icon: CircleX, rank: 0 },
  similar: { text: "похоже — проверьте", tone: "warn", icon: TriangleAlert, rank: 1 },
  exact: { text: "точно", tone: "ok", icon: Check, rank: 2 },
};

const byAttention = <T extends { how: How }>(list: T[]) => [...list].sort((a, b) => HOW[a.how].rank - HOW[b.how].rank);

function Status({ how, text, rows }: { how: How; text?: string; rows: number }) {
  const { icon: Icon, tone } = HOW[how];
  return (
    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-ink-3">
      <span data-how={how}>
        <Chip tone={tone}>
          <Icon className="size-3.5" aria-hidden /> {text ?? HOW[how].text}
        </Chip>
      </span>
      строк: {rows}
    </div>
  );
}

function RowErrors({ errors }: { errors: Report["errors"] }) {
  return errors.map((e, i) => (
    <p key={i} className="m-0 mt-1 text-[12px] text-bad">
      {e.message}
    </p>
  ));
}

// 5.4.9, С10: шаблон → проверка с сопоставлением → загрузка документом «Ввод остатков»
export function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const refresh = useInvalidateInventory();
  const catalog = useTree();
  const buildings = useQuery({ queryKey: ["buildings"], queryFn: () => get<{ items: { id: string; name: string }[] }>("/api/buildings"), enabled: open });
  const input = useRef<HTMLInputElement>(null);
  const [building, setBuilding] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [rooms, setRooms] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (f: File, apply: boolean, t = types, r = rooms) => {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", f);
    form.append("building_id", building);
    form.append("mapping", JSON.stringify({ types: t, rooms: r }));
    form.append("apply", apply ? "true" : "false");
    try {
      const res = await fetch("/api/inventory/import", { method: "POST", body: form, headers: { "X-Requested-With": "app" }, credentials: "same-origin" });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? "Файл не проверен.");
      setReport(body as Report);
      if (body.applied) refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const reset = () => {
    setFile(null);
    setReport(null);
    setTypes({});
    setRooms({});
    setError(null);
  };
  const close = () => {
    reset();
    onClose();
  };
  const allTypes = (catalog.data?.types ?? []).filter((t) => !t.archived);
  const namesId = useId();
  const roomsId = useId();
  const rowErrors = report?.errors.filter((e) => !e.name && !e.room) ?? [];
  const attention = (list: { how: How }[]) => list.filter((x) => x.how !== "exact").length;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()} title="Загрузить имущество из Excel" wide>
      <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto pr-1">
        <p className="m-0 text-[13px] text-ink-2">
          Заполните шаблон: одна строка — одна вещь при поштучном учёте или позиция с количеством. Система сопоставит наименования с каталогом, кабинеты — с помещениями плана, покажет ошибки по строкам и загрузит всё одним документом «Ввод остатков» — или ничего.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" asChild>
            <a href="/api/inventory/import/template.xlsx" download>
              <Download /> Шаблон
            </a>
          </Button>
          <select aria-label="Здание" value={building} onChange={(e) => { setBuilding(e.target.value); setReport(null); }} className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm">
            <option value="">— здание —</option>
            {buildings.data?.items.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <input
            ref={input}
            type="file"
            accept=".xlsx"
            aria-label="Файл со списком имущества"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (!f) return;
              reset();
              setFile(f);
              void send(f, false, {}, {});
            }}
          />
          <Button size="sm" disabled={!building || busy} onClick={() => input.current?.click()}>
            <FileUp /> {file ? "Другой файл" : "Выбрать файл"}
          </Button>
          {file && <span className="truncate text-[13px] text-ink-2">{file.name}</span>}
        </div>
        {busy && <p className="m-0 text-[13px] text-ink-2">Проверяю…</p>}
        <FormError message={error} />
        {report && !busy && (
          <>
            {report.applied ? (
              <div className="flex flex-wrap items-center gap-3 rounded-lg bg-ok-soft px-3 py-2 text-[13px] text-ok">
                Загружено: единиц — {report.units}, позиций остатков — {report.stock}, на {money(report.total)}.
                {report.created_types?.length ? ` Новые типы: ${report.created_types.join(", ")}.` : ""}
                <Button size="sm" onClick={() => { close(); navigate(`/documents/${report.document_id}`); }}>
                  Открыть документ
                </Button>
              </div>
            ) : report.ok ? (
              <p className="m-0 rounded-lg bg-accent-soft px-3 py-2 text-[13px]">
                Ошибок нет. Будет заведено единиц: {report.units}, позиций остатков: {report.stock}, на {money(report.total)}.
              </p>
            ) : (
              <p className="m-0 rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad">
                Есть что исправить ({report.errors.length}) — пока не исправлено, не загрузится ничего.
                {rowErrors.length < report.errors.length && " Ошибки сопоставления — в таблицах ниже, у своих строк."}
              </p>
            )}
            {/* shrink-0: со своей прокруткой список иначе сжимается до нуля, когда таблицы не помещаются (R-047) */}
            {rowErrors.length > 0 && (
              <ul aria-label="Ошибки по строкам файла" className="m-0 max-h-40 shrink-0 list-none overflow-y-auto p-0 text-[13px]">
                {rowErrors.map((e, i) => (
                  <li key={i} className="border-b border-line py-1">
                    <span className="text-ink-2">Строка {e.row}:</span> {e.message}
                  </li>
                ))}
              </ul>
            )}
            {!report.applied && (
              <>
                <section aria-labelledby={namesId} className="flex flex-col gap-1.5">
                  <h3 id={namesId} className="m-0 text-sm font-semibold">
                    Наименования → типы каталога
                    {attention(report.names) > 0 && <span className="font-normal text-ink-2"> · проверьте: {attention(report.names)}</span>}
                  </h3>
                  <table className="w-full border-collapse text-[13px]">
                    <tbody>
                      {byAttention(report.names).map((n) => (
                        <tr key={n.name} className="border-b border-line">
                          <td className="py-1.5 pr-2">
                            {n.name}
                            <Status how={n.how} rows={n.rows.length} />
                            <RowErrors errors={report.errors.filter((e) => e.name === n.name)} />
                          </td>
                          <td className="w-1/2 py-1.5">
                            <select
                              aria-label={`Тип для «${n.name}»`}
                              value={types[n.name] ?? n.type_id ?? ""}
                              onChange={(e) => setTypes({ ...types, [n.name]: e.target.value })}
                              className="h-8 w-full rounded-md border border-line-strong bg-surface px-2 text-[13px]"
                            >
                              <option value="">— выберите —</option>
                              <option value="new">+ создать тип «{n.name}»</option>
                              {n.candidates.length > 0 && (
                                <optgroup label="Похожие">
                                  {n.candidates.map((c) => (
                                    <option key={c.type_id} value={c.type_id}>
                                      {c.name}
                                    </option>
                                  ))}
                                </optgroup>
                              )}
                              <optgroup label="Все типы">
                                {allTypes.map((t) => (
                                  <option key={t.id} value={t.id}>
                                    {t.name}
                                  </option>
                                ))}
                              </optgroup>
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
                <section aria-labelledby={roomsId} className="flex flex-col gap-1.5">
                  <h3 id={roomsId} className="m-0 text-sm font-semibold">
                    Помещения → план «{report.building.name}»
                    {attention(report.rooms) > 0 && <span className="font-normal text-ink-2"> · проверьте: {attention(report.rooms)}</span>}
                  </h3>
                  <table className="w-full border-collapse text-[13px]">
                    <tbody>
                      {byAttention(report.rooms).map((r) => (
                        <tr key={r.key} className="border-b border-line">
                          <td className="py-1.5 pr-2">
                            {r.floor} этаж, {r.room} {r.room_name}
                            <Status how={r.how} text={r.confirm ? "похоже — подтвердите" : undefined} rows={r.rows.length} />
                            {/* R-002: номер совпал, название нет — показать, куда попадут вещи */}
                            {r.confirm && r.place_title && <div className="mt-1 text-[12px] text-ink-2">на плане — {r.place_title}</div>}
                            <RowErrors errors={report.errors.filter((e) => e.room === r.key)} />
                          </td>
                          <td className="w-1/2 py-1.5">
                            <div className="flex items-center gap-2">
                              <div className="min-w-0 flex-1">
                                <PlacePicker value={rooms[r.key] ?? r.place} onChange={(v) => setRooms({ ...rooms, [r.key]: v ?? "" })} label={`Место для ${r.floor}|${r.room}`} className="h-8 text-[13px]" />
                              </div>
                              {r.confirm && r.place && !rooms[r.key] && (
                                <Button size="sm" onClick={() => setRooms({ ...rooms, [r.key]: r.place! })}>
                                  Верно
                                </Button>
                              )}
                              {r.confirm && rooms[r.key] === r.place && (
                                <span className="inline-flex shrink-0 items-center gap-1 text-[12px] text-ok">
                                  <Check className="size-3.5" aria-hidden /> подтверждено
                                </span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              </>
            )}
          </>
        )}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={close}>{report?.applied ? "Закрыть" : "Отмена"}</Button>
        {file && report && !report.applied && (
          <>
            <Button disabled={busy} onClick={() => void send(file, false)}>
              Проверить снова
            </Button>
            <Button variant="primary" disabled={busy || !report.ok} onClick={() => void send(file, true)}>
              Загрузить
            </Button>
          </>
        )}
      </div>
    </Dialog>
  );
}
