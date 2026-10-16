import { useQuery } from "@tanstack/react-query";
import { Columns3, Download, FileSpreadsheet, FileUp, Plus, QrCode, Truck } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { useTree } from "@/catalog/parts";
import { ApiError, get, post, query } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { PageBody } from "@/shell/Shell";
import { useCard } from "@/shell/context";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { FormError, Input } from "@/ui/form";
import { Card, Empty, Loading, PageHeader } from "@/ui/misc";
import { ImportDialog } from "./ImportDialog";
import { PlacePicker, StateChip, printLabels, usePlaceTree } from "./parts";
import { STATES, dateRu, money, today, type Balance, type Doc, type Registry, type State, type UnitBrief } from "./types";

type Tab = "registry" | "balances" | "cost";

// 6.5.4: реестр имущества; остатки на дату (5.4.3); стоимость на дату (5.4.5, С19)
export function PropertyPage() {
  const me = useMe();
  const admin = me.role === "admin";
  const [params, setParams] = useSearchParams();
  const tab = ((admin && params.get("tab")) || "registry") as Tab;
  const [importing, setImporting] = useState(false);
  const navigate = useNavigate();
  const newDoc = async (kind: string) => {
    const doc = await post<Doc>("/api/inventory/documents", { kind, header: {} });
    navigate(`/documents/${doc.id}`);
  };
  return (
    <PageBody>
      <PageHeader
        title="Имущество"
        subtitle={admin ? "Инвентарные единицы, остатки и стоимость" : "Что где числится"}
        actions={
          admin && (
            <>
              <Button onClick={() => setImporting(true)}>
                <FileUp /> Загрузить из Excel
              </Button>
              <Button onClick={() => void newDoc("receipt")}>
                <Plus /> Приход
              </Button>
            </>
          )
        }
      />
      {admin && (
        <div role="tablist" aria-label="Разделы" className="flex gap-1 border-b border-line">
          {([["registry", "Реестр"], ["balances", "Остатки"], ["cost", "Стоимость"]] as [Tab, string][]).map(([k, t]) => (
            <button
              key={k}
              role="tab"
              type="button"
              aria-selected={tab === k}
              onClick={() => setParams((p) => {
                const out = new URLSearchParams(p);
                if (k === "registry") out.delete("tab");
                else out.set("tab", k);
                return out;
              })}
              className={cn("-mb-px h-10 cursor-pointer border-0 border-b-2 bg-transparent px-3 text-sm max-md:h-11", tab === k ? "border-accent font-medium" : "border-transparent text-ink-2")}
            >
              {t}
            </button>
          ))}
        </div>
      )}
      {tab === "registry" && <RegistryTab />}
      {tab === "balances" && <BalancesTab />}
      {tab === "cost" && <CostTab />}
      <ImportDialog open={importing} onClose={() => setImporting(false)} />
    </PageBody>
  );
}

// ---------------------------------------------------------------- реестр

const COLUMNS = [
  ["number", "Инв. номер"],
  ["title", "Наименование"],
  ["serial", "Серийный номер"],
  ["place", "Место"],
  ["state", "Состояние"],
  ["responsible", "Ответственный"],
  ["department", "Подразделение"],
  ["commissioned_on", "Дата ввода"],
  ["price", "Цена"],
  ["value", "Остаточная"],
] as const;
type Col = (typeof COLUMNS)[number][0];
const DEFAULT_COLS: Col[] = ["number", "title", "place", "state", "responsible", "price"];

function readCols(): Col[] {
  try {
    const raw = localStorage.getItem("registry-columns");
    return raw ? (JSON.parse(raw) as Col[]) : DEFAULT_COLS;
  } catch {
    return DEFAULT_COLS;
  }
}

interface Filters {
  q: string;
  building_id: string;
  floor_id: string;
  place: string;
  layer_id: string;
  state: string;
  responsible: string;
  department: string;
  since: string;
  until: string;
  written_off: boolean;
}
const EMPTY: Filters = { q: "", building_id: "", floor_id: "", place: "", layer_id: "", state: "", responsible: "", department: "", since: "", until: "", written_off: false };

function readFilters(): Filters {
  try {
    const raw = localStorage.getItem("registry-filters");
    return raw ? { ...EMPTY, ...(JSON.parse(raw) as Partial<Filters>) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

function RegistryTab() {
  const me = useMe();
  const admin = me.role === "admin";
  const navigate = useNavigate();
  const [card, setCard] = useCard();
  // ссылка с главной («Неисправные» и т. п.) задаёт выборку: она — поверх запомненной
  const [urlParams] = useSearchParams();
  const [filters, setFiltersState] = useState<Filters>(() => {
    const fromUrl = Object.fromEntries((["state", "building_id", "place"] as const).filter((k) => urlParams.get(k)).map((k) => [k, urlParams.get(k)!]));
    return Object.keys(fromUrl).length ? { ...EMPTY, ...fromUrl } : readFilters();
  });
  const [sort, setSort] = useState("number");
  const [limit, setLimit] = useState(100);
  const [cols, setColsState] = useState<Col[]>(readCols);
  const [chooser, setChooser] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const places = usePlaceTree();
  const catalog = useTree();
  const setFilters = (f: Partial<Filters>) => {
    const next = { ...filters, ...f };
    setFiltersState(next);
    setLimit(100);
    try {
      localStorage.setItem("registry-filters", JSON.stringify(next));
    } catch {
      /* не запомнится */
    }
  };
  const setCols = (c: Col[]) => {
    setColsState(c);
    try {
      localStorage.setItem("registry-columns", JSON.stringify(c));
    } catch {
      /* не запомнится */
    }
  };
  const params = { ...filters, written_off: filters.written_off ? "true" : undefined, sort, limit };
  const list = useQuery({ queryKey: ["inventory", "units", params], queryFn: () => get<Registry>(`/api/inventory/units${query(params)}`) });
  const items = list.data?.items ?? [];
  const visibleCols = cols.filter((c) => (c !== "number" || admin) && ((c !== "price" && c !== "value") || admin));
  const floors = places.data?.buildings.find((b) => b.id === filters.building_id)?.floors ?? [];
  const chosen = items.filter((u) => selected.has(u.id));
  const toggle = (id: string) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  });
  const move = async () => {
    setError(null);
    try {
      const doc = await post<Doc>("/api/inventory/documents", { kind: "transfer", header: {}, lines: chosen.map((u) => ({ unit_id: u.id })) });
      navigate(`/documents/${doc.id}`);
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  const exportUrl = `/api/inventory/units/export.xlsx${query({ ...params, limit: undefined, ids: selected.size ? [...selected].join(",") : undefined })}`;
  const sortBy = (c: Col) => setSort(sort === c ? `-${c}` : c);
  const cell = (u: UnitBrief, c: Col) => {
    switch (c) {
      case "number":
        return <span className="font-mono">{u.number}</span>;
      case "title":
        return <span className="font-medium">{u.title}</span>;
      case "serial":
        return u.serial || "—";
      case "place":
        return u.place?.title ?? "—";
      case "state":
        return <StateChip state={u.state} />;
      case "responsible":
        return u.responsible || "—";
      case "department":
        return u.department || "—";
      case "commissioned_on":
        return dateRu(u.commissioned_on);
      case "price":
        return <span className="font-mono">{money(u.price)}</span>;
      case "value":
        return <span className="font-mono">{money(u.value)}</span>;
    }
  };
  const input = "h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input aria-label="Поиск в реестре" placeholder="Название, инв. или серийный номер" value={filters.q} onChange={(e) => setFilters({ q: e.target.value })} className="max-w-xs" />
        <select aria-label="Здание" value={filters.building_id} onChange={(e) => setFilters({ building_id: e.target.value, floor_id: "" })} className={input}>
          <option value="">все здания</option>
          {places.data?.buildings.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
        {floors.length > 0 && (
          <select aria-label="Этаж" value={filters.floor_id} onChange={(e) => setFilters({ floor_id: e.target.value })} className={input}>
            <option value="">все этажи</option>
            {floors.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        )}
        <PlacePicker value={filters.place} onChange={(place) => setFilters({ place: place ?? "" })} label="Место хранения" allowEmpty emptyTitle="все места" className="w-auto max-w-xs" />
        <select aria-label="Слой" value={filters.layer_id} onChange={(e) => setFilters({ layer_id: e.target.value })} className={input}>
          <option value="">все слои</option>
          {catalog.data?.layers.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
        <select aria-label="Состояние" value={filters.state} onChange={(e) => setFilters({ state: e.target.value })} className={input}>
          <option value="">любое состояние</option>
          {(Object.keys(STATES) as State[]).map((s) => (
            <option key={s} value={s}>
              {STATES[s]}
            </option>
          ))}
        </select>
        <Input aria-label="Ответственный" placeholder="Ответственный" value={filters.responsible} onChange={(e) => setFilters({ responsible: e.target.value })} className="w-44" />
        <Input aria-label="Подразделение" placeholder="Подразделение" value={filters.department} onChange={(e) => setFilters({ department: e.target.value })} className="w-44" />
        <label className="flex items-center gap-1.5 text-[13px] text-ink-2">
          введены с
          <input type="date" aria-label="Введены с" value={filters.since} onChange={(e) => setFilters({ since: e.target.value })} className={input} />
          по
          <input type="date" aria-label="Введены по" value={filters.until} onChange={(e) => setFilters({ until: e.target.value })} className={input} />
        </label>
        <label className="flex items-center gap-1.5 text-[13px] text-ink-2">
          <input type="checkbox" checked={filters.written_off} onChange={(e) => setFilters({ written_off: e.target.checked })} /> и списанные
        </label>
        <Button size="sm" variant="ghost" onClick={() => setFilters(EMPTY)}>
          Сбросить
        </Button>
        <div className="flex-1" />
        <Button size="sm" variant="ghost" aria-label="Столбцы" onClick={() => setChooser(true)}>
          <Columns3 /> Столбцы
        </Button>
      </div>
      <FormError message={error} />
      <Card className="overflow-x-auto">
        {list.isLoading ? (
          <Loading />
        ) : !items.length ? (
          <Empty title="Ничего не числится">Измените фильтры — или поставьте имущество на учёт: приход, ввод остатков, загрузка из Excel.</Empty>
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-2">
                {admin && (
                  <th className="w-8 border-b border-line px-3 py-2">
                    <input type="checkbox" aria-label="Выбрать все" checked={items.length > 0 && items.every((u) => selected.has(u.id))} onChange={(e) => setSelected(e.target.checked ? new Set(items.map((u) => u.id)) : new Set())} />
                  </th>
                )}
                {visibleCols.map((c) => (
                  <th key={c} className="border-b border-line px-3 py-2 font-medium whitespace-nowrap">
                    <button type="button" onClick={() => sortBy(c)} className="cursor-pointer border-0 bg-transparent p-0 text-xs text-ink-2">
                      {COLUMNS.find((x) => x[0] === c)![1]}
                      {sort === c ? " ↑" : sort === `-${c}` ? " ↓" : ""}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((u) => (
                <tr key={u.id} onClick={() => setCard(`unit:${u.id}`)} className={cn("cursor-pointer hover:bg-surface-2", card === `unit:${u.id}` && "bg-accent-soft hover:bg-accent-soft", u.state === "written_off" && "text-ink-3")}>
                  {admin && (
                    <td className="border-b border-line px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Выбрать ${u.number}`} checked={selected.has(u.id)} onChange={() => toggle(u.id)} />
                    </td>
                  )}
                  {visibleCols.map((c) => (
                    <td key={c} className="border-b border-line px-3 py-2">
                      {cell(u, c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <div className="flex flex-wrap items-center gap-3 text-[13px] text-ink-2">
        <span>
          Показано {items.length} из {list.data?.total ?? 0}
          {admin && list.data?.sum_price !== undefined && ` · стоимость: ${money(list.data.sum_price)}, остаточная ${money(list.data.sum_value)}`}
        </span>
        {list.data && items.length < list.data.total && (
          <Button size="sm" onClick={() => setLimit(limit + 200)}>
            Показать ещё
          </Button>
        )}
        <div className="flex-1" />
        {admin && selected.size > 0 && (
          <span className="font-medium text-ink">
            Выбрано: {selected.size} · {money(chosen.reduce((s, u) => s + (u.price ?? 0), 0))}
          </span>
        )}
        {admin && (
          <>
            <Button size="sm" disabled={!selected.size} onClick={() => void printLabels({ unit_ids: [...selected] }).catch((e) => setError((e as Error).message))}>
              <QrCode /> Метки
            </Button>
            <Button size="sm" disabled={!selected.size} onClick={() => void move()}>
              <Truck /> Переместить
            </Button>
          </>
        )}
        <Button size="sm" asChild>
          <a href={exportUrl} download>
            <FileSpreadsheet /> Excel
          </a>
        </Button>
      </div>
      <Dialog open={chooser} onOpenChange={setChooser} title="Столбцы реестра">
        <div className="flex flex-col gap-2">
          {COLUMNS.filter(([c]) => (c !== "number" && c !== "price" && c !== "value") || admin).map(([c, t]) => (
            <label key={c} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={cols.includes(c)} onChange={(e) => setCols(e.target.checked ? COLUMNS.map((x) => x[0]).filter((x) => x === c || cols.includes(x)) : cols.filter((x) => x !== c))} /> {t}
            </label>
          ))}
        </div>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------- остатки (5.4.3)

function BalancesTab() {
  const [at, setAt] = useState(today());
  const [place, setPlace] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["inventory", "balances", at, place], queryFn: () => get<{ items: Balance[] }>(`/api/inventory/balances${query({ at, place: place ?? undefined })}`) });
  const total = (list.data?.items ?? []).reduce((s, b) => s + (b.amount ?? 0), 0);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-[13px] text-ink-2">
          на дату
          <input type="date" aria-label="Остатки на дату" value={at} max={today()} onChange={(e) => setAt(e.target.value || today())} className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm" />
        </label>
        <PlacePicker value={place} onChange={setPlace} allowEmpty emptyTitle="все места" className="w-auto max-w-sm" />
      </div>
      <Card className="overflow-x-auto">
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.items.length ? (
          <Empty title="Остатков нет">То, что учитывается количеством (расходные материалы, стулья, светильники), появляется здесь после прихода или ввода остатков.</Empty>
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-2">
                {["Место", "Наименование", "Количество", "Средняя цена", "Стоимость"].map((h) => (
                  <th key={h} className="border-b border-line px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((b) => (
                <tr key={`${b.place}${b.type_id}${b.model_id}`}>
                  <td className="border-b border-line px-3 py-2">{b.place_title}</td>
                  <td className="border-b border-line px-3 py-2 font-medium">
                    {b.type_name} {b.model_name && <span className="font-normal text-ink-2">{b.model_name}</span>}
                  </td>
                  <td className="border-b border-line px-3 py-2 font-mono">
                    {b.qty.toLocaleString("ru-RU")} {b.unit}
                  </td>
                  <td className="border-b border-line px-3 py-2 font-mono">{money(b.avg_price)}</td>
                  <td className="border-b border-line px-3 py-2 font-mono">{money(b.amount)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={4} className="px-3 py-2 font-medium">
                  Итого
                </td>
                <td className="px-3 py-2 font-mono font-medium">{money(total)}</td>
              </tr>
            </tfoot>
          </table>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- стоимость на дату (С19)

const GROUPS: [string, string][] = [
  ["building", "здание"],
  ["floor", "этаж"],
  ["place", "место"],
  ["layer", "слой"],
  ["type", "тип"],
  ["department", "подразделение"],
];

interface Statement {
  at: string;
  group_titles: string[];
  rows: { group: string[]; units: number; stock_positions: number; initial: number; value: number }[];
  total: { units: number; initial: number; value: number };
}

function CostTab() {
  const [at, setAt] = useState(today());
  const [groups, setGroups] = useState<string[]>(["building", "floor", "layer"]);
  const params = { at, group_by: groups.join(",") };
  const st = useQuery({ queryKey: ["inventory", "cost", params], queryFn: () => get<Statement>(`/api/inventory/cost${query(params)}`) });
  const toggle = (g: string) => setGroups((list) => (list.includes(g) ? list.filter((x) => x !== g) : GROUPS.map((x) => x[0]).filter((x) => x === g || list.includes(x))));
  const titles = useMemo(() => st.data?.group_titles ?? [], [st.data]);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-[13px] text-ink-2">
          на дату
          <input type="date" aria-label="Стоимость на дату" value={at} max={today()} onChange={(e) => setAt(e.target.value || today())} className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm" />
        </label>
        <span className="text-[13px] text-ink-2">с разбивкой по</span>
        {GROUPS.map(([g, t]) => (
          <label key={g} className="flex items-center gap-1.5 text-[13px]">
            <input type="checkbox" checked={groups.includes(g)} onChange={() => toggle(g)} /> {t}
          </label>
        ))}
        <div className="flex-1" />
        <Button size="sm" asChild>
          <a href={`/api/inventory/cost.xlsx${query(params)}`} download>
            <Download /> Excel
          </a>
        </Button>
      </div>
      <Card className="overflow-x-auto">
        {st.isLoading || !st.data ? (
          <Loading />
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-2">
                {[...titles, "Единиц", "Первоначальная", "Остаточная"].map((h) => (
                  <th key={h} className="border-b border-line px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {st.data.rows.map((r, i) => (
                <tr key={i}>
                  {r.group.map((g, j) => (
                    <td key={j} className="border-b border-line px-3 py-2">
                      {g}
                    </td>
                  ))}
                  <td className="border-b border-line px-3 py-2 font-mono">{r.units || "—"}</td>
                  <td className="border-b border-line px-3 py-2 font-mono">{money(r.initial)}</td>
                  <td className="border-b border-line px-3 py-2 font-mono">{money(r.value)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="font-medium">
                <td colSpan={Math.max(1, titles.length)} className="px-3 py-2">
                  Итого на {dateRu(st.data.at)}
                </td>
                <td className="px-3 py-2 font-mono">{st.data.total.units}</td>
                <td className="px-3 py-2 font-mono">{money(st.data.total.initial)}</td>
                <td className="px-3 py-2 font-mono">{money(st.data.total.value)}</td>
              </tr>
            </tfoot>
          </table>
        )}
      </Card>
    </div>
  );
}
