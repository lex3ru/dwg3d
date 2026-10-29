import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, FileUp, MapPin, QrCode, RotateCcw, Trash2, Truck, Wrench, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { ValueInput } from "@/catalog/parts";
import type { Characteristic } from "@/catalog/types";
import { showValue } from "@/catalog/types";
import { ApiError, api, get, patch, post } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { formatBytes, formatDateTime } from "@/lib/format";
import { journalUrl } from "@/lib/journal";
import { TextField } from "@/editor/Properties";
import { useCardTitle } from "@/shell/context";
import { Button } from "@/ui/button";
import { FormError } from "@/ui/form";
import { Loading } from "@/ui/misc";
import { StateChip, printLabels, useInvalidateInventory } from "./parts";
import { KINDS, dateRu, money, type Doc, type UnitFull } from "./types";

type Tab = "main" | "cost" | "files" | "moves" | "history";

// 6.5.3: карточка инвентарной единицы
export function UnitCard({ id }: { id: string }) {
  const me = useMe();
  const admin = me.role === "admin";
  const client = useQueryClient();
  const refresh = useInvalidateInventory();
  const navigate = useNavigate();
  const unit = useQuery({ queryKey: ["inventory", "unit", id], queryFn: () => get<UnitFull>(`/api/inventory/units/${id}`) });
  const placed = useQuery({
    queryKey: ["inventory", "unit-item", id],
    queryFn: () => get<{ item: { item_id: string; floor_id: string; building_id: string } | null }>(`/api/link/units/${id}`),
  });
  const [tab, setTab] = useState<Tab>("main");
  const [error, setError] = useState<string | null>(null);
  const photo = useRef<HTMLInputElement>(null);
  const doc = useRef<HTMLInputElement>(null);
  useCardTitle(unit.data ? `${unit.data.title}${unit.data.number ? ` № ${unit.data.number}` : ""}` : null);
  if (unit.isLoading) return <Loading />;
  if (!unit.data) return <p className="text-sm text-bad">Инвентарная единица не найдена.</p>;
  const u = unit.data;
  const live = u.state !== "written_off";

  const edit = async (values: Record<string, unknown>) => {
    setError(null);
    try {
      const next = await patch<UnitFull>(`/api/inventory/units/${u.id}`, { version: u.version, values });
      client.setQueryData(["inventory", "unit", id], next);
      refresh();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  const act = async (kind: string, header: Record<string, unknown> = {}) => {
    setError(null);
    try {
      const d = await post<Doc>("/api/inventory/documents", { kind, header, lines: [{ unit_id: u.id }] });
      navigate(`/documents/${d.id}`);
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  const upload = async (f: File, kind: "photo" | "doc") => {
    setError(null);
    const form = new FormData();
    form.append("file", f);
    const r = await fetch(`/api/inventory/units/${u.id}/files?kind=${kind}`, { method: "POST", body: form, headers: { "X-Requested-With": "app" }, credentials: "same-origin" });
    const body = await r.json();
    if (!r.ok) setError(body?.error?.message ?? "Файл не загрузился.");
    else client.setQueryData(["inventory", "unit", id], body);
    refresh();
  };
  // «Показать на плане» (С17): этаж с подсвеченным предметом, если единица стоит на плане,
  // иначе — её помещение
  const where = u.place?.room_id ? `/plan/${u.place.building_id}/${u.place.floor_id}?room=${u.place.room_id}` : null;
  const onPlan = placed.data?.item ? `/plan/${placed.data.item.building_id}/${placed.data.item.floor_id}?item=${placed.data.item.item_id}&mode=place` : where;
  const tabs: [Tab, string][] = [
    ["main", "Основное"],
    ...(admin ? ([["cost", "Стоимость"]] as [Tab, string][]) : []),
    ["files", `Файлы (${u.files.length})`],
    ...(admin ? ([["moves", "Движение"]] as [Tab, string][]) : []),
    ["history", "История"],
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-3">
        <div className="flex size-20 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-line bg-surface-2">
          {u.photo_url ? <img src={u.photo_url} alt="Фото" className="size-full object-cover" /> : <Camera className="size-6 text-ink-3" />}
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="m-0 text-lg leading-tight font-semibold">{u.title}</h2>
          {u.number && <div className="font-mono text-sm">№ {u.number}</div>}
          <div className="flex flex-wrap items-center gap-2">
            <StateChip state={u.state} />
            {u.serial && <span className="text-[12px] text-ink-3">с/н {u.serial}</span>}
          </div>
        </div>
      </div>
      <div className="text-[13px]">
        <span className="text-ink-2">Числится: </span>
        {u.place?.room_id && u.place.building_id && u.place.floor_id ? (
          <Link to={`/plan/${u.place.building_id}/${u.place.floor_id}?room=${u.place.room_id}`} className="text-accent-ink">
            {u.place.title}
          </Link>
        ) : (
          (u.place?.title ?? "—")
        )}
        {u.parent && (
          <div className="text-ink-2">
            В составе:{" "}
            <Link to={`?card=unit:${u.parent.id}`} className="text-accent-ink">
              {u.parent.title} {u.parent.number}
            </Link>
          </div>
        )}
        {u.state === "written_off" && (
          <div className="text-ink-2">
            Списана {dateRu(u.written_off_on)}: {u.writeoff_reason}
          </div>
        )}
      </div>
      {admin && live && (
        <div className="flex flex-wrap gap-1.5">
          {onPlan && (
            <Button size="sm" asChild>
              <Link to={onPlan}>
                <MapPin /> {placed.data?.item ? "Показать на плане" : "Помещение на плане"}
              </Link>
            </Button>
          )}
          <Button size="sm" onClick={() => void act("transfer")}>
            <Truck /> Переместить
          </Button>
          {u.state === "repair" ? (
            <Button size="sm" onClick={() => void act("repair", { repair: "return" })}>
              <Wrench /> Из ремонта
            </Button>
          ) : (
            <Button size="sm" onClick={() => void act("repair", { repair: "send" })}>
              <Wrench /> В ремонт
            </Button>
          )}
          <Button size="sm" variant="danger" onClick={() => void act("writeoff")}>
            <XCircle /> Списать
          </Button>
          <Button size="sm" onClick={() => void printLabels({ unit_ids: [u.id] }).catch((e) => setError((e as Error).message))}>
            <QrCode /> Метка
          </Button>
        </div>
      )}
      {!admin && onPlan && (
        <Button size="sm" asChild className="self-start">
          <Link to={onPlan}>
            <MapPin /> Показать на плане
          </Link>
        </Button>
      )}
      <FormError message={error} />
      <div role="tablist" className="flex flex-wrap gap-1 border-b border-line">
        {tabs.map(([k, t]) => (
          <button key={k} role="tab" type="button" aria-selected={tab === k} onClick={() => setTab(k)} className={cn("-mb-px h-9 cursor-pointer border-0 border-b-2 bg-transparent px-2 text-[13px] max-md:h-11", tab === k ? "border-accent font-medium" : "border-transparent text-ink-2")}>
            {t}
          </button>
        ))}
      </div>

      {tab === "main" && (
        <div className="flex flex-col gap-3">
          <TextField label="Ответственный" value={u.responsible} readOnly={!admin || !live} placeholder="ФИО" onChange={(responsible) => void edit({ responsible })} />
          <TextField label="Подразделение" value={u.department} readOnly={!admin || !live} onChange={(department) => void edit({ department })} />
          {admin && live && (u.state === "in_use" || u.state === "broken") && (
            <label className="flex flex-col gap-1 text-[12px] text-ink-2">
              Состояние
              <select aria-label="Состояние" value={u.state} onChange={(e) => void edit({ state: e.target.value })} className="h-8 rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink">
                <option value="in_use">в работе</option>
                <option value="broken">неисправна</option>
              </select>
            </label>
          )}
          <div className="text-[12px] text-ink-2">Дата ввода: {dateRu(u.commissioned_on)}</div>
          {u.characteristics.length > 0 && (
            <table className="w-full border-collapse text-[13px]">
              <tbody>
                {u.characteristics.map((c) => (
                  <tr key={c.id} className="border-b border-line">
                    <td className="w-1/2 py-1.5 pr-2 text-ink-2">
                      {c.name}
                      {c.unit && `, ${c.unit}`}
                      {c.required && <span className="text-bad"> *</span>}
                    </td>
                    <td className="py-1.5">
                      {c.level === "item" && admin && live ? (
                        <ValueInput c={c as unknown as Characteristic} value={c.value} onChange={(v) => void edit({ values: { [c.id]: v } })} />
                      ) : (
                        showValue(c as unknown as Characteristic, c.value)
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <TextField label="Примечание" value={u.note} readOnly={!admin || !live} onChange={(note) => void edit({ note })} />
          {u.children.length > 0 && (
            <div className="text-[13px]">
              <div className="text-[12px] text-ink-2">В составе этой единицы:</div>
              {u.children.map((c) => (
                <div key={c.id}>
                  <Link to={`?card=unit:${c.id}`} className="text-accent-ink">
                    {c.title} {c.number}
                  </Link>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "cost" && (
        <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-2 text-[13px]">
          <dt className="text-ink-2">Цена приобретения</dt>
          <dd className="m-0 font-mono">{money(u.price)}</dd>
          <dt className="text-ink-2">Дата ввода</dt>
          <dd className="m-0">{dateRu(u.commissioned_on)}</dd>
          <dt className="text-ink-2">Срок службы</dt>
          <dd className="m-0">{u.life_months ? `${u.life_months} мес.` : "не задан — не убывает"}</dd>
          {u.value_base != null && (
            <>
              <dt className="text-ink-2">Переоценка</dt>
              <dd className="m-0 font-mono">
                {money(u.value_base)} на {dateRu(u.value_date)}
              </dd>
            </>
          )}
          <dt className="text-ink-2">Остаточная сегодня</dt>
          <dd className="m-0 font-mono font-medium">{money(u.value)}</dd>
        </dl>
      )}

      {tab === "files" && (
        <div className="flex flex-col gap-2">
          <input ref={photo} type="file" accept="image/*" capture="environment" className="hidden" aria-label="Фото" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0], "photo")} />
          <input ref={doc} type="file" accept="application/pdf,image/*" className="hidden" aria-label="Документ" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0], "doc")} />
          {admin && live && (
            <div className="flex gap-2">
              <Button size="sm" onClick={() => photo.current?.click()}>
                <Camera /> Фото
              </Button>
              <Button size="sm" onClick={() => doc.current?.click()}>
                <FileUp /> Документ
              </Button>
            </div>
          )}
          {u.files.map((f) => (
            <div key={f.link_id} className="flex items-center gap-2 text-[13px]">
              <a href={f.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-accent-ink">
                {f.kind === "photo" ? "📷 " : ""}
                {f.name}
              </a>
              <span className="text-[11px] text-ink-3">{formatBytes(f.size)}</span>
              {admin && (
                <Button size="icon" variant="ghost" aria-label={`Убрать ${f.name}`} onClick={async () => { await api("DELETE", `/api/inventory/files/${f.link_id}`); void unit.refetch(); }}>
                  <Trash2 />
                </Button>
              )}
            </div>
          ))}
          {!u.files.length && <p className="m-0 text-[13px] text-ink-3">Файлов нет: фото, паспорт, гарантийный талон, акты.</p>}
        </div>
      )}

      {tab === "moves" && (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px]">
          {u.movements.map((m, i) => (
            <li key={i} className="border-b border-line pb-1.5">
              <Link to={`/documents/${m.document_id}`} className={cn("text-accent-ink", m.status === "cancelled" && "line-through")}>
                {m.title}
              </Link>{" "}
              <span className="text-ink-3">{dateRu(m.date)}</span>
              <div className="text-[12px] text-ink-2">{[m.from, m.to].filter(Boolean).join(" → ") || KINDS[m.kind]}</div>
            </li>
          ))}
          {!u.movements.length && <li className="text-ink-3">Документов нет.</li>}
        </ul>
      )}

      {tab === "history" && (
        <ul className="m-0 flex list-none flex-col gap-2 p-0 text-[13px]">
          {u.changes.map((c) => (
            <li key={c.id} className="border-b border-line pb-2">
              <div className="flex items-center gap-2">
                <span className="flex-1 text-ink-2">
                  {formatDateTime(c.at)} · {c.actor}
                </span>
                {c.can_roll_back && (
                  <Button size="sm" variant="ghost" onClick={async () => { await post(`/api/inventory/changes/${c.id}/rollback`); void unit.refetch(); refresh(); }}>
                    <RotateCcw /> Откатить
                  </Button>
                )}
              </div>
              {Object.keys(c.after).map((k) => (
                <div key={k} className={cn(c.rolled_back && "text-ink-3 line-through")}>
                  {FIELD[k] ?? k}: <span className="text-ink-3">{show(c.before[k])}</span> → {show(c.after[k])}
                </div>
              ))}
            </li>
          ))}
          {!u.changes.length && <li className="text-ink-3">Карточку не правили. Движение — во вкладке «Движение».</li>}
          {admin && (
            <li>
              <Link to={journalUrl(`unit:${u.id}`, u.title + (u.number ? ` № ${u.number}` : ""))}>Журнал единицы</Link>
              <span className="text-ink-3"> — всё вместе: документы, перенос при объединении помещений, файлы</span>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

const FIELD: Record<string, string> = {
  responsible: "Ответственный",
  department: "Подразделение",
  note: "Примечание",
  state: "Состояние",
  values: "Характеристики",
  parent_id: "В составе",
};

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (v === "in_use") return "в работе";
  if (v === "broken") return "неисправна";
  if (typeof v === "object") return Object.values(v as Record<string, unknown>).map((x) => show(x)).join(", ");
  return String(v);
}
