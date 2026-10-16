import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Plus, Printer, QrCode, Save, Trash2, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import type { TypeFull } from "@/catalog/types";
import { ApiError, api, get, post, put } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { PageBody } from "@/shell/Shell";
import { useCardTitle } from "@/shell/context";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Card, Chip, Empty, Loading } from "@/ui/misc";
import { STATUS } from "./DocumentsPage";
import { PlacePicker, TypePicker, UnitPicker, printLabels, useInvalidateInventory } from "./parts";
import { STATES, dateRu, money, today, type Doc, type DocLine } from "./types";

const INPUT_FIELDS = [
  "unit_id", "type_id", "model_id", "qty", "price", "number", "serial", "responsible", "department",
  "state", "commissioned_on", "life_months", "note", "from_place", "to_place", "reason", "new_value",
] as const;

const cell = "h-8 w-full min-w-0 rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink disabled:bg-transparent disabled:border-transparent max-md:h-11";

// 6.5.6: документ — шапка, строки, итог; «Сохранить черновик», «Провести», «Печать»,
// у проведённого — «Отменить» (обратный документ)
export function DocumentPage() {
  const { docId } = useParams();
  const doc = useQuery({ queryKey: ["inventory", "document", docId], queryFn: () => get<Doc>(`/api/inventory/documents/${docId}`) });
  useCardTitle(doc.data?.title);
  if (doc.isLoading) return <Loading />;
  if (!doc.data) return <Empty title="Документ не найден" />;
  if (doc.data.kind === "inventory" && !doc.data.cancels_id) return <Navigate to={`/inventory/${doc.data.id}`} replace />;
  return <Editor key={`${doc.data.id}:${doc.data.version}`} doc={doc.data} />;
}

function Editor({ doc }: { doc: Doc }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const refresh = useInvalidateInventory();
  const [head, setHead] = useState(doc);
  const [lines, setLines] = useState<DocLine[]>(doc.lines);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; errors?: string[] } | null>(null);
  const [confirm, setConfirm] = useState<"post" | "cancel" | "delete" | null>(null);
  const draft = doc.status === "draft";
  const kind = doc.kind;
  const set = (patch: Partial<Doc>) => {
    setHead({ ...head, ...patch });
    setDirty(true);
  };
  const setLine = (i: number, patch: Partial<DocLine>) => {
    setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
    setDirty(true);
  };
  const addLine = (l: DocLine) => {
    setLines([...lines, l]);
    setDirty(true);
  };
  const removeLine = (i: number) => {
    setLines(lines.filter((_, j) => j !== i));
    setDirty(true);
  };
  const body = () => ({
    version: doc.version,
    header: {
      date: head.date, from_place: head.from_place, to_place: head.to_place, basis: head.basis, supplier: head.supplier,
      contractor: head.contractor, repair: head.repair ?? undefined, repair_cost: head.repair_cost, reason: head.reason, note: head.note,
    },
    lines: lines.map((l) => Object.fromEntries(INPUT_FIELDS.filter((k) => l[k] !== undefined).map((k) => [k, l[k]]))),
  });
  const done = (next: Doc) => {
    client.setQueryData(["inventory", "document", next.id], next);
    refresh();
  };
  const fail = (e: unknown) => {
    const err = e as ApiError & { details?: { errors?: string[] } };
    setError({ message: err.message });
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await put<Doc>(`/api/inventory/documents/${doc.id}`, body());
      done(next);
      return next;
    } catch (e) {
      fail(e);
      return null;
    } finally {
      setBusy(false);
    }
  };
  const postIt = async () => {
    setConfirm(null);
    const saved = dirty ? await save() : doc;
    if (!saved) return;
    setBusy(true);
    try {
      done(await post<Doc>(`/api/inventory/documents/${doc.id}/post`, { version: saved.version }));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  const cancelIt = async () => {
    setConfirm(null);
    try {
      const back = await post<Doc>(`/api/inventory/documents/${doc.id}/cancel`);
      refresh();
      navigate(`/documents/${back.id}`);
    } catch (e) {
      fail(e);
    }
  };
  const created = lines.flatMap((l) => l.created_units ?? []);
  const total = lines.reduce((s, l) => s + (l.unit_id ? (l.price ?? 0) : (Number(l.qty) || 0) * (Number(l.price) || 0)), 0);
  const unitIds = lines.map((l) => l.unit_id).filter(Boolean) as string[];

  const withUnits = kind !== "opening" && kind !== "receipt";
  const withQty = kind === "transfer" || kind === "writeoff" || kind === "opening" || kind === "receipt";

  return (
    <PageBody>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="ghost" asChild>
          <Link to="/documents">
            <ArrowLeft /> Документы
          </Link>
        </Button>
        <h1 className={cn("m-0 text-[24px] font-semibold", doc.status === "cancelled" && "line-through")}>
          {doc.title} от {dateRu(doc.date)}
        </h1>
        <Chip tone={STATUS[doc.status][1]}>{STATUS[doc.status][0]}</Chip>
        {doc.cancels_id && (
          <Link to={`/documents/${doc.cancels_id}`} className="text-[13px] text-accent-ink">
            отменяет исходный документ
          </Link>
        )}
        {doc.cancelled_by_id && (
          <Link to={`/documents/${doc.cancelled_by_id}`} className="text-[13px] text-accent-ink">
            отменён обратным документом
          </Link>
        )}
        <div className="flex-1" />
        {draft && (
          <>
            <Button variant="danger" onClick={() => setConfirm("delete")}>
              <Trash2 /> Удалить черновик
            </Button>
            <Button disabled={!dirty || busy} onClick={() => void save()}>
              <Save /> Сохранить черновик
            </Button>
            <Button variant="primary" disabled={busy || !lines.length} onClick={() => setConfirm("post")}>
              <CheckCircle2 /> Провести
            </Button>
          </>
        )}
        {created.length > 0 && (
          <Button onClick={() => void printLabels({ unit_ids: created.map((u) => u.id) }).catch((e) => setError({ message: (e as Error).message }))}>
            <QrCode /> Метки ({created.length})
          </Button>
        )}
        <Button asChild>
          <a href={`/api/inventory/documents/${doc.id}/print.pdf`} target="_blank" rel="noreferrer">
            <Printer /> Печать
          </a>
        </Button>
        {doc.status === "posted" && !doc.cancels_id && (
          <Button variant="danger" onClick={() => setConfirm("cancel")}>
            <Undo2 /> Отменить
          </Button>
        )}
      </div>
      {!!doc.warnings?.length && (
        <div role="note" className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn">
          {doc.warnings.map((w) => (
            <p key={w} className="m-0">
              {w}
            </p>
          ))}
        </div>
      )}
      {error && (
        <div role="alert" className="rounded-lg border border-bad/30 bg-bad-soft px-3 py-2 text-sm text-bad">
          {error.message}
        </div>
      )}

      {/* шапка */}
      <Card className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
        <Labeled label="Дата">
          <input type="date" aria-label="Дата документа" disabled={!draft} value={head.date} max={today()} onChange={(e) => set({ date: e.target.value })} className={cell} />
        </Labeled>
        {kind === "repair" && (
          <Labeled label="Что">
            <select aria-label="Ремонт" disabled={!draft} value={head.repair ?? "send"} onChange={(e) => set({ repair: e.target.value as "send" | "return" })} className={cell}>
              <option value="send">отправка в ремонт</option>
              <option value="return">возврат из ремонта</option>
            </select>
          </Labeled>
        )}
        {(kind === "transfer" || kind === "writeoff") && (
          <Labeled label={kind === "transfer" ? "Откуда" : "Откуда (для количества)"}>
            {draft ? (
              <PlacePicker value={head.from_place} onChange={(v) => set({ from_place: v })} label="Откуда" allowEmpty emptyTitle={kind === "transfer" ? "— откуда числится —" : "—"} className={cell} />
            ) : (
              <div className="text-sm">{doc.from_title || "откуда числилось"}</div>
            )}
          </Labeled>
        )}
        {(kind === "transfer" || kind === "receipt" || kind === "opening") && (
          <Labeled label="Куда">
            {draft ? <PlacePicker value={head.to_place} onChange={(v) => set({ to_place: v })} label="Куда" allowEmpty className={cell} /> : <div className="text-sm">{doc.to_title || "—"}</div>}
          </Labeled>
        )}
        {kind === "receipt" && (
          <Labeled label="Поставщик">
            <input aria-label="Поставщик" disabled={!draft} value={head.supplier} onChange={(e) => set({ supplier: e.target.value })} className={cell} />
          </Labeled>
        )}
        {kind === "repair" && (
          <>
            <Labeled label="Исполнитель ремонта">
              <input aria-label="Исполнитель ремонта" disabled={!draft} value={head.contractor} onChange={(e) => set({ contractor: e.target.value })} className={cell} />
            </Labeled>
            {head.repair === "return" && (
              <Labeled label="Стоимость ремонта, ₽">
                <input aria-label="Стоимость ремонта" inputMode="decimal" disabled={!draft} value={head.repair_cost ?? ""} onChange={(e) => set({ repair_cost: e.target.value === "" ? null : Number(e.target.value.replace(",", ".")) })} className={cell} />
              </Labeled>
            )}
          </>
        )}
        {kind === "writeoff" && (
          <Labeled label="Причина списания">
            <input aria-label="Причина списания" disabled={!draft} value={head.reason} onChange={(e) => set({ reason: e.target.value })} className={cell} placeholder="износ, поломка, израсходовано…" />
          </Labeled>
        )}
        <Labeled label="Основание">
          <input aria-label="Основание" disabled={!draft} value={head.basis} onChange={(e) => set({ basis: e.target.value })} className={cell} placeholder="приказ, накладная, акт…" />
        </Labeled>
      </Card>

      {/* строки */}
      <Card className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="text-left text-xs text-ink-2">
              <th className="w-8 border-b border-line px-2 py-2">№</th>
              <th className="border-b border-line px-2 py-2 font-medium">Наименование</th>
              <th className="w-40 border-b border-line px-2 py-2 font-medium">Инв. номер / кол-во</th>
              {(kind === "receipt" || kind === "opening") && <th className="w-28 border-b border-line px-2 py-2 font-medium">Цена, ₽</th>}
              {kind === "revaluation" && <th className="w-32 border-b border-line px-2 py-2 font-medium">Новая стоимость</th>}
              <th className="w-28 border-b border-line px-2 py-2 font-medium">Сумма</th>
              {draft && <th className="w-10 border-b border-line" />}
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <LineRow key={l.id ?? i} n={i + 1} line={l} doc={doc} draft={draft} onChange={(p) => setLine(i, p)} onRemove={() => removeLine(i)} />
            ))}
          </tbody>
          <tfoot>
            <tr className="font-medium">
              <td />
              <td colSpan={kind === "receipt" || kind === "opening" || kind === "revaluation" ? 3 : 2} className="px-2 py-2">
                Итого
              </td>
              <td className="px-2 py-2 font-mono">{money(total)}</td>
              {draft && <td />}
            </tr>
          </tfoot>
        </table>
        {!lines.length && <p className="m-0 px-4 py-3 text-[13px] text-ink-3">Строк нет — добавьте ниже.</p>}
      </Card>
      {draft && (
        <div className="flex flex-wrap items-start gap-2">
          {withUnits && (
            <div className="w-full max-w-md">
              <UnitPicker
                place={kind === "transfer" ? head.from_place : undefined}
                exclude={unitIds}
                states={kind === "repair" ? (head.repair === "return" ? ["repair"] : ["in_use", "broken", "storage"]) : undefined}
                onPick={(u) => addLine({ unit_id: u.id, number: u.number, type_name: u.title, unit_place: u.place?.title, unit_state: u.state, price: u.price, accounting: "piece", qty: 1 })}
              />
            </div>
          )}
          {withQty && (
            <Button onClick={() => addLine({ qty: 1, price: kind === "receipt" || kind === "opening" ? null : undefined, accounting: "quantity" })}>
              <Plus /> {kind === "receipt" || kind === "opening" ? "Строка: тип и количество" : "Количество (остаток)"}
            </Button>
          )}
        </div>
      )}
      {!draft && (
        <p className="m-0 text-[12px] text-ink-3">
          Создан: {doc.created_by}. {doc.posted_at && `Проведён ${formatDateTime(doc.posted_at)}: ${doc.posted_by}.`} Проведённый документ не правится — ошибка исправляется отменой.
        </p>
      )}

      <Dialog
        open={confirm !== null}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={confirm === "post" ? "Провести документ?" : confirm === "cancel" ? "Отменить документ?" : "Удалить черновик?"}
        description={
          confirm === "post"
            ? "Проведённый документ не правится: место, количество и стоимость имущества изменятся. Если хоть одна строка невозможна, не проведётся ничего."
            : confirm === "cancel"
              ? "Будет создан и проведён обратный документ со ссылкой на этот: всё вернётся, как было до него."
              : "Черновик удаляется насовсем."
        }
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>Нет</Button>
            <Button
              variant={confirm === "post" ? "primary" : "danger"}
              onClick={async () => {
                if (confirm === "post") await postIt();
                else if (confirm === "cancel") await cancelIt();
                else {
                  await api("DELETE", `/api/inventory/documents/${doc.id}`);
                  refresh();
                  navigate("/documents");
                }
              }}
            >
              {confirm === "post" ? "Провести" : confirm === "cancel" ? "Отменить документ" : "Удалить"}
            </Button>
          </>
        }
      />
    </PageBody>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 text-[12px] text-ink-2">
      {label}
      {children}
    </div>
  );
}

function LineRow({ n, line: l, doc, draft, onChange, onRemove }: { n: number; line: DocLine; doc: Doc; draft: boolean; onChange: (p: Partial<DocLine>) => void; onRemove: () => void }) {
  const kind = doc.kind;
  const newItems = kind === "receipt" || kind === "opening";
  const type = useQuery({ queryKey: ["catalog-type", l.type_id], queryFn: () => get<TypeFull>(`/api/catalog/types/${l.type_id}`), enabled: !!l.type_id && newItems && draft });
  const piece = newItems ? (type.data?.accounting ?? l.accounting) !== "quantity" : !!l.unit_id;
  const [more, setMore] = useState(false);
  useEffect(() => {
    if (type.data && newItems && draft && l.accounting !== type.data.accounting) onChange({ accounting: type.data.accounting, unit: type.data.unit });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type.data]);
  const amount = l.unit_id ? (l.price ?? 0) : (Number(l.qty) || 0) * (Number(l.price) || 0);
  return (
    <>
      <tr className="align-top">
        <td className="border-b border-line px-2 py-2 text-ink-3">{n}</td>
        <td className="border-b border-line px-2 py-2">
          {l.unit_id ? (
            <>
              <Link to={`/property?card=unit:${l.unit_id}`} className="font-medium text-ink">
                {l.type_name}
              </Link>{" "}
              {l.model_name && <span className="text-ink-2">{l.model_name}</span>}
              <div className="text-[11px] text-ink-3">
                {l.unit_place}
                {l.unit_state && ` · ${STATES[l.unit_state]}`}
              </div>
              {kind === "writeoff" && (
                <input aria-label={`Причина, строка ${n}`} disabled={!draft} placeholder="причина (если не общая)" value={l.reason ?? ""} onChange={(e) => onChange({ reason: e.target.value })} className={cn(cell, "mt-1")} />
              )}
            </>
          ) : draft ? (
            <div className="flex flex-col gap-1">
              <TypePicker value={l.type_id} label={`Тип, строка ${n}`} onChange={(t) => onChange({ type_id: t?.id ?? null, type_name: t?.name, model_id: null, accounting: t?.accounting, unit: t?.unit })} />
              {newItems && type.data && type.data.models.length > 0 && (
                <select aria-label={`Модель, строка ${n}`} value={l.model_id ?? ""} onChange={(e) => onChange({ model_id: e.target.value || null })} className={cell}>
                  <option value="">модель не выбрана</option>
                  {type.data.models.filter((m) => !m.archived).map((m) => (
                    <option key={m.id} value={m.id}>
                      {[m.manufacturer, m.name].filter(Boolean).join(" ")}
                    </option>
                  ))}
                </select>
              )}
            </div>
          ) : (
            <>
              <span className="font-medium">{l.type_name}</span> {l.model_name && <span className="text-ink-2">{l.model_name}</span>}
              {(l.from_title || l.to_title) && <div className="text-[11px] text-ink-3">{[l.from_title, l.to_title].filter(Boolean).join(" → ")}</div>}
            </>
          )}
        </td>
        <td className="border-b border-line px-2 py-2">
          {l.unit_id ? (
            <span className="font-mono">{l.number}</span>
          ) : l.created_units?.length ? (
            <span className="font-mono text-[12px]">{l.created_units.map((u) => u.number).join(", ")}</span>
          ) : (
            <div className="flex items-center gap-1">
              <input aria-label={`Количество, строка ${n}`} inputMode="decimal" disabled={!draft} value={l.qty ?? ""} onChange={(e) => onChange({ qty: e.target.value === "" ? undefined : Number(e.target.value.replace(",", ".")) })} className={cn(cell, "w-20")} />
              <span className="text-ink-3">{piece && newItems ? "шт." : (l.unit ?? "")}</span>
            </div>
          )}
          {newItems && piece && draft && Number(l.qty) === 1 && (
            <input aria-label={`Инв. номер, строка ${n}`} placeholder="номер — если есть наклейка" value={l.number ?? ""} onChange={(e) => onChange({ number: e.target.value })} className={cn(cell, "mt-1 font-mono")} />
          )}
        </td>
        {newItems && (
          <td className="border-b border-line px-2 py-2">
            <input aria-label={`Цена, строка ${n}`} inputMode="decimal" disabled={!draft} value={l.price ?? ""} onChange={(e) => onChange({ price: e.target.value === "" ? null : Number(e.target.value.replace(",", ".")) })} className={cell} />
          </td>
        )}
        {kind === "revaluation" && (
          <td className="border-b border-line px-2 py-2">
            <input aria-label={`Новая стоимость, строка ${n}`} inputMode="decimal" disabled={!draft} value={l.new_value ?? ""} onChange={(e) => onChange({ new_value: e.target.value === "" ? null : Number(e.target.value.replace(",", ".")) })} className={cell} />
          </td>
        )}
        <td className="border-b border-line px-2 py-2 font-mono">{money(amount)}</td>
        {draft && (
          <td className="border-b border-line px-1 py-2">
            <Button size="icon" variant="ghost" aria-label={`Убрать строку ${n}`} onClick={onRemove}>
              <Trash2 />
            </Button>
          </td>
        )}
      </tr>
      {newItems && draft && piece && (
        <tr>
          <td />
          <td colSpan={5} className="border-b border-line px-2 pb-2">
            <button type="button" onClick={() => setMore(!more)} className="cursor-pointer border-0 bg-transparent p-0 text-[12px] text-accent-ink">
              {more ? "Скрыть подробности" : "Подробности: серийный номер, ответственный, место, дата ввода…"}
            </button>
            {more && (
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                <input aria-label={`Серийный номер, строка ${n}`} placeholder="Серийный номер" value={l.serial ?? ""} onChange={(e) => onChange({ serial: e.target.value })} className={cell} />
                <input aria-label={`Ответственный, строка ${n}`} placeholder="Ответственный" value={l.responsible ?? ""} onChange={(e) => onChange({ responsible: e.target.value })} className={cell} />
                <input aria-label={`Подразделение, строка ${n}`} placeholder="Подразделение" value={l.department ?? ""} onChange={(e) => onChange({ department: e.target.value })} className={cell} />
                {kind === "opening" && (
                  <>
                    <PlacePicker value={l.to_place} onChange={(v) => onChange({ to_place: v })} label={`Куда, строка ${n}`} allowEmpty emptyTitle="как в шапке" className={cell} />
                    <input type="date" aria-label={`Дата ввода, строка ${n}`} max={today()} value={l.commissioned_on ?? ""} onChange={(e) => onChange({ commissioned_on: e.target.value || null })} className={cell} />
                    <select aria-label={`Состояние, строка ${n}`} value={l.state ?? ""} onChange={(e) => onChange({ state: e.target.value || null })} className={cell}>
                      <option value="">состояние — по месту</option>
                      {(["in_use", "broken", "repair", "storage"] as const).map((s) => (
                        <option key={s} value={s}>
                          {STATES[s]}
                        </option>
                      ))}
                    </select>
                  </>
                )}
                <input aria-label={`Срок службы, строка ${n}`} inputMode="numeric" placeholder="Срок службы, мес. (из типа)" value={l.life_months ?? ""} onChange={(e) => onChange({ life_months: e.target.value ? Number(e.target.value) : null })} className={cell} />
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
